import os

import redis.asyncio as redis
from dotenv import load_dotenv

load_dotenv()


def _redis_conn(db_default: int = 0, **overrides):
    """按 .env 建 Redis 连接；overrides 里非 None 的项覆盖 .env。"""
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


class ProfileMemory:
    """L4 用户画像：Redis Hash，一个用户一个 key，字段就是画像的各项属性。

    decode_responses=True：否则取回来是 bytes，拼接时要到处 .decode()，
    而且 hgetall 已经拿到值了，再逐个 hget 是白跑一趟。
    """

    def __init__(self, user_id, host=None, port=None, db=None, password=None):
        self.redis = _redis_conn(0, host=host, port=port, db=db, password=password)
        self.key = f"profile:{user_id}"

    async def save(self, hashkey, value):
        await self.redis.hset(self.key, hashkey, str(value))

    async def query(self):
        rs = await self.redis.hgetall(self.key)
        if not rs:
            return ""
        return "".join(f"{k}:{v}\n" for k, v in rs.items())

    async def clear(self):
        """整份画像删掉，测试收尾和「重置用户」用。"""
        await self.redis.delete(self.key)
