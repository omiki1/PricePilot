import asyncio
import json
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.ai.tool.session_repository import SessionError, append_turn, ensure_session
from app.web.deps import get_current_user_id

chat_router = APIRouter()

# 会话归属不对 / 已删除时的结束帧文案（前端按 code 换成 ui_copy.js 里的文案，这里给老前端兜底）
SESSION_FORBIDDEN_TEXT = '这段对话不属于当前账号。'
SESSION_DELETED_TEXT = '这段对话打不开了，可能已被删除。'


def sse(data: dict) -> str:
    """把字典打包成一条 SSE 消息。必须以 \\n\\n 结尾，否则前端收不到这条消息。"""
    return f'data: {json.dumps(data, ensure_ascii=False)}\n\n'


async def _check_session(session_id: str, user_id: str) -> str:
    """检查归属；数据库不可用时返回 unavailable，本轮不保存历史。"""
    try:
        return await asyncio.to_thread(ensure_session, session_id, user_id)
    except SessionError as exc:
        print(f'[session] 会话校验失败，本轮照常回答但不落库：{exc}')
        return 'unavailable'


async def _persist_turn(session_id: str, question: str, answer: str, products) -> bool:
    """一轮问答落库。任何失败只打日志、返回 False，绝不让异常冒到 SSE 流里。"""
    try:
        await asyncio.to_thread(append_turn, session_id, question, answer, products)
        return True
    except Exception as exc:                    # noqa: BLE001
        print(f'[session] 聊天记录保存失败（session={session_id}）：{exc}')
        return False


@chat_router.get('/chat')
async def chat(request: Request, question: str, session_id: str = '',
               user_id: str = Depends(get_current_user_id)):
    """通过 SSE 发送文字、商品和结束状态，并保存本轮记录。"""
    print(f'用户问题{question},用户ID:{user_id}')
    shopping_agent = request.app.state.shopping_agent          # lifespan 里创建好的图
    thread_id = session_id or user_id or "default"             # 会话隔离靠 thread_id

    async def generate():
        # 没传 session_id 的老调用方：照旧聊天，不落库
        persist = False
        if session_id:
            status = await _check_session(session_id, user_id)
            if status == 'forbidden':
                yield sse({'data': SESSION_FORBIDDEN_TEXT, 'done': True, 'code': 'session_forbidden'})
                return
            if status == 'deleted':
                yield sse({'data': SESSION_DELETED_TEXT, 'done': True, 'code': 'session_deleted'})
                return
            persist = status == 'ok'

        text_parts = []
        last_products = None
        try:
            async for x in shopping_agent.chat(question, user_id, thread_id):
                # 商品帧和图内文本分开处理：商品帧不拼进正文
                if isinstance(x, dict) and x.get('type') == 'products':
                    if x.get('data'):
                        last_products = x['data']          # 历史里只存本轮最后一次商品帧
                        yield sse({'type': 'products', 'data': x['data'], 'done': False})
                    continue
                if isinstance(x, str):
                    text_parts.append(x)
                yield sse({'type': 'text', 'data': x, 'done': False})

            done = {'data': '', 'done': True}
            if persist and not await _persist_turn(session_id, question, ''.join(text_parts), last_products):
                done['saved'] = False
            elif session_id and not persist:
                done['saved'] = False                  # 校验阶段库就不可用
            yield sse(done)
        except Exception as e:
            print(f'流式输出异常: {e}')
            # 已经给用户看过一部分内容的话，把问题和这部分内容存下来，免得刷新后问题也消失
            if persist and (text_parts or last_products):
                await _persist_turn(session_id, question, ''.join(text_parts), last_products)
            yield sse({'data': f'服务器内部错误: {e}', 'done': True})

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
        },
    )
