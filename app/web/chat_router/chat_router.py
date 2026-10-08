"""聊天接口：把图里吐出的东西拆成 SSE 帧，结束时把这一轮存进历史。"""
import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.ai.tool.session_repository import append_turn, ensure_session
from app.web.deps import get_current_user_id

chat_router = APIRouter()


def sse(data: dict) -> str:
    """把字典打包成一条 SSE 消息。必须以 \\n\\n 结尾，否则前端收不到这条消息。"""
    return f'data: {json.dumps(data, ensure_ascii=False)}\n\n'


@chat_router.get('/chat')
async def chat(request: Request, question: str, session_id: str = '',
               user_id: str = Depends(get_current_user_id)):
    """SSE 流式回答：文字帧 + 商品帧 + 结束帧；带了 session_id 就把这一轮存进历史。"""
    shopping_agent = request.app.state.shopping_agent          # lifespan 里创建好的图
    thread_id = session_id or user_id or 'default'             # 会话隔离靠 thread_id

    async def generate():
        text_parts, last_products = [], None
        async for x in shopping_agent.chat(question, user_id, thread_id):
            # 商品帧和图内文本分开处理：商品帧不拼进正文
            if isinstance(x, dict) and x.get('type') == 'products':
                if x.get('data'):
                    last_products = x['data']                  # 历史里只存本轮最后一次商品帧
                    yield sse({'type': 'products', 'data': x['data'], 'done': False})
                continue
            if isinstance(x, str):
                text_parts.append(x)
            yield sse({'type': 'text', 'data': x, 'done': False})

        if session_id:
            await asyncio.to_thread(ensure_session, session_id, user_id)
            await asyncio.to_thread(append_turn, session_id, question,
                                    ''.join(text_parts), last_products)
        yield sse({'data': '', 'done': True})

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
        },
    )
