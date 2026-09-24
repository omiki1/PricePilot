"""Prompt 构建器 —— 把四层记忆按固定顺序组装（主笔：B）

组装顺序（课程文档口径，不能乱）：
    [1] 基础角色设定
    [2] 历史摘要        ← L2 SummaryMemory
    [3] 长期记忆 Top-N  ← L3 LongMemory
    [4] 用户画像        ← L4 ProfileMemory
    [5] 最近聊天记录 + 当前问题  ← L1 WindowMemory

本层不调用 LLM，只做字符串组装；任何一层取不到就跳过（如实留白，不编造）。
"""
from __future__ import annotations

import logging

from app.ai.memory import config

logger = logging.getLogger(__name__)

DEFAULT_ROLE = (
    "你是一个有记忆能力的购物决策助手。"
    "你会记住用户的长期偏好、预算习惯和之前的对话摘要，"
    "并在回答时结合这些记忆；记忆里没有的信息不要编造。"
)


class PromptBuilder:
    def __init__(self, window, summary, long_memory, profile, user_id, session_id,
                 *, role: str | None = None, top_k: int | None = None):
        self.window = window
        self.summary = summary
        self.long_memory = long_memory
        self.profile = profile
        self.user_id = user_id
        self.session_id = session_id
        self.role = role or DEFAULT_ROLE
        self.top_k = top_k or config.LONG_MEMORY_TOP_K

    # ── 各层安全取数：拿不到就返回空，绝不中断组装 ──
    def _summary_text(self) -> str:
        try:
            return self.summary.load(self.session_id) or ""
        except Exception as exc:                      # noqa: BLE001
            logger.warning("组装 Prompt 时读取 L2 失败：%s", exc)
            return ""

    def _long_memories(self, question: str | None) -> list[str]:
        try:
            return self.long_memory.load(self.user_id, question=question, limit=self.top_k) or []
        except Exception as exc:                      # noqa: BLE001
            logger.warning("组装 Prompt 时检索 L3 失败：%s", exc)
            return []

    def _profile_text(self) -> str:
        try:
            return self.profile.render(self.user_id) or ""
        except Exception as exc:                      # noqa: BLE001
            logger.warning("组装 Prompt 时读取 L4 失败：%s", exc)
            return ""

    # ── 组装 ──
    def build_memory_block(self, question: str | None = None) -> str:
        """只出记忆段落（不含角色设定与当前问题）。

        用途：把记忆挂到已有节点上时，不需要改动别人的 prompt 结构，
        只要把这段拼在前面即可（见 app/ai/memory/README 的接入说明）。
        """
        blocks: list[str] = []

        summary_text = self._summary_text()
        if summary_text:
            blocks.append(f"【历史摘要】\n{summary_text}")

        memories = self._long_memories(question)
        if memories:
            blocks.append("【长期记忆】\n" + "\n".join(f"- {m}" for m in memories))

        profile_text = self._profile_text()
        if profile_text:
            blocks.append(f"【用户画像】\n{profile_text}")

        return "\n\n".join(blocks)

    def build(self, question: str | None = None) -> str:
        """出完整 Prompt 文本（角色 + 四层记忆 + 最近对话 + 当前问题）。"""
        parts = [self.role]
        memory_block = self.build_memory_block(question)
        if memory_block:
            parts.append(memory_block)

        try:
            recent = self.window.render()
        except Exception as exc:                      # noqa: BLE001
            logger.warning("组装 Prompt 时读取 L1 失败：%s", exc)
            recent = ""

        if recent:
            parts.append(f"【最近聊天记录】\n{recent}")
        if question:
            parts.append(f"user: {question}")
        return "\n\n".join(parts)

    def build_messages(self, question: str | None = None) -> list[dict]:
        """给 ChatOpenAI / LangChain 用的消息列表形式。"""
        return [{"role": "user", "content": self.build(question)}]
