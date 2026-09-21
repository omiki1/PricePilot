import asyncio
import json
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
chat_router = APIRouter()
def sse(data: dict) -> str:
    """把字典打包成一条 SSE 消息。必须以 \\n\\n 结尾，否则前端收不到这条消息。"""
    return f'data: {json.dumps(data, ensure_ascii=False)}\n\n'
@chat_router.get('/chat')
async def chat(request: Request, question: str, user_id: str, session_id: str = ''):
    """聊天接口：接收用户输入 → 跑图 → SSE 流式输出。

    帧类型：
      {"type": "products", "data": [Product...]} 排名后的商品（recommend 跑完立刻推，约 3~5s）
      {"type": "text",     "data": "..."}        模型生成的文字（随后流式补上）
      {"done": true}                             结束标记
    """
    print(f'用户问题{question},用户ID:{user_id}')
    shopping_agent = request.app.state.shopping_agent          # lifespan 里创建好的图
    thread_id = session_id or user_id or "default"             # 会话隔离靠 thread_id
    async def generate():
        try:
            async for x in shopping_agent.chat(question, user_id, thread_id):
                # 商品帧和图内文本分开处理：商品帧不拼进正文
                if isinstance(x, dict) and x.get('type') == 'products':
                    if x.get('data'):
                        yield sse({'type': 'products', 'data': x['data'], 'done': False})
                    continue
                yield sse({'type': 'text', 'data': x, 'done': False})

            yield sse({'data': '', 'done': True})
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
