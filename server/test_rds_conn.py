"""RDS 连通性测试：从 .env 读 MYSQL_* 配置连接并打印版本与表清单。"""
from pathlib import Path

import db_compat

env = {}
for line in (Path(__file__).parent / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        env.setdefault(k.strip(), v.strip())

conn = db_compat.connect_mysql(
    env["MYSQL_HOST"], env["MYSQL_USER"], env["MYSQL_PASSWORD"],
    env.get("MYSQL_NAME", "lucky_nemo"), int(env.get("MYSQL_PORT", "3306")))
print("MySQL 连接 OK:", conn.execute("SELECT VERSION()").fetchone()[0])
print("表清单:", [r[0] for r in conn.execute("SHOW TABLES").fetchall()])
conn.close()
