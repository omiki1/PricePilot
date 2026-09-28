"""四层记忆（app/ai/agent/memory）。

    L1 窗口   Redis List    最近若干条原文
    L2 摘要   PostgreSQL    一次会话一份，UPSERT 覆盖
    L3 长期   向量库        跨会话偏好，语义检索
    L4 画像   Redis Hash    结构化属性

对外只暴露两个东西：
    build_memory_block(user_id, session_id, question)  取记忆 -> 拼成一段文本
    update_memory(user_id, session_id, question)       跑完一轮后更新 L2/L3/L4

调用方是 shopping_graph：进图前取、跑完写。
记忆是增强项不是依赖项 —— 这里任何一层挂了都只返回空串，主链路照常。
"""

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
    """跑完一轮后更新记忆。

    messages 是窗口记忆里的原始消息（每项 {'role','content'}），先按顺序写进 L1，
    再让 MemoryManager 基于窗口内容更新 L2/L3/L4。
    """
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
