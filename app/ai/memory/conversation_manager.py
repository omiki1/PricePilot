"""会话管理器 —— 记忆系统的全局入口（主笔：B）

一次对话的完整生命周期（课程文档口径）：

    用户发送消息
      1. save_user()   写入 L1 窗口
      2. build_prompt() 组装四层记忆 → 交给模型
      3. 模型推理
      4. save_ai()     回复写入 L1
      5. update()      触发 L2/L3/L4 提取更新

与 Checkpointer 的分工（课程文档特别强调，别混在一起）：
    Checkpointer 保存「图的运行状态」，进程内、随运行结束而失效；
    四层记忆保存「需要跨会话记住的用户信息」，落在 Redis / PG / 向量库。

本类不强依赖任何框架，可以直接在节点里用，也可以单独跑（见 tools/memory_demo.py）。
"""
from __future__ import annotations

import logging

from app.ai.memory.prompt_builder import PromptBuilder
from app.ai.memory.retrieval.memory_manager import MemoryManager
from app.ai.memory.store import LongMemory, ProfileMemory, SummaryMemory, WindowMemory

logger = logging.getLogger(__name__)


class ConversationManager:
    def __init__(self, user_id, session_id, *, window=None, summary=None,
                 long_memory=None, profile=None, model=None, enable_update: bool = True):
        self.user_id = str(user_id)
        self.session_id = str(session_id)

        # 四层存储：允许外部注入（测试用内存实现/假嵌入），默认按配置自建
        self.window = window or WindowMemory(self.session_id)
        self.summary = summary or SummaryMemory()
        self.long_memory = long_memory or LongMemory()
        self.profile = profile or ProfileMemory(self.user_id)

        self.enable_update = enable_update
        self._memory_manager = (MemoryManager(self, model=model)
                                if enable_update else None)

    # ── 1 / 4：窗口写入 ──
    def save_user(self, question: str) -> None:
        self.window.add("user", question)

    def save_ai(self, response: str) -> None:
        self.window.add("assistant", response)

    # ── 2：组装 Prompt ──
    def _builder(self) -> PromptBuilder:
        return PromptBuilder(self.window, self.summary, self.long_memory,
                             self.profile, self.user_id, self.session_id)

    def build_prompt(self, question: str | None = None) -> str:
        return self._builder().build(question)

    def build_messages(self, question: str | None = None) -> list[dict]:
        return self._builder().build_messages(question)

    def build_memory_block(self, question: str | None = None) -> str:
        """只要记忆段落 —— 挂到已有节点上时用这个，不动别人的 prompt 结构。"""
        return self._builder().build_memory_block(question)

    # ── 5：记忆更新 ──
    def update(self, question: str) -> dict:
        """每轮对话结束后调用：更新 L4 / L3，条件触发 L2。"""
        if self._memory_manager is None:
            return {"profile": {}, "long_memory": None, "summary": None,
                    "skipped": "enable_update=False"}
        return self._memory_manager.update(question)

    # ── 便捷组合 ──
    def turn(self, question: str, answer: str) -> dict:
        """一轮完整收尾：写入窗口 → 触发记忆更新。返回本轮更新报告。"""
        self.save_user(question)
        self.save_ai(answer)
        return self.update(question)

    def history(self, limit: int | None = None) -> list[dict]:
        return self.window.load(limit)

    def memory_snapshot(self) -> dict:
        """把四层记忆的当前状态抓一份出来，便于调试与演示。"""
        snapshot = {"l1_window": self.history(), "l2_summary": "", "l3_long": [], "l4_profile": {}}
        try:
            snapshot["l2_summary"] = self.summary.load(self.session_id)
        except Exception as exc:                      # noqa: BLE001
            snapshot["l2_summary"] = f"<不可用: {exc}>"
        try:
            snapshot["l3_long"] = self.long_memory.load(self.user_id)
        except Exception as exc:                      # noqa: BLE001
            snapshot["l3_long"] = [f"<不可用: {exc}>"]
        try:
            snapshot["l4_profile"] = self.profile.load(self.user_id)
        except Exception as exc:                      # noqa: BLE001
            snapshot["l4_profile"] = {"_error": str(exc)}
        return snapshot

    def clear_session(self) -> None:
        """只清本会话的短期记忆（L1）与其摘要（L2）；用户级记忆保留。"""
        self.window.clear()
        try:
            self.summary.delete(self.session_id)
        except Exception as exc:                      # noqa: BLE001
            logger.warning("清理 L2 失败：%s", exc)

    def clear_user(self) -> None:
        """清该用户的长期记忆（L3）与画像（L4）。演示/测试用，慎在生产调用。"""
        self.long_memory.clear(self.user_id)
        self.profile.clear(self.user_id)
