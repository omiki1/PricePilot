from langchain_core.messages import HumanMessage, SystemMessage

from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.model import MyModel

SYSTEM = ('你是购物助手。用户只是打招呼或闲聊时，用一两句话自然回应，'
          '并顺势引导他说出想买什么。不要推荐任何商品，不要列清单。'


          '如果用户问的是「我问过哪些问题」「上次聊了什么」这类关于历史对话的问题，'
          '就根据下面给出的记忆和最近对话如实回答（用列表列出问过的问题即可）；'
          '只有确实查不到相关信息时，才说明没有记录。'
          '不要在有记忆的情况下回答「我没有之前的对话记录」。')

# 最近几轮对话的条数上限（只影响这个节点的 prompt 长度）
HISTORY_MAX_MESSAGES = 8
# 历史里的助手回复可能很长（整段商品分析），截断后再喂，避免把 prompt 撑爆
ASSISTANT_TRUNCATE = 120


def _history_text(state: ShoppingState, limit: int = HISTORY_MAX_MESSAGES) -> str:
    """取本轮之前最近几轮对话（不含本轮输入）。"""
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


    # memory_block 由 shopping_graph.chat() 在进图前组装好（历史摘要 + 长期记忆 +。
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
