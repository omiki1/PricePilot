"""记忆更新调度器 —— 每轮对话结束后触发（主笔：B）

调度策略（课程文档口径）：
    ProfileAgent    (L4)  每轮必执行
    LongMemoryAgent (L3)  每轮必执行
    SummaryAgent    (L2)  条件触发（窗口里未摘要的消息数达到阈值）

阈值说明：课程文档写「窗口消息 ≥ 10」，那是在 40 条窗口下的取值。
本项目窗口 4 条，按 10 永远触发不了，所以阈值默认取「窗口条数 × 2」，
语义不变（攒够了才压一次），但能被观察到。
"""
from __future__ import annotations

import logging

from app.ai.memory import config
from app.ai.memory.retrieval.long_memory_agent import LongMemoryAgent
from app.ai.memory.retrieval.profile_agent import ProfileAgent
from app.ai.memory.retrieval.summary_agent import SummaryAgent

logger = logging.getLogger(__name__)


class MemoryManager:
    def __init__(self, conversation, *, model=None, trigger_messages: int | None = None):
        self.conversation = conversation
        self.user_id = conversation.user_id
        self.session_id = conversation.session_id
        self.window = conversation.window
        self.trigger_messages = trigger_messages or config.SUMMARY_TRIGGER_MESSAGES

        self.profile_agent = ProfileAgent(conversation.profile, model=model)
        self.long_memory_agent = LongMemoryAgent(conversation.long_memory, model=model)
        self.summary_agent = SummaryAgent(conversation.summary, model=model)

    def update(self, query: str) -> dict:
        """跑一轮记忆更新。返回本轮发生了什么，便于在日志/测试里核对。

        任何一层失败都不会抛出：记忆更新失败不该影响用户这次对话的答复。
        """
        report = {"profile": {}, "long_memory": None, "summary": None}

        try:
            report["profile"] = self.profile_agent.update(self.user_id, query)
        except Exception as exc:                      # noqa: BLE001
            logger.warning("L4 更新异常：%s", exc)

        try:
            report["long_memory"] = self.long_memory_agent.update(self.user_id, query)
        except Exception as exc:                      # noqa: BLE001
            logger.warning("L3 更新异常：%s", exc)

        try:
            pending = self.window.messages_since_summary()
            if pending >= self.trigger_messages:
                summary = self.summary_agent.update(self.session_id, self.window.load_all())
                if summary:
                    report["summary"] = summary
                    self.window.mark_summarized()
        except Exception as exc:                      # noqa: BLE001
            logger.warning("L2 更新异常：%s", exc)

        return report
