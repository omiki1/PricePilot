"""L4 用户画像 —— Redis Hash 键值存储（主笔：B）

为什么用户画像不用向量库（课程文档的核心判断）：
    画像存的是「确定的事实」（姓名、职业、城市、预算习惯），需要精确查询；
    Redis HSET/HGETALL 是 O(1)，而向量检索要算嵌入、相似度还可能召不回来。
    两者的分工是：L3 存「一句话的偏好」，L4 存「有字段名的属性」。

字段覆盖策略：按字段覆盖更新（同名 key 直接覆盖），不做历史留痕——
留痕属于 L2/L3 的职责。
"""
from __future__ import annotations

from typing import Any, Mapping

import redis

from app.ai.memory import config


class ProfileMemory:
    """一个用户的结构化画像（跨会话长期有效，不设过期）。"""

    def __init__(self, user_id=None, *, client: redis.Redis | None = None):
        self.user_id = str(user_id) if user_id is not None else None
        self.client = client or redis.StrictRedis(
            host=config.REDIS_HOST, port=config.REDIS_PORT, db=config.REDIS_DB,
            decode_responses=True)

    def _key(self, user_id=None) -> str:
        target = user_id if user_id is not None else self.user_id
        if target is None:
            raise ValueError("缺少 user_id：ProfileMemory 需要知道画像属于谁")
        return f"chat_profile:{target}"

    # ── 写 ──
    def update(self, user_id, key: str, value: Any) -> None:
        """单字段更新。空值不写入——「不知道」不该覆盖掉已知的画像。"""
        if value is None or (isinstance(value, str) and not value.strip()):
            return
        self.client.hset(self._key(user_id), str(key), str(value))

    def update_many(self, user_id, mapping: Mapping[str, Any]) -> int:
        """批量更新，返回实际写入的字段数。"""
        payload = {
            str(k): str(v) for k, v in mapping.items()
            if v is not None and not (isinstance(v, str) and not v.strip())
        }
        if not payload:
            return 0
        # 逐字段 HSET 而不是 hset(key, mapping=...)：后者在不同 redis-py 版本上
        # 参数序列化不一致（实测本机报 wrong number of arguments），逐字段最稳。
        pipe = self.client.pipeline()
        for field, value in payload.items():
            pipe.hset(self._key(user_id), field, value)
        pipe.execute()
        return len(payload)

    def save(self, user_id, mapping: Mapping[str, Any]) -> int:
        """课程文档里的调用形式：save(user_id, {"name": "张三"})。"""
        return self.update_many(user_id, mapping)

    # ── 读 ──
    def load(self, user_id=None) -> dict[str, str]:
        """返回整个画像字典。"""
        return dict(self.client.hgetall(self._key(user_id)))

    def get(self, user_id, key: str, default=None):
        return self.client.hget(self._key(user_id), str(key)) or default

    def render(self, user_id=None) -> str:
        """渲染成 Prompt 里的 `- key: value` 多行文本。"""
        return "\n".join(f"- {k}: {v}" for k, v in self.load(user_id).items())

    def clear(self, user_id=None) -> None:
        self.client.delete(self._key(user_id))
