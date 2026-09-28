import redis.asyncio as redis


class ProfileMemory:
    """L4 用户画像：Redis Hash，一个用户一个 key，字段就是画像的各项属性。

    decode_responses=True：否则取回来是 bytes，拼接时要到处 .decode()，
    而且 hgetall 已经拿到值了，再逐个 hget 是白跑一趟。
    """

    def __init__(self, user_id, host="localhost", port=6379, db=0):
        self.redis = redis.StrictRedis(
            host=host, port=port, db=db, socket_timeout=3, decode_responses=True
        )
        self.key = f"profile:{user_id}"

    async def save(self, hashkey, value):
        await self.redis.hset(self.key, hashkey, str(value))

    async def query(self):
        rs = await self.redis.hgetall(self.key)
        if not rs:
            return ""
        return "".join(f"{k}:{v}\n" for k, v in rs.items())
