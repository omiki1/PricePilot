"""L2 摘要提取 Agent（主笔：B）

策略：增量摘要 —— 「旧摘要 + 新对话 → 新摘要」，避免每轮重压全量历史。
触发条件不在这里判断，由 MemoryManager 统一调度（课程文档口径）。
"""
from __future__ import annotations

import logging

from app.ai.memory.retrieval.base import ask, resolve_model

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """你是一个对话摘要助手。
你的任务：根据【历史摘要】和【最近聊天记录】生成新的摘要。

要求：
1. 保留重要信息（用户的需求、预算、已经确定的条件、已排除的选项）
2. 去掉闲聊内容
3. 避免重复
4. 控制在 200 字以内
5. 使用第三人称描述
6. 只返回新的摘要，不要任何解释或标题

如果没有历史摘要，就只根据最近聊天记录生成。
"""


def render_messages(messages) -> str:
    """把窗口消息渲染成 `role: content` 多行文本（兼容 dict 与消息对象）。"""
    lines = []
    for message in messages:
        if isinstance(message, dict):
            role, content = message.get("role"), message.get("content")
        else:
            role = getattr(message, "type", None) or getattr(message, "role", "user")
            content = getattr(message, "content", "")
        lines.append(f"{role}：{content}")
    return "\n".join(lines)


class SummaryAgent:
    def __init__(self, summary_memory, model=None):
        self.summary_memory = summary_memory
        self.model = resolve_model(model)

    def summarize(self, old_summary: str, messages) -> str | None:
        """只生成不落库。"""
        payload = (
            f"历史摘要：{old_summary or '（暂无）'}\n"
            f"最近聊天记录：\n{render_messages(messages)}\n"
            f"请生成新的摘要："
        )
        return ask(self.model, SUMMARY_PROMPT, payload)

    def update(self, session_id, messages) -> str | None:
        """读取旧摘要 → 生成新摘要 → UPSERT 落库，返回新摘要（失败返回 None）。"""
        try:
            old_summary = self.summary_memory.load(session_id)
        except Exception as exc:                      # noqa: BLE001
            logger.warning("L2 读取旧摘要失败（跳过本轮摘要）：%s", exc)
            return None

        summary = self.summarize(old_summary, messages)
        if not summary:
            return None
        try:
            self.summary_memory.save(session_id, summary)
        except Exception as exc:                      # noqa: BLE001
            logger.warning("L2 摘要落库失败：%s", exc)
            return None
        logger.info("L2 摘要已更新 session=%s，长度=%d", session_id, len(summary))
        return summary
