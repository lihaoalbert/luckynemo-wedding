"""数据库双后端兼容层（2026-08-11 SQLite → RDS MySQL 迁移）。

默认 SQLite（本地开发/回退）；生产 .env 设 DB_BACKEND=mysql + MYSQL_* 后走 PyMySQL。
对上层（app.py / mp_worker.py）保持 sqlite3 风格接口，业务代码零改动：

- SQL 统一用 `?` 占位符，本层翻译为 MySQL 的 `%s`（跳过单引号字符串内的 ?）
- fetchone/fetchall 返回 Row：同时支持 row[0] 下标与 row["col"] 列名（对齐 sqlite3.Row）
- conn.row_factory 赋值兼容（no-op）
- 方言翻译：datetime('now') → NOW()；INSERT OR IGNORE → INSERT IGNORE；
  ON CONFLICT(...) DO NOTHING → INSERT IGNORE；
  ON CONFLICT(...) DO UPDATE SET x=excluded.x → ON DUPLICATE KEY UPDATE x=VALUES(x)

注意：pymysql 仅在 connect_mysql 时惰性 import（本地 sqlite 开发无需安装）。
"""
from __future__ import annotations

import re

# ----------------------------------------------------------------------
# SQL 方言翻译
# ----------------------------------------------------------------------
_RE_ON_CONFLICT_NOTHING = re.compile(r"\s*ON CONFLICT\([^)]*\)\s*DO NOTHING", re.IGNORECASE)
_RE_ON_CONFLICT_UPDATE = re.compile(r"ON CONFLICT\([^)]*\)\s*DO UPDATE SET", re.IGNORECASE)
_RE_EXCLUDED = re.compile(r"excluded\.(\w+)", re.IGNORECASE)


def _qmark_to_percent(sql: str) -> str:
    """? → %s，跳过单引号字符串字面量内的 ?。
    前置：字面 % 转义为 %%（pymysql 用 % 格式化参数，SQL 文本里的 % 如 LIKE 'image/%' 必须转义）。
    注意顺序：SQL 里本来没有 %s（占位符统一是 ?），先转义 % 再替换 ? 不会误伤。"""
    sql = sql.replace("%", "%%")
    out = []
    in_str = False
    for ch in sql:
        if ch == "'":
            in_str = not in_str
            out.append(ch)
        elif ch == "?" and not in_str:
            out.append("%s")
        else:
            out.append(ch)
    return "".join(out)


def translate(sql: str) -> str:
    """SQLite 方言 → MySQL 方言。"""
    s = sql
    # ON CONFLICT(...) DO NOTHING → INSERT IGNORE（去掉子句，改写动词）
    if _RE_ON_CONFLICT_NOTHING.search(s):
        s = _RE_ON_CONFLICT_NOTHING.sub("", s)
        s = re.sub(r"^\s*INSERT\s+INTO", "INSERT IGNORE INTO", s, flags=re.IGNORECASE)
    # INSERT OR IGNORE → INSERT IGNORE
    s = re.sub(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO", "INSERT IGNORE INTO", s, flags=re.IGNORECASE)
    # ON CONFLICT(...) DO UPDATE SET x=excluded.x → ON DUPLICATE KEY UPDATE x=VALUES(x)
    if _RE_ON_CONFLICT_UPDATE.search(s):
        s = _RE_ON_CONFLICT_UPDATE.sub("ON DUPLICATE KEY UPDATE", s)
        s = _RE_EXCLUDED.sub(r"VALUES(\1)", s)
    s = s.replace("datetime('now')", "NOW()")
    return _qmark_to_percent(s)


# ----------------------------------------------------------------------
# 行/游标/连接包装
# ----------------------------------------------------------------------
class Row:
    """同时支持下标与列名访问（对齐 sqlite3.Row 的两种用法）。"""

    __slots__ = ("_values", "_index")

    def __init__(self, values, columns):
        self._values = tuple(values)
        self._index = {c: i for i, c in enumerate(columns)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._index[key]]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return list(self._index)


class _Cursor:
    def __init__(self, cur):
        self._cur = cur

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    def _wrap(self, row):
        if row is None:
            return None
        return Row(row, [d[0] for d in self._cur.description])

    def fetchone(self):
        return self._wrap(self._cur.fetchone())

    def fetchall(self):
        return [self._wrap(r) for r in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class MyConn:
    """pymysql 连接的 sqlite3 风格包装。"""

    def __init__(self, raw):
        self._raw = raw

    # 兼容 sqlite 的 conn.row_factory 赋值（本层始终返回双访问 Row）
    @property
    def row_factory(self):
        return None

    @row_factory.setter
    def row_factory(self, _value):
        pass

    def execute(self, sql, params=()):
        cur = self._raw.cursor()
        cur.execute(translate(sql), params)
        return _Cursor(cur)

    def executemany(self, sql, seq_of_params):
        cur = self._raw.cursor()
        cur.executemany(translate(sql), seq_of_params)
        return _Cursor(cur)

    def commit(self):
        self._raw.commit()

    def close(self):
        self._raw.close()


# ----------------------------------------------------------------------
# MySQL 建表 DDL（与 SQLite 侧 _SCHEMA + _migrate 的最终列结构一致）
# ----------------------------------------------------------------------
MYSQL_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS leads(
       id INT PRIMARY KEY AUTO_INCREMENT,
       order_no VARCHAR(64) UNIQUE,
       name VARCHAR(128) NOT NULL, contact VARCHAR(128) NOT NULL,
       wedding_date VARCHAR(64), feishu_ok INT DEFAULT 0,
       created_at VARCHAR(40) NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS questionnaires(
       id INT PRIMARY KEY AUTO_INCREMENT,
       name VARCHAR(128) NOT NULL, contact VARCHAR(128) NOT NULL,
       fields_json TEXT NOT NULL, oss_key VARCHAR(255), feishu_ok INT DEFAULT 0,
       created_at VARCHAR(40) NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS uploads(
       id INT PRIMARY KEY AUTO_INCREMENT,
       contact VARCHAR(128) NOT NULL, filename VARCHAR(255) NOT NULL,
       oss_key VARCHAR(255) NOT NULL, size INT, content_type VARCHAR(64),
       created_at VARCHAR(40) NOT NULL, slot VARCHAR(16) DEFAULT '') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS mp_orders(
       id INT PRIMARY KEY AUTO_INCREMENT,
       order_no VARCHAR(64) UNIQUE, open_token VARCHAR(128) NOT NULL,
       status VARCHAR(16) NOT NULL DEFAULT 'created',
       auth_ok INT DEFAULT 0, free_used INT DEFAULT 0, paid_count INT DEFAULT 0,
       selection_json TEXT, created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
       asset_group_id VARCHAR(64) DEFAULT '', byted_token VARCHAR(128) DEFAULT '',
       auth_url TEXT, mode VARCHAR(16) DEFAULT '', share_token VARCHAR(32) DEFAULT '',
       ref VARCHAR(32) DEFAULT '', free_quota INT DEFAULT 1, ref_rewarded INT DEFAULT 0
       ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS mp_jobs(
       id INT PRIMARY KEY AUTO_INCREMENT,
       order_no VARCHAR(64) NOT NULL, kind VARCHAR(32) NOT NULL,
       payload_json TEXT NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'queued',
       result_json TEXT, created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
       INDEX idx_jobs_order (order_no)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS mp_devices(
       id INT PRIMARY KEY AUTO_INCREMENT,
       order_no VARCHAR(64) NOT NULL, open_token VARCHAR(128) NOT NULL,
       role VARCHAR(4) NOT NULL DEFAULT 'A', created_at VARCHAR(40) NOT NULL,
       UNIQUE KEY uk_device (order_no, open_token)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS mp_feedback(
       id INT PRIMARY KEY AUTO_INCREMENT,
       order_no VARCHAR(64) NOT NULL, type VARCHAR(16) NOT NULL DEFAULT 'other',
       text TEXT NOT NULL, images_json TEXT, status VARCHAR(16) NOT NULL DEFAULT 'new',
       created_at VARCHAR(40) NOT NULL, reply TEXT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS mp_subs(
       id INT PRIMARY KEY AUTO_INCREMENT,
       order_no VARCHAR(64) NOT NULL, openid VARCHAR(64) NOT NULL,
       used INT NOT NULL DEFAULT 0, created_at VARCHAR(40) NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS mp_assets(
       id INT PRIMARY KEY AUTO_INCREMENT,
       oss_key VARCHAR(255) UNIQUE, group_id VARCHAR(64), created_at VARCHAR(40) NOT NULL
       ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS mp_members(
       id INT PRIMARY KEY AUTO_INCREMENT,
       order_no VARCHAR(64) NOT NULL, role VARCHAR(4) NOT NULL,
       byted_token VARCHAR(128) DEFAULT '', auth_url TEXT,
       asset_group_id VARCHAR(64) DEFAULT '', auth_ok INT DEFAULT 0,
       created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
       UNIQUE KEY uk_member (order_no, role)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS mp_sessions(
       openid VARCHAR(64) PRIMARY KEY, session_key VARCHAR(128) NOT NULL,
       updated_at VARCHAR(40) NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS mp_pay_orders(
       out_trade_no VARCHAR(64) PRIMARY KEY, order_no VARCHAR(64) NOT NULL,
       openid VARCHAR(64) NOT NULL, product VARCHAR(32) NOT NULL,
       coins INT NOT NULL, grant_count INT NOT NULL,
       status VARCHAR(16) NOT NULL DEFAULT 'created',
       created_at VARCHAR(40) NOT NULL, paid_at VARCHAR(40) DEFAULT ''
       ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS mp_favs(
       openid VARCHAR(64) NOT NULL, series_id VARCHAR(64) NOT NULL,
       created_at VARCHAR(40) NOT NULL,
       PRIMARY KEY(openid, series_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]

_ensured = False


def ensure_mysql_schema(conn: MyConn) -> None:
    """建表（幂等，进程内只做一次）。"""
    global _ensured
    if _ensured:
        return
    for ddl in MYSQL_SCHEMA:
        conn.execute(ddl)
    conn.commit()
    _ensured = True


def connect_mysql(host: str, user: str, password: str, database: str,
                  port: int = 3306) -> MyConn:
    import pymysql  # 惰性导入：本地 sqlite 开发无需安装

    raw = pymysql.connect(host=host, port=port, user=user, password=password,
                          database=database, charset="utf8mb4", autocommit=False,
                          connect_timeout=5, read_timeout=30, write_timeout=30)
    conn = MyConn(raw)
    ensure_mysql_schema(conn)
    return conn
