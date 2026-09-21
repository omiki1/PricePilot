import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from langgraph.config import get_stream_writer

from app.ai.agent.multi_agent.node.recommend_node import recommend_node as _recommend_node

chat_router = APIRouter()

# 统一从 app.state 取图的名字。main.py / system_router / products_router 都用这个，
# 之前 chat_router 用 shopping_agent、products_router 用 shopping_graph，必然有一个取到 None。
GRAPH_STATE_ATTR = 'shopping_graph'


def sse(data: dict) -> str:
    """把字典打包成一条 SSE 消息。必须以 \n\n 结尾，否则前端收不到这条消息。"""
    return f'data: {json.dumps(data, ensure_ascii=False)}\n\n'


def _dump_products(raw) -> list:
    """state 里是 Pydantic 的 Product，转成可 JSON 序列化的 dict。"""
    items = []
    for item in raw or []:
        if hasattr(item, 'model_dump'):
            items.append(item.model_dump())
        elif isinstance(item, dict):
            items.append(item)
    return items


def get_graph(request: Request):
    graph = getattr(request.app.state, GRAPH_STATE_ATTR, None)
    if graph is None:
        raise HTTPException(status_code=503, detail='ShoppingGraph 未装配，请查看服务端日志')
    return graph


async def recommend_node(state):
    """包一层：排名+取证跑完就立刻把商品帧写进流，前端不用等模型写完文字。

    这样"商品卡片 3~5 秒可见、文字继续流式补"，总耗时不变但等待感大幅降低。
    recommend_node 本体逻辑不改。
    """
    result = await _recommend_node(state)
    try:
        get_stream_writer()({'type': 'products', 'data': _dump_products(result.get('ranked_top'))})
    except Exception as exc:
        # 拿不到 writer（比如不在流式上下文里）不该影响主流程
        print(f'推送商品帧失败: {exc}')
    return result


@chat_router.get('/chat')
async def chat(request: Request, question: str, user_id: str = 'default', session_id: str = ''):
    """聊天接口：接收用户输入 → 跑图 → SSE 流式输出。

    帧类型：
      {"type": "products", "data": [Product...]}  排名后的商品（recommend 跑完立刻推）
      {"type": "text",     "data": "..."}         模型/节点生成的文字（流式补上）
      {"done": true}                              结束标记

    收藏不在这里：前端点商品卡的收藏按钮后直接调 POST /api/favorites，
    不走 SSE、不重新检索，所以没有收藏帧。
    """
    print(f'用户问题{question},用户ID:{user_id}')
    graph = get_graph(request)
    thread_id = session_id or user_id or 'default'             # 会话隔离靠 thread_id

    async def generate():
        try:
            async for chunk in graph.chat(question, user_id, thread_id):
                # 商品帧和图内文本分开处理：商品帧不拼进正文
                if isinstance(chunk, dict) and chunk.get('type') == 'products':
                    if chunk.get('data'):
                        yield sse({**chunk, 'done': False})
                    continue
                yield sse({'type': 'text', 'data': chunk, 'done': False})

            yield sse({'data': '', 'done': True})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f'流式输出异常: {e}')
            yield sse({'data': f'服务器内部错误: {e}', 'done': True})

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
        },
    )
