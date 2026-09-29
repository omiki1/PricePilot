import json
import os

import redis.asyncio as redis
from dotenv import load_dotenv

load_dotenv()


def _redis_conn(db_default: int = 0, **overrides):
    """按 .env 建 Redis 连接；overrides 里非 None 的项覆盖 .env。

    密码必须读 —— Redis 开了 requirepass 时，不传密码会报：
        AuthenticationError: HELLO must be called with the client already authenticated
    """
    kwargs = {
        "host": os.getenv("REDIS_HOST", "localhost"),
        "port": int(os.getenv("REDIS_PORT", 6379)),
        "db": int(os.getenv("REDIS_DB", db_default)),
        "socket_timeout": 3,
        "decode_responses": True,
    }
    password = os.getenv("REDIS_PASSWORD")
    if password:
        kwargs["password"] = password
    kwargs.update({k: v for k, v in overrides.items() if v is not None})
    return redis.StrictRedis(**kwargs)


class WindowMemory:
    """L1 窗口记忆：Redis List，按 session_id 存最近的原始消息。

    window_size 的语义是「保留的消息条数」（与课程文档 ltrim 口径一致）。
    user 和 ai 各算一条，所以 WINDOW_MEMORY_ROUNDS=40 实际是最近 20 轮。
    """

    def __init__(self, session_id, host=None, port=None, db=None, password=None):
        self.redis = _redis_conn(0, host=host, port=port, db=db, password=password)
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
