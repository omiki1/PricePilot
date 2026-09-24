"""L3 长期记忆提取 Agent（主笔：B）

策略：过滤 + 精炼（课程文档口径）。
    判断用户输入里是否含值得长期保存的信息（偏好 / 长期计划 / 技能 / 兴趣 / 身份）；
    不需要保存 → 模型输出 NONE → 丢弃；
    需要保存 → 输出一句话 → 写入向量库。

注意：本层写「一句话的自然语言事实」，不写结构化字段（那是 L4 的活）。
"""
from __future__ import annotations

import logging

from app.ai.memory.retrieval.base import ask, resolve_model

logger = logging.getLogger(__name__)

LONG_MEMORY_PROMPT = """你是一个长期记忆提取助手。
请判断下面内容是否值得长期保存。

值得长期保存的范围：用户偏好（喜欢/不喜欢什么）、长期计划、技能、兴趣、身份、常用条件。
不值得保存的内容：寒暄、一次性问题、当前这段话里的临时信息（比如"帮我看下这个"）。

规则：
- 如果不需要保存，只返回 NONE（大写，不要任何其他字符）
- 如果需要保存，只返回一句话，第三人称，不超过 40 字，不要解释、不要标点堆砌
- 不要编造用户没说过的事实
"""

SKIP_MARKER = "NONE"


class LongMemoryAgent:
    def __init__(self, long_memory, model=None):
        self.long_memory = long_memory
        self.model = resolve_model(model)

    def extract(self, user_input: str) -> str | None:
        """只提取不落库。返回一句话或 None（表示不值得保存）。"""
        text = ask(self.model, LONG_MEMORY_PROMPT, user_input)
        if text is None:
            return None
        first_line = text.strip().splitlines()[0].strip().strip('"“”')
        if not first_line or first_line.upper().startswith(SKIP_MARKER):
            return None
        return first_line

    def update(self, user_id, user_input: str) -> str | None:
        """提取并写入向量库，返回写入的记忆（没写则 None）。"""
        memory = self.extract(user_input)
        if not memory:
            logger.info("L3 判断为无需长期保存")
            return None
        try:
            self.long_memory.save(user_id, memory)
        except Exception as exc:                      # noqa: BLE001
            logger.warning("L3 写入失败（不影响对话）：%s", exc)
            return None
        logger.info("L3 长期记忆 +1 %s：%s", user_id, memory)
        return memory
