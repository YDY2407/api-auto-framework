"""
数据库客户端封装（用于接口自动化中的落库断言与脏数据清理）
说明：当前本地靶场使用内置 sqlite3；在企业真实项目中替换为 pymysql.connect(...) 即可，方法签名完全一致。
"""
import sqlite3
from typing import Any


class DBClient:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def fetch_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def execute(self, sql: str, params: tuple = ()) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.rowcount
