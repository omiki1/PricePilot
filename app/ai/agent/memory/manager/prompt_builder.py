from app.ai.agent.memory.save.window_memory import WindowMemory
from app.ai.agent.memory.save.summary_memory import SummaryMemory
from app.ai.agent.memory.save.long_memory import LongMemory
from app.ai.agent.memory.save.profile_memory import ProfileMemory


class PromptBuilder:
    """按固定顺序把四层记忆拼成一段文本，喂给下游节点当上下文。"""

    def __init__(self, session_id, user_id):
        self.window_memory = WindowMemory(session_id)
        self.summary_memory = SummaryMemory(session_id)
        self.long_memory = LongMemory()
        self.profile_memory = ProfileMemory(user_id)

    async def builder_prompt(self, user_id, question):
        sections = []

        # L1 窗口：最近几轮原文
        try:
            window = await self.window_memory.query() or []
        except Exception as exc:                  # noqa: BLE001
            print(f"[memory] 读窗口记忆失败：{exc}")
            window = []
        if window:
            lines = [f"{'用户' if i.get('role') == 'user' else '助手'}：{i.get('content', '')}"
                     for i in window]
            sections.append("【最近对话】\n" + '\n'.join(lines))

        # L2 摘要：更早的会话内容压缩成的要点
        try:
            summary = await self.summary_memory.query()
        except Exception as exc:                  # noqa: BLE001
            print(f"[memory] 读摘要记忆失败：{exc}")
            summary = ""
        if summary:
            sections.append("【会话摘要】\n" + summary)

        # L3 长期：跨会话的稳定偏好，按语义检索 Top-N
        try:
            long_items = await self.long_memory.query(user_id, question) or []
        except Exception as exc:                  # noqa: BLE001
            print(f"[memory] 读长期记忆失败：{exc}")
            long_items = []
        if long_items:
            sections.append("【长期偏好】\n" + '\n'.join(
                item if item.strip().startswith("-") else f"- {item}" for item in long_items))

        # L4 画像：结构化属性
        try:
            profile = await self.profile_memory.query()
        except Exception as exc:                  # noqa: BLE001
            print(f"[memory] 读用户画像失败：{exc}")
            profile = ""
        if profile:
            sections.append("【用户画像】\n" + profile.strip())

        if not sections:
            return ""

        header = (
            "以下是这位用户的历史记忆，供参考。\n"
            "与本次需求冲突时，一律以本次需求为准。\n"
        )
        return header + '\n'.join(sections)


