"""L1 窗口记忆 —— 基于 Redis List 的滑动窗口（主笔：B）

课程文档口径：rpush 追加 + ltrim 保留最近 N 条 + expire 自动过期。

本实现对文档做了一处必要修正（否则摘要记忆拿不到原料）：
    文档里窗口列表本身被 ltrim 到 N 条，而 SummaryAgent 又是从窗口里读「要压缩的对话」，
    窗口只剩 4 条时它永远只能看到最近 2 轮，增量摘要会不断丢掉中段信息。
    因此这里把两件事拆开：
      - 存储上限 WINDOW_STORE_MAX（默认 200 条）：列表实际保留的原文，供摘要压缩；
      - 取用窗口 WINDOW_SIZE（默认 4 条）：喂给模型/prompt 的最近消息。
    load() 默认按窗口取，load_all() 给摘要用。

另外用同一 key 下的 hash 记录「已摘要到第几条」，让 L2 的条件触发可以跨进程判断。
"""
from __future__ import annotations

import json
from typing import Any

import redis

from app.ai.memory import config


class WindowMemory:
    """一个会话的短期记忆（工作记忆）。"""

    def __init__(self, session_id, *, window_size: int | None = None,
                 ttl_seconds: int | None = None, store_max: int | None = None,
                 client: redis.Redis | None = None):
        self.session_id = session_id
        self.key = f"chat_window:{session_id}"
        self.meta_key = f"{self.key}:meta"
        self.window_size = window_size or config.WINDOW_SIZE
        self.ttl_seconds = ttl_seconds or config.WINDOW_TTL_SECONDS
        self.store_max = store_max or config.WINDOW_STORE_MAX
        self.client = client or redis.StrictRedis(
            host=config.REDIS_HOST, port=config.REDIS_PORT, db=config.REDIS_DB,
            decode_responses=True)

    # ── 写 ──
    def add(self, role: str, content: str) -> None:
        """追加一条消息并刷新过期时间。role 用 user / assistant（与模型消息口径一致）。"""
        msg = json.dumps({"role": role, "content": content}, ensure_ascii=False)
        pipe = self.client.pipeline()
        pipe.rpush(self.key, msg)
        pipe.ltrim(self.key, -self.store_max, -1)
        pipe.expire(self.key, self.ttl_seconds)
        pipe.hincrby(self.meta_key, "total", 1)
        pipe.expire(self.meta_key, self.ttl_seconds)
        pipe.execute()

    # ── 读 ──
    def load(self, limit: int | None = None) -> list[dict[str, Any]]:
        """取最近若干条消息（默认窗口大小）。给 PromptBuilder 用。"""
        limit = limit or self.window_size
        raw = self.client.lrange(self.key, -limit, -1)
        return [json.loads(item) for item in raw]

    def load_all(self) -> list[dict[str, Any]]:
        """取列表里的全部原文（最多 store_max 条）。给摘要提取用。"""
        raw = self.client.lrange(self.key, 0, -1)
        return [json.loads(item) for item in raw]

    def size(self) -> int:
        return int(self.client.llen(self.key) or 0)

    # ── 摘要进度（L2 的条件触发依据）──
    def total_messages(self) -> int:
        return int(self.client.hget(self.meta_key, "total") or 0)

    def messages_since_summary(self) -> int:
        summarized = int(self.client.hget(self.meta_key, "summarized") or 0)
        return max(self.total_messages() - summarized, 0)

    def mark_summarized(self) -> None:
        self.client.hset(self.meta_key, "summarized", self.total_messages())
        self.client.expire(self.meta_key, self.ttl_seconds)

    def render(self, limit: int | None = None) -> str:
        """把窗口渲染成 `role: content` 多行文本。"""
        return "\n".join(f"{m['role']}: {m['content']}" for m in self.load(limit))

    def clear(self) -> None:
        self.client.delete(self.key, self.meta_key)
