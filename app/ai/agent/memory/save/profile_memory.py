
import redis.asyncio as redis

class ProfileMemory:
    """L4 用户画像：Redis Hash，一个用户一个 key，字段就是画像的各项属性。"""

    def __init__(self, user_id):
        self.redis = redis.StrictRedis(host="localhost", port=6379, db=0, socket_timeout=3)
        self.key = f"profile:{user_id}"

    # 保存
    async def save(self, hashkey, value):
        await self.redis.hset(self.key, hashkey, value)

    # 查询
    async def query(self):
        # 查询某个用户的用户画像
        rs = await self.redis.hgetall(self.key)
        data = ""
        if rs:
            for hashkey, value in rs.items():
                #value = await self.redis.hget(self.key, hashkey)
                data += f"{hashkey.decode()}:{value.decode()}\n"
        return data

    async def clear(self):
        """整份画像删掉，测试收尾和「重置用户」用。"""
        await self.redis.delete(self.key)
