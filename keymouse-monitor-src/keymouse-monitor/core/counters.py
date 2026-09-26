"""统计聚合：内存缓冲 + 定时落库 + 供 UI 读取的实时口径。"""

from __future__ import annotations

import threading
import time
import traceback

from . import keymap as km
from .store import Store, now_str, today_str

FLUSH_INTERVAL = 3.0


class Counters:
    """线程安全的内存计数器。

    - 钩子回调调用 `on_key/on_click/on_move`（极短临界区）。
    - 后台线程每 FLUSH_INTERVAL 秒把增量写入 SQLite 并合并进内存快照。
    - UI 读取 `stats_for()` 时会叠加尚未落库的增量，所以显示是实时的。
    """

    def __init__(self, store: Store, flush_interval: float = FLUSH_INTERVAL):
        self.store = store
        self.flush_interval = flush_interval
        self.lock = threading.RLock()

        snap = store.load(days=8)
        self.totals: dict[str, int] = snap["totals"]
        self.by_day: dict[str, dict[str, int]] = snap["by_day"]
        self.move_total: float = snap["move_total"]
        self.move_day: dict[str, float] = snap["move_day"]
        # 按住时长（毫秒）
        self.dur_totals: dict[str, int] = snap.get("dur_totals", {})
        self.dur_by_day: dict[str, dict[str, int]] = snap.get("dur_by_day", {})
        self.first_run: str = snap["first_run"] or now_str()
        self.session_count: int = snap["sessions"]

        self._cur_day = today_str()
        self._days7: list[str] = [today_str(-i) for i in range(6, -1, -1)]
        self.buf: dict[str, dict[str, int]] = {self._cur_day: {}}
        self.px_buf: dict[str, float] = {self._cur_day: 0.0}
        self.dur_buf: dict[str, dict[str, int]] = {self._cur_day: {}}

        # 本次运行
        self.session_started = now_str()
        # 兜底：即使没有调用 start()（只读脚本/测试直接构造 Counters），
        # 界面刷新也不该因为缺少这个时间戳而崩
        self._session_start_ts = time.time()
        self.session_keys = 0
        self.session_clicks = 0
        self.session_px = 0.0
        self.session_hold_ms = 0
        self.paused = False

        self.last_flush_ts: float = 0.0
        self.flush_errors = 0
        self.last_error: str | None = None
        self.flushed_rows = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending_session_write = False

    # ------------------------------------------------------------ 写入路径
    def on_key(self, key_id: str) -> None:
        with self.lock:
            self.session_keys += 1
            d = self.buf.get(self._cur_day)
            if d is None:
                d = self.buf[self._cur_day] = {}
            d[key_id] = d.get(key_id, 0) + 1

    def on_click(self, key_id: str) -> None:
        with self.lock:
            self.session_clicks += 1
            d = self.buf.get(self._cur_day)
            if d is None:
                d = self.buf[self._cur_day] = {}
            d[key_id] = d.get(key_id, 0) + 1

    def on_move(self, dist: float) -> None:
        with self.lock:
            self.session_px += dist
            self.px_buf[self._cur_day] = self.px_buf.get(self._cur_day, 0.0) + dist

    def on_hold(self, key_id: str, ms: int) -> None:
        """记录一次"按住不放"的时长（毫秒）。"""
        ms = int(ms)
        if ms <= 0:
            return
        with self.lock:
            self.session_hold_ms += ms
            d = self.dur_buf.get(self._cur_day)
            if d is None:
                d = self.dur_buf[self._cur_day] = {}
            d[key_id] = d.get(key_id, 0) + ms

    def toggle_pause(self) -> bool:
        with self.lock:
            self.paused = not self.paused
            return self.paused

    # ------------------------------------------------------------ 读取路径
    def _roll_day(self) -> None:
        """跨天时切换缓冲（需持锁）。"""
        day = today_str()
        if day != self._cur_day:
            self._cur_day = day
            self._days7 = [today_str(-i) for i in range(6, -1, -1)]
            self.buf.setdefault(day, {})
            self.px_buf.setdefault(day, 0.0)
            self.dur_buf.setdefault(day, {})

    def stats_for(self, key_id: str) -> dict:
        """返回 {total, week, today}（含未落库增量）。"""
        with self.lock:
            self._roll_day()
            total = self.totals.get(key_id, 0)
            for d in self.buf.values():
                total += d.get(key_id, 0)
            week = 0
            for day in self._days7:
                week += self.by_day.get(day, {}).get(key_id, 0)
                week += self.buf.get(day, {}).get(key_id, 0)
            today = self.by_day.get(self._cur_day, {}).get(key_id, 0)
            today += self.buf.get(self._cur_day, {}).get(key_id, 0)
            return {"total": total, "week": week, "today": today}

    def dur_stats_for(self, key_id: str) -> dict:
        """返回按住时长 {total, week, today}，单位毫秒（含未落库增量）。"""
        with self.lock:
            self._roll_day()
            total = self.dur_totals.get(key_id, 0)
            for d in self.dur_buf.values():
                total += d.get(key_id, 0)
            week = 0
            for day in self._days7:
                week += self.dur_by_day.get(day, {}).get(key_id, 0)
                week += self.dur_buf.get(day, {}).get(key_id, 0)
            today = self.dur_by_day.get(self._cur_day, {}).get(key_id, 0)
            today += self.dur_buf.get(self._cur_day, {}).get(key_id, 0)
            return {"total": total, "week": week, "today": today}

    def dur_overall_stats(self) -> dict:
        """全部键位汇总的按住时长（含未落库增量），单位毫秒。"""
        with self.lock:
            self._roll_day()
            total = sum(self.dur_totals.values())
            for d in self.dur_buf.values():
                total += sum(d.values())
            week = 0
            for day in self._days7:
                week += sum(self.dur_by_day.get(day, {}).values())
                week += sum(self.dur_buf.get(day, {}).values())
            today = sum(self.dur_by_day.get(self._cur_day, {}).values())
            today += sum(self.dur_buf.get(self._cur_day, {}).values())
            return {"total": total, "week": week, "today": today}

    def daily_series(self, key_id: str, n: int = 7) -> list[tuple[str, int]]:
        with self.lock:
            self._roll_day()
            days = [today_str(-i) for i in range(n - 1, -1, -1)]
            out = []
            for day in days:
                v = self.by_day.get(day, {}).get(key_id, 0)
                v += self.buf.get(day, {}).get(key_id, 0)
                out.append((day, v))
            return out

    def today_counts(self, key_ids) -> dict[str, int]:
        """供热力图使用：一次性取今日各键次数。"""
        with self.lock:
            self._roll_day()
            base = self.by_day.get(self._cur_day, {})
            pend = self.buf.get(self._cur_day, {})
            return {k: base.get(k, 0) + pend.get(k, 0) for k in key_ids}

    def overall_stats(self) -> dict:
        """全部键位汇总（含未落库增量）。"""
        with self.lock:
            self._roll_day()
            total = sum(self.totals.values())
            for d in self.buf.values():
                total += sum(d.values())
            today = sum(self.by_day.get(self._cur_day, {}).values())
            today += sum(self.buf.get(self._cur_day, {}).values())
            week = 0
            for day in self._days7:
                week += sum(self.by_day.get(day, {}).values())
                week += sum(self.buf.get(day, {}).values())
            return {"total": total, "week": week, "today": today}

    def overall_series(self, n: int = 7) -> list[tuple[str, int]]:
        with self.lock:
            self._roll_day()
            days = [today_str(-i) for i in range(n - 1, -1, -1)]
            out = []
            for day in days:
                v = sum(self.by_day.get(day, {}).values())
                v += sum(self.buf.get(day, {}).values())
                out.append((day, v))
            return out

    def move_stats(self) -> dict:
        with self.lock:
            self._roll_day()
            today = self.move_day.get(self._cur_day, 0.0) + self.px_buf.get(self._cur_day, 0.0)
            return {
                "total": self.move_total + sum(self.px_buf.values()),
                "today": today,
                "session": self.session_px,
            }

    def session_stats(self) -> dict:
        with self.lock:
            elapsed = max(1.0, time.time() - self._session_start_ts)
            keys = self.session_keys
            clicks = self.session_clicks
            return {
                "started": self.session_started,
                "keys": keys,
                "clicks": clicks,
                "px": self.session_px,
                "hold_ms": self.session_hold_ms,
                "elapsed": elapsed,
                "per_min": (keys + clicks) / (elapsed / 60.0),
            }

    # ------------------------------------------------------------ 落库线程
    def start(self) -> None:
        self._session_start_ts = time.time()
        self._thread = threading.Thread(target=self._loop, name="km-flush", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.flush_interval):
            try:
                self.flush_now()
            except Exception:
                with self.lock:
                    self.flush_errors += 1

    def flush_now(self, final: bool = False) -> None:
        with self.lock:
            self._roll_day()
            day_deltas = {d: kv for d, kv in self.buf.items() if kv}
            px_deltas = {d: v for d, v in self.px_buf.items() if v}
            dur_deltas = {d: kv for d, kv in self.dur_buf.items() if kv}
            move_total_now = self.move_total + sum(self.px_buf.values())
            session = {
                "started": self.session_started,
                "ended": now_str(),
                "keys": self.session_keys,
                "clicks": self.session_clicks,
                "px": self.session_px,
            }
            # 取出缓冲（写库期间新事件进入新缓冲）
            self.buf = {self._cur_day: {}}
            self.px_buf = {self._cur_day: 0.0}
            self.dur_buf = {self._cur_day: {}}
            if (not day_deltas and not px_deltas and not dur_deltas
                    and not self._pending_session_write):
                return
            self._pending_session_write = False

        try:
            self.store.flush(day_deltas, px_deltas, move_total_now, session, dur_deltas)
        except Exception:
            # 写失败：把增量还回缓冲，下次重试，绝不丢数
            with self.lock:
                for d, kv in day_deltas.items():
                    tgt = self.buf.setdefault(d, {})
                    for k, n in kv.items():
                        tgt[k] = tgt.get(k, 0) + n
                for d, v in px_deltas.items():
                    self.px_buf[d] = self.px_buf.get(d, 0.0) + v
                for d, kv in dur_deltas.items():
                    tgt = self.dur_buf.setdefault(d, {})
                    for k, ms in kv.items():
                        tgt[k] = tgt.get(k, 0) + ms
                self.flush_errors += 1
                self.last_error = traceback.format_exc()
                self._pending_session_write = True
            raise

        with self.lock:
            for d, kv in day_deltas.items():
                bucket = self.by_day.setdefault(d, {})
                for k, n in kv.items():
                    bucket[k] = bucket.get(k, 0) + n
                    self.totals[k] = self.totals.get(k, 0) + n
            for d, kv in dur_deltas.items():
                bucket = self.dur_by_day.setdefault(d, {})
                for k, ms in kv.items():
                    bucket[k] = bucket.get(k, 0) + ms
                    self.dur_totals[k] = self.dur_totals.get(k, 0) + ms
            for d, v in px_deltas.items():
                self.move_day[d] = self.move_day.get(d, 0.0) + v
            self.move_total = move_total_now
            self.last_flush_ts = time.time()
            self.flushed_rows += sum(len(kv) for kv in day_deltas.values())

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(5.0)
        try:
            self.flush_now(final=True)  # 退出前把最后一点增量写掉
        except Exception:
            pass

    # ------------------------------------------------------------ 汇总
    def category_totals(self) -> dict:
        with self.lock:
            mouse = set(km.MOUSE_KEYS)
            keys = clicks = 0
            for k, n in self.totals.items():
                if k in mouse:
                    clicks += n
                else:
                    keys += n
            for d in self.buf.values():
                for k, n in d.items():
                    if k in mouse:
                        clicks += n
                    else:
                        keys += n
            return {"keys": keys, "clicks": clicks}
