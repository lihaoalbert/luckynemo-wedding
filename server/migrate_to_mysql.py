"""SQLite → MySQL 存量数据一次性迁移（2026-08-11 迁 RDS）。

用法（ECS 上运行）：
    cd /opt/luckynemo/server && .venv/bin/python migrate_to_mysql.py

幂等（REPLACE INTO），可重复执行；跑完用行数对比验收。
.env 需已配好 MYSQL_HOST/USER/PASSWORD/NAME。
"""
import sqlite3
from pathlib import Path

import db_compat

SERVER_DIR = Path(__file__).resolve().parent

TABLES = ["leads", "questionnaires", "uploads", "mp_orders", "mp_jobs", "mp_devices",
          "mp_feedback", "mp_subs", "mp_assets", "mp_members", "mp_sessions",
          "mp_pay_orders", "mp_favs"]


def load_env() -> dict:
    env = {}
    f = SERVER_DIR / ".env"
    for line in f.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def main() -> None:
    env = load_env()
    src = sqlite3.connect(SERVER_DIR / "data" / "app.db")
    src.row_factory = sqlite3.Row
    dst = db_compat.connect_mysql(
        env["MYSQL_HOST"], env["MYSQL_USER"], env["MYSQL_PASSWORD"],
        env.get("MYSQL_NAME", "lucky_nemo"), int(env.get("MYSQL_PORT", "3306")))
    total = 0
    for t in TABLES:
        rows = src.execute(f"SELECT * FROM {t}").fetchall()
        if not rows:
            print(f"{t}: 0 行，跳过")
            continue
        cols = rows[0].keys()
        sql = f"REPLACE INTO {t} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        dst.executemany(sql, [tuple(r) for r in rows])
        dst.commit()
        total += len(rows)
        print(f"{t}: 迁移 {len(rows)} 行")
    print(f"完成，共 {total} 行")


if __name__ == "__main__":
    main()
