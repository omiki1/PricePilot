"""PostgreSQL 摘要存储；同步驱动配合线程，兼容 Windows 事件循环。"""

import asyncio
import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

_conninfo = os.getenv("POSTGRESQL_URL") or (
    "host=127.0.0.1 port=5432 dbname=postgres user=postgres connect_timeout=3"
)


class SummaryMemory:
    """一次会话一份摘要，按 session_id UPSERT 覆盖。"""

    def __init__(self, session_id):
        self.session_id = session_id
        self.conninfo = _conninfo

    # ── 同步实现（真正的数据库操作）──
    def _save_sync(self, summary: str):
        # 连接数据库
        with psycopg.connect(self.conninfo, connect_timeout=5,) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversation_summary(session_id, summary)
                    VALUES(%s, %s)
                    ON CONFLICT(session_id)
                    DO UPDATE SET summary = EXCLUDED.summary, update_time = NOW()
                    """,
                    (str(self.session_id), summary),
                )
            conn.commit()

    def _query_sync(self) -> str:
        # 连接数据库
        with psycopg.connect(self.conninfo, connect_timeout=5,) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT summary FROM conversation_summary WHERE session_id = %s",
                    (str(self.session_id),),
                )
                row = cur.fetchone()
                return row[0] if row else ""

    # ── 对外的异步接口：丢线程池，不阻塞事件循环 ──
    async def save(self, summary: str):
        await asyncio.to_thread(self._save_sync, summary)

    async def query(self) -> str:
        return await asyncio.to_thread(self._query_sync)
