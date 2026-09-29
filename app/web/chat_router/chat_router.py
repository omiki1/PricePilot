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
    """进图前的会话归属校验（omiki 2026-09-29）。

    返回 'ok'（已存在且属于本人，或刚懒创建）/ 'forbidden' / 'deleted' / 'unavailable'（库挂了）。
    必须在跑图之前做：thread_id = session_id，放行别人的会话 ID 就等于让他读到
    别人的 LangGraph 检查点和 Redis 窗口记忆。
    库不可用时只降级为「这轮不落库」，不拦聊天 —— 历史记录是锦上添花，不能拖垮主链路。
    """
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
    """聊天接口：接收用户输入 → 跑图 → SSE 流式输出。
    帧类型：
      {"type": "products", "data": [Product...]} 排名后的商品（recommend 跑完立刻推，约 3~5s）
      {"type": "text",     "data": "..."}        模型生成的文字（随后流式补上）
      {"done": true}                             结束标记
    结束帧的可选字段（新增，老前端忽略即可）：
      "saved": false                              这一轮已回答但没存进历史
      "code": "session_forbidden" / "session_deleted"   会话校验没过，这一轮不跑图；data 里是提示文案
    user_id 仍是 query 参数（前端不用改），但统一经 get_current_user_id 解析，接 token 时只改 deps.py。
    """
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
