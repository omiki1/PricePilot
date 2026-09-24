"""L2 摘要记忆 —— PostgreSQL 持久化（主笔：B）

课程文档口径：表 conversation_summary，UPSERT 语义
    INSERT ... ON CONFLICT(session_id) DO UPDATE SET summary=EXCLUDED.summary, update_time=NOW()

一处工程化处理：文档把连接池写死在类里，这里改成懒加载 + 可用性降级——
    Redis 没起、PG 没起都不该让整个对话流程崩掉。记忆是增强，不是主链路。
"""
from __future__ import annotations

import re
import threading

from app.ai.memory import config

_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SummaryUnavailable(RuntimeError):
    """摘要记忆不可用（驱动缺失或数据库连不上）。调用方应降级，不要中断对话。"""


class SummaryMemory:
    """按 session_id 存一段对话摘要，一个会话一条，UPSERT 覆盖。"""

    def __init__(self, conninfo: str | None = None, table: str | None = None, *, pool=None):
        self.conninfo = conninfo or config.POSTGRESQL_URL
        self.table = table or config.SUMMARY_TABLE
        if not _SAFE_IDENT.match(self.table):
            raise ValueError(f"非法表名：{self.table}")
        self._pool = pool
        self._lock = threading.Lock()
        self._ready = False

    # ── 连接池与建表 ──
    def _ensure(self):
        if self._ready:
            return self._pool
        with self._lock:
            if self._ready:
                return self._pool
            if self._pool is None:
                try:
                    from psycopg_pool import ConnectionPool
                except ImportError as exc:
                    raise SummaryUnavailable(
                        "缺少 psycopg 驱动：pip install \"psycopg[binary,pool]\"") from exc
                # open=False：构造时不连库，避免 import 阶段就把服务拖住
                # connect_timeout=3：连不上时快速失败。不给这个参数，
                # 后台重连线程会卡在默认超时里，进程退出时报
                # "couldn't stop thread 'pool-N-worker-0' within 5.0 seconds"。
                self._pool = ConnectionPool(
                    self.conninfo, min_size=1, max_size=5, open=False,
                    kwargs={"connect_timeout": 3})
            try:
                self._pool.open(wait=True, timeout=8)
            except Exception as exc:                 # noqa: BLE001
                # 连接失败要顺手把池关掉：否则后台重连线程会一直挂着，
                # 进程退出时表现为 "couldn't stop thread ... within 5.0 seconds"
                try:
                    self._pool.close()
                except Exception:                    # noqa: BLE001
                    pass
                self._pool = None
                raise SummaryUnavailable(f"PostgreSQL 连接失败：{exc}") from exc
            self._create_table()
            self._ready = True
            return self._pool

    def _create_table(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    session_id  TEXT PRIMARY KEY,
                    summary     TEXT NOT NULL,
                    create_time TIMESTAMP DEFAULT NOW(),
                    update_time TIMESTAMP DEFAULT NOW()
                )
                """
            )

    # ── 读写 ──
    def load(self, session_id) -> str:
        """读取指定会话的摘要；没有则返回空字符串。"""
        pool = self._ensure()
        with pool.connection() as conn:
            row = conn.execute(
                f"SELECT summary FROM {self.table} WHERE session_id=%s",
                (str(session_id),),
            ).fetchone()
        return row[0] if row else ""

    def save(self, session_id, summary: str) -> None:
        """写入或更新摘要（UPSERT）。"""
        pool = self._ensure()
        with pool.connection() as conn:
            conn.execute(
                f"""
                INSERT INTO {self.table}(session_id, summary)
                VALUES(%s, %s)
                ON CONFLICT(session_id)
                DO UPDATE SET summary=EXCLUDED.summary, update_time=NOW()
                """,
                (str(session_id), summary),
            )

    def delete(self, session_id) -> None:
        pool = self._ensure()
        with pool.connection() as conn:
            conn.execute(f"DELETE FROM {self.table} WHERE session_id=%s", (str(session_id),))

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._ready = False
