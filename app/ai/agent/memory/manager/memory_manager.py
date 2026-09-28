from app.ai.agent.memory.retrieval.SummaryAgent import SummaryAgent
from app.ai.agent.memory.manager.session_manager import SessionManager
from app.ai.agent.memory.retrieval.long_agent import LongAgent
from app.ai.agent.memory.retrieval.profile_agent import ProfileAgent


class MemoryManager:
    """一轮对话结束后，把窗口里的内容提炼进 L2 / L3 / L4。

    每个智能体各自 try/except：某一层挂了不该拖累另外两层。
    """

    def __init__(self, session_manager: SessionManager):
        self.summary_agent = SummaryAgent(session_manager.summary_memory)
        self.window_memory = session_manager.window_memory
        self.long_agent = LongAgent(session_manager.long_memory)
        self.profile_agent = ProfileAgent(session_manager.profile_memory)

    async def update(self, user_id, question):
        window = await self.window_memory.query() or []

        # 拼成给模型看的对话文本：user / ai 都要带上，每条一行。
        # 只收用户提问的话，「助手推荐了什么、用户满不满意」就丢了。
        lines = []
        for item in window:
            who = "用户" if item.get("role") == "user" else "助手"
            lines.append(f"{who}：{item.get('content', '')}")
        dialogue = chr(10).join(lines)
        if not dialogue:
            dialogue = question or ""

        report = {}

        try:
            await self.long_agent.update(user_id, dialogue)
            report["long"] = "ok"
        except Exception as exc:                  # noqa: BLE001
            report["long"] = f"失败：{exc}"

        try:
            await self.profile_agent.update(dialogue)
            report["profile"] = "ok"
        except Exception as exc:                  # noqa: BLE001
            report["profile"] = f"失败：{exc}"

        # 摘要：至少攒够 2 条消息才做，否则第一轮就把半句话压成摘要没意义
        if len(window) >= 2:
            try:
                await self.summary_agent.update(window)
                report["summary"] = "ok"
            except Exception as exc:              # noqa: BLE001
                report["summary"] = f"失败：{exc}"
        else:
            report["summary"] = f"跳过（窗口仅 {len(window)} 条）"

        report["window"] = len(window)
        return report
