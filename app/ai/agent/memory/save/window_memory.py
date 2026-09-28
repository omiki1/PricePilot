import json
import os

import redis.asyncio as redis
from dotenv import load_dotenv

load_dotenv()


class WindowMemory:
    """L1 窗口记忆：Redis List，按 session_id 存最近的原始消息。

    window_size 的语义是「保留的消息条数」（与课程文档 ltrim 口径一致）。
    user 和 ai 各算一条，所以 WINDOW_MEMORY_ROUNDS=40 实际是最近 20 轮。
    """

    def __init__(self, session_id, host=None, port=None, db=None):
        self.redis = redis.StrictRedis(
            host=host or os.getenv("REDIS_HOST", "localhost"),
            port=int(port or os.getenv("REDIS_PORT", 6379)),
            db=int(db if db is not None else os.getenv("REDIS_DB", 0)),
            socket_timeout=3,
            decode_responses=True,
        )
        self.window_size = int(os.getenv("WINDOW_MEMORY_ROUNDS") or 40)
        self.session_id = session_id
        self.key = f"window_memory:{self.session_id}"
        self.window_limit_time = int(os.getenv("WINDOW_MEMORY_TIME") or 86400)

    async def save(self, role: str, content: str):
        data = {"role": role, "content": content}
        await self.redis.rpush(self.key, json.dumps(data, ensure_ascii=False))
        await self.redis.ltrim(self.key, -self.window_size, -1)
        await self.redis.expire(self.key, self.window_limit_time)

    async def query(self):
        """返回消息列表；没有记录时返回空列表。

        原来键不存在时返回 None，调用方一 for 就 TypeError —— 统一成 []，
        调用方少一层判空。
        """
        if not await self.redis.exists(self.key):
            return []
        data = await self.redis.lrange(self.key, 0, -1)
        return [json.loads(i) for i in data]

    async def clear(self):
        await self.redis.delete(self.key)
