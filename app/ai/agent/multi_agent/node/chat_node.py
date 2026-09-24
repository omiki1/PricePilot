from langchain_core.messages import HumanMessage, SystemMessage

from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.model import MyModel

SYSTEM = ('你是购物助手。用户只是打招呼或闲聊时，用一两句话自然回应，'
          '并顺势引导他说出想买什么。不要推荐任何商品，不要列清单。'
          # ── [B 修改 2026-09-24] 允许回答"聊过什么"这类元问题 ───────────────
          # 原来没有这段，用户问「我问过哪些问题」时上下文里什么都没有，
          # 模型只能老实回一句「我没有之前的对话记录」——即使图里明明已经把
          # 四层记忆和最近对话塞进来了。所以这里明确告诉它可以、也应该照着回答。
          '如果用户问的是「我问过哪些问题」「上次聊了什么」这类关于历史对话的问题，'
          '就根据下面给出的记忆和最近对话如实回答（用列表列出问过的问题即可）；'
          '只有确实查不到相关信息时，才说明没有记录。'
          '不要在有记忆的情况下回答「我没有之前的对话记录」。')

# 最近几轮对话的条数上限（只影响这个节点的 prompt 长度）
HISTORY_MAX_MESSAGES = 8
# 历史里的助手回复可能很长（整段商品分析），截断后再喂，避免把 prompt 撑爆
ASSISTANT_TRUNCATE = 120


def _history_text(state: ShoppingState, limit: int = HISTORY_MAX_MESSAGES) -> str:
    """取本轮之前最近几轮对话（不含本轮输入）。

    ── [B 修改 2026-09-24] ──
    原实现在这里只读 `state['messages'][-1]`，等于把这一轮之前的对话全扔了，
    所以哪怕在**同一个会话**里问「我问过哪些问题」也答不出来。
    messages 是 checkpoint 里累积的，用户问过的每一句都在，直接拿来用即可。
    """
    messages = list(state.get('messages') or [])
    if len(messages) <= 1:
        return ''
    lines = []
    for message in messages[:-1][-limit:]:
        text = (getattr(message, 'content', '') or '').strip()
        if not text:
            continue
        if isinstance(message, HumanMessage):
            lines.append('用户：' + text)
        else:
            clipped = text[:ASSISTANT_TRUNCATE]
            if len(text) > ASSISTANT_TRUNCATE:
                clipped += '…'
            lines.append('助手：' + clipped)
    return '\n'.join(lines)


async def chat_node(state: ShoppingState):
    user_input = state['messages'][-1].content

    # ── [B 修改 2026-09-24] 把四层记忆与最近对话接进闲聊分支 ──────────────
    # memory_block 由 shopping_graph.chat() 在进图前组装好（历史摘要 + 长期记忆 +
    # 用户画像），output_node 一直在用，chat_node 却漏了 —— 于是"闲聊/元问题"
    # 这条路上记忆形同不存在。
    blocks = [SYSTEM]

    memory_block = (state.get('memory_block') or '').strip()
    if memory_block:
        blocks.append('【跨会话记忆】\n' + memory_block)

    history = _history_text(state)
    if history:
        blocks.append('【本次会话的最近对话】\n' + history)

    reply = await MyModel.get_model().ainvoke([
        SystemMessage(content='\n\n'.join(blocks)),
        HumanMessage(content=user_input),
    ])
    return {'answer': {'text': reply.content, 'products': []}}
