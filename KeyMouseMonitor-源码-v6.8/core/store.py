"""SQLite 持久层：按天明细 + 累计总数，永久保留。"""

from __future__ import annotations

import datetime as _dt
import os
import sqlite3
import threading
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT
);
CREATE TABLE IF NOT EXISTS key_day (
    day TEXT NOT NULL,
    key TEXT NOT NULL,
    n   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, key)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS key_total (
    key TEXT PRIMARY KEY,
    n   INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS move_day (
    day TEXT PRIMARY KEY,
    px  REAL NOT NULL DEFAULT 0
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS dur_day (
    day TEXT NOT NULL,
    key TEXT NOT NULL,
    ms  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, key)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS dur_total (
    key TEXT PRIMARY KEY,
    ms  INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS session (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT,
    ended   TEXT,
    keys    INTEGER DEFAULT 0,
    clicks  INTEGER DEFAULT 0,
    px      REAL    DEFAULT 0
);
"""


def today_str(offset_days: int = 0) -> str:
    return (_dt.date.today() + _dt.timedelta(days=offset_days)).isoformat()


def now_str() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class Store:
    """一个 Store 实例由采集后台线程独占写；读可通过 load_* 单独连接。"""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        # 必须是 RLock：close() 会在持有锁的情况下调用 set_meta()，
        # 普通 Lock 会在同一线程内二次获取时自死锁（导致退出时卡住不关）。
        self._lock = threading.RLock()
        # check_same_thread=False：连接由采集线程写入、UI 线程读取，
        # 所有访问都在 Store._lock 保护下串行化（sqlite3 线程安全的常规做法）。
        self._conn = sqlite3.connect(
            path, timeout=15, isolation_level=None, check_same_thread=False
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO meta(k, v) VALUES('first_run', ?)", (now_str(),)
        )
        # 启动时做一次轻量完整性检查 + WAL 合并，异常时暴露给界面
        self.integrity: str = "ok"
        try:
            row = self._conn.execute("PRAGMA quick_check").fetchone()
            self.integrity = str(row[0]) if row else "unknown"
            self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception as exc:
            self.integrity = f"检查失败: {exc}"
        # 上一次是否正确退出（用于判断是否发生过强杀/断电）
        prev_exit = self.get_meta("last_exit")
        self.prev_exit_clean = bool(prev_exit) and self.get_meta("session_open") != "1"
        self.set_meta("last_open", now_str())
        self.set_meta("session_open", "1")
        self._session_id: int | None = None

    # ------------------------------------------------------------ 读
    def load(self, days: int = 8) -> dict:
        """加载 UI 需要的快照：累计总数、近 N 天明细、移动距离。"""
        cur = self._conn.cursor()
        totals = {k: int(n) for k, n in cur.execute("SELECT key, n FROM key_total")}
        since = today_str(-(days - 1))
        by_day: dict[str, dict[str, int]] = {}
        for day, key, n in cur.execute(
            "SELECT day, key, n FROM key_day WHERE day >= ?", (since,)
        ):
            by_day.setdefault(day, {})[key] = int(n)
        move_total = float(self.get_meta("move_total_px", "0") or 0)
        move_day = {
            d: float(px) for d, px in cur.execute("SELECT day, px FROM move_day")
        }
        dur_totals = {
            k: int(ms) for k, ms in cur.execute("SELECT key, ms FROM dur_total")
        }
        dur_by_day: dict[str, dict[str, int]] = {}
        for day, key, ms in cur.execute(
            "SELECT day, key, ms FROM dur_day WHERE day >= ?", (since,)
        ):
            dur_by_day.setdefault(day, {})[key] = int(ms)
        return {
            "totals": totals,
            "by_day": by_day,
            "move_total": move_total,
            "move_day": move_day,
            "dur_totals": dur_totals,
            "dur_by_day": dur_by_day,
            "first_run": self.get_meta("first_run", ""),
            "sessions": int(
                cur.execute("SELECT COUNT(*) FROM session").fetchone()[0] or 0
            ),
        }

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta(k, v) VALUES(?, ?) "
                "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (key, str(value)),
            )

    # ------------------------------------------------------------ 写
    def flush(
        self,
        day_deltas: dict[str, dict[str, int]],
        px_deltas: dict[str, float],
        move_total: float,
        session: dict | None = None,
        dur_deltas: dict[str, dict[str, int]] | None = None,
    ) -> None:
        """把缓冲增量写入数据库。一个事务完成，崩溃也不会丢已提交数据。

        dur_deltas: {day: {key: 按住毫秒数}}，与次数分开累计。
        """
        if not day_deltas and not px_deltas and not dur_deltas:
            if session:
                self._write_session(session)
            return
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                rows = [
                    (day, key, n)
                    for day, kv in day_deltas.items()
                    for key, n in kv.items()
                    if n
                ]
                if rows:
                    cur.executemany(
                        "INSERT INTO key_day(day, key, n) VALUES(?,?,?) "
                        "ON CONFLICT(day,key) DO UPDATE SET n = n + excluded.n",
                        rows,
                    )
                    cur.executemany(
                        "INSERT INTO key_total(key, n) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET n = n + excluded.n",
                        [(key, n) for _, key, n in rows],
                    )
                pxs = [(d, p) for d, p in px_deltas.items() if p]
                if pxs:
                    cur.executemany(
                        "INSERT INTO move_day(day, px) VALUES(?,?) "
                        "ON CONFLICT(day) DO UPDATE SET px = px + excluded.px",
                        pxs,
                    )
                drows = [
                    (day, key, int(ms))
                    for day, kv in (dur_deltas or {}).items()
                    for key, ms in kv.items()
                    if ms
                ]
                if drows:
                    cur.executemany(
                        "INSERT INTO dur_day(day, key, ms) VALUES(?,?,?) "
                        "ON CONFLICT(day,key) DO UPDATE SET ms = ms + excluded.ms",
                        drows,
                    )
                    cur.executemany(
                        "INSERT INTO dur_total(key, ms) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET ms = ms + excluded.ms",
                        [(key, ms) for _, key, ms in drows],
                    )
                cur.execute(
                    "INSERT INTO meta(k, v) VALUES('move_total_px', ?) "
                    "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                    (repr(float(move_total)),),
                )
                if session:
                    self._write_session(session)
                cur.execute("COMMIT")
            except BaseException:
                cur.execute("ROLLBACK")
                raise

    def _write_session(self, session: dict) -> None:
        if self._session_id is None:
            cur = self._conn.execute(
                "INSERT INTO session(started, ended, keys, clicks, px) VALUES(?,?,?,?,?)",
                (
                    session.get("started", now_str()),
                    session.get("ended"),
                    int(session.get("keys", 0)),
                    int(session.get("clicks", 0)),
                    float(session.get("px", 0)),
                ),
            )
            self._session_id = int(cur.lastrowid)
        else:
            self._conn.execute(
                "UPDATE session SET ended=?, keys=?, clicks=?, px=? WHERE id=?",
                (
                    session.get("ended"),
                    int(session.get("keys", 0)),
                    int(session.get("clicks", 0)),
                    float(session.get("px", 0)),
                    self._session_id,
                ),
            )

    def close(self) -> None:
        with self._lock:
            try:
                self.set_meta("last_exit", now_str())
                self.set_meta("session_open", "0")
            except Exception:
                pass
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            self._conn.close()

    # ------------------------------------------------------------ 工具
    def db_size(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += os.path.getsize(self.path + suffix)
            except OSError:
                pass
        return total


def read_snapshot(path: str, days: int = 8) -> dict:
    """只读打开（供 --dump / 外部工具使用）。"""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        totals = {k: int(n) for k, n in cur.execute("SELECT key, n FROM key_total")}
        since = today_str(-(days - 1))
        by_day: dict[str, dict[str, int]] = {}
        for day, key, n in cur.execute(
            "SELECT day, key, n FROM key_day WHERE day >= ?", (since,)
        ):
            by_day.setdefault(day, {})[key] = int(n)
        move_day = {d: float(px) for d, px in cur.execute("SELECT day, px FROM move_day")}
        meta = {k: v for k, v in cur.execute("SELECT k, v FROM meta")}
        # 旧数据库可能还没有按住时长表（只读连接无法建表），缺失时按空处理
        try:
            dur_totals = {
                k: int(ms) for k, ms in cur.execute("SELECT key, ms FROM dur_total")
            }
            dur_by_day: dict[str, dict[str, int]] = {}
            for day, key, ms in cur.execute(
                "SELECT day, key, ms FROM dur_day WHERE day >= ?", (since,)
            ):
                dur_by_day.setdefault(day, {})[key] = int(ms)
        except sqlite3.OperationalError:
            dur_totals, dur_by_day = {}, {}
        return {
            "totals": totals,
            "by_day": by_day,
            "move_day": move_day,
            "dur_totals": dur_totals,
            "dur_by_day": dur_by_day,
            "meta": meta,
            "sessions": [
                dict(zip(("id", "started", "ended", "keys", "clicks", "px"), row))
                for row in cur.execute(
                    "SELECT id, started, ended, keys, clicks, px FROM session "
                    "ORDER BY id DESC LIMIT 10"
                )
            ],
        }
    finally:
        conn.close()


def key_totals_by_prefix(snapshot: dict, mouse: bool) -> int:
    from .keymap import MOUSE_KEYS

    ms = set(MOUSE_KEYS)
    total = 0
    for k, n in snapshot["totals"].items():
        if (k in ms) == mouse:
            total += int(n)
    return total


def iter_days_back(n: int) -> Iterable[str]:
    for i in range(n - 1, -1, -1):
        yield today_str(-i)
