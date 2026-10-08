import json
import os
import redis.asyncio as redis

class WindowMemory:
    """L1 窗口记忆：Redis List，按 session_id 存最近的原始消息。"""

    def __init__(self, session_id):
        self.redis = redis.StrictRedis(host="localhost",port=6379,db=0)
        # 按消息条数保留，用户和助手的消息各占一条。
        self.window_size = int(os.getenv("WINDOW_MEMORY_ROUNDS") or 40)
        self.session_id = session_id
        self.key = f"window_memory:{self.session_id}"
        self.window_limit_time = int(os.getenv("WINDOW_MEMORY_TIME") or 86400)

    async def save(self, role: str, content: str):
        # 构建字典
        data = {"role": role, "content": content}
        # 添加到列表种
        await self.redis.rpush(self.key, json.dumps(data, ensure_ascii=False))
        # 设置保留窗口记忆
        await self.redis.ltrim(self.key, -self.window_size, -1)
        # 设置过期时间
        await self.redis.expire(self.key, self.window_limit_time)

    async def query(self):
        """返回消息列表；没有记录时返回空列表。"""
        # Redis 对不存在的列表直接返回空数组。
        data = await self.redis.lrange(self.key, 0, -1)
        return [json.loads(i) for i in data]

    async def clear(self):
        await self.redis.delete(self.key)
