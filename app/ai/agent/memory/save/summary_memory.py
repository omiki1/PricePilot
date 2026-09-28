"""L2 摘要记忆（PostgreSQL）。

为什么用**同步** psycopg 而不是 AsyncConnectionPool：
    psycopg 的异步模式需要 SelectorEventLoop，而 uvicorn 在 Windows 上
    硬编码返回 ProactorEventLoop（uvicorn/loops/asyncio.py）：
        if sys.platform == "win32" and not use_subprocess:
            return asyncio.ProactorEventLoop
    set_event_loop_policy() 也管不着它 —— 那行是直接返回类，不看 policy。
    于是异步连接必然报：
        "Psycopg cannot use the 'ProactorEventLoop' to run in async mode"

    改成同步驱动 + asyncio.to_thread：连接在哪个线程跑都行，
    和事件循环类型无关，uvicorn / 脚本 / 测试里都能用。

表结构见 db/schema_memory_pg.sql（session_id 是 TEXT，不是 integer）。
"""

import asyncio
import os

import psycopg
from psycopg.rows import tuple_row
from dotenv import load_dotenv

load_dotenv()

_conninfo = os.getenv("POSTGRESQL_URL") or (
    "host=127.0.0.1 port=5432 dbname=postgres user=postgres connect_timeout=3"
)


class SummaryMemory:
    """一次会话一份摘要，按 session_id UPSERT 覆盖。"""

    def __init__(self, session_id, conninfo: str = ""):
        self.session_id = session_id
        self.conninfo = conninfo or _conninfo

    # ── 同步实现（真正的数据库操作）──
    def _save_sync(self, summary: str):
        with psycopg.connect(self.conninfo, connect_timeout=5, row_factory=tuple_row) as conn:
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
        with psycopg.connect(self.conninfo, connect_timeout=5, row_factory=tuple_row) as conn:
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
