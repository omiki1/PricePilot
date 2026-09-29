from app.ai.agent.memory.save.redis_client import create_redis_client


class ProfileMemory:
    """L4 用户画像：Redis Hash，一个用户一个 key，字段就是画像的各项属性。"""

    def __init__(self, user_id, host=None, port=None, db=None, password=None):
        self.redis = create_redis_client(0, host=host, port=port, db=db, password=password)
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
