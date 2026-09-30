"""只读查看统计数据库：表结构、累计次数、按住时长、会话、今日数据。

用法: python -X utf8 tools/db_report.py [--db F:\\KeyMouseMonitor\\stats.db] [--top 12]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=r"F:\KeyMouseMonitor\stats.db")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    db = os.path.abspath(args.db)
    if not os.path.exists(db):
        print(f"数据库不存在: {db}")
        return 1
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cur = conn.cursor()

    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print(f"数据库: {db}")
    print(f"文件大小: {os.path.getsize(db) / 1024:.1f} KB")
    print(f"表: {tables}")

    print("\n== meta ==")
    for k, v in cur.execute("SELECT k, v FROM meta"):
        print(f"  {k} = {v}")

    print(f"\n== 累计次数 Top {args.top} ==")
    rows = list(cur.execute("SELECT key, n FROM key_total ORDER BY n DESC LIMIT ?",
                            (args.top,)))
    for k, n in rows:
        print(f"  {k:<12} {n:>10,}")
    total_keys = cur.execute(
        "SELECT COALESCE(SUM(n),0) FROM key_total WHERE key NOT LIKE 'Mouse%' "
        "AND key NOT LIKE 'Wheel%'").fetchone()[0]
    total_clicks = cur.execute(
        "SELECT COALESCE(SUM(n),0) FROM key_total WHERE key LIKE 'Mouse%' "
        "OR key LIKE 'Wheel%'").fetchone()[0]
    print(f"  键盘合计 {total_keys:,} / 鼠标合计 {total_clicks:,}")

    if "dur_total" in tables:
        print(f"\n== 按住时长 Top {args.top} ==")
        for k, ms in cur.execute(
                "SELECT key, ms FROM dur_total ORDER BY ms DESC LIMIT ?", (args.top,)):
            print(f"  {k:<12} {ms / 1000:>10.1f} 秒")
        tot_ms = cur.execute("SELECT COALESCE(SUM(ms),0) FROM dur_total").fetchone()[0]
        print(f"  累计按住 {tot_ms / 3600000:.1f} 小时")

    print("\n== 移动距离 ==")
    for day, px in cur.execute("SELECT day, px FROM move_day ORDER BY day DESC LIMIT 5"):
        print(f"  {day}  {px / 3779.53:>8.1f} m")

    today = time.strftime("%Y-%m-%d")
    print(f"\n== 今日 ({today}) ==")
    kd = list(cur.execute("SELECT key, n FROM key_day WHERE day=? ORDER BY n DESC "
                          "LIMIT 8", (today,)))
    print(f"  次数: {kd if kd else '（今天还没有数据）'}")
    if "dur_day" in tables:
        dd = list(cur.execute("SELECT key, ms FROM dur_day WHERE day=? ORDER BY ms DESC "
                              "LIMIT 8", (today,)))
        print(f"  按住: {[(k, f'{ms / 1000:.1f}s') for k, ms in dd] if dd else '（暂无）'}")

    if "session" in tables:
        print("\n== 最近会话 ==")
        cols = [d[1] for d in cur.execute("PRAGMA table_info(session)")]
        for row in cur.execute(f"SELECT {','.join(cols)} FROM session ORDER BY id DESC "
                               "LIMIT 5"):
            print("  " + ", ".join(f"{c}={v}" for c, v in zip(cols, row)))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
