"""四层记忆（app/ai/agent/memory）。"""

from app.ai.agent.memory.manager.session_manager import SessionManager
from app.ai.agent.memory.manager.memory_manager import MemoryManager

__all__ = ["SessionManager", "MemoryManager", "build_memory_block", "update_memory"]


def _make(user_id: str, session_id: str):
    """建会话管理器。建不起来返回 None（本轮无记忆）。"""
    try:
        return SessionManager(session_id=str(session_id), user_id=str(user_id))
    except Exception as exc:                       # noqa: BLE001
        print(f"[memory] 初始化失败，本轮无记忆：{exc}")
        return None


async def build_memory_block(user_id: str, session_id: str, question: str) -> str:
    """组装四层记忆段落。任何异常都退化成空串。"""
    sm = _make(user_id, session_id)
    if sm is None:
        return ""
    try:
        prompt = await sm.prompt_builder.builder_prompt(user_id, question)
        return prompt or ""
    except Exception as exc:                       # noqa: BLE001
        print(f"[memory] 组装记忆失败，本轮无记忆：{exc}")
        return ""


async def update_memory(user_id: str, session_id: str, question: str, messages: list) -> dict:
    """跑完一轮后更新记忆。"""
    sm = _make(user_id, session_id)
    if sm is None:
        return {}
    try:
        for item in messages or []:
            await sm.save(item.get("role", "user"), item.get("content", ""))
        return await MemoryManager(sm).update(user_id, question)
    except Exception as exc:                       # noqa: BLE001
        print(f"[memory] 更新记忆失败：{exc}")
        return {}
