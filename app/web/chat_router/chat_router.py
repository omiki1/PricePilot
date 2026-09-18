

import asyncio
import json

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

chat_router = APIRouter()


def sse(data: dict) -> str:
    """把字典打包成一条 SSE 消息。必须以 \\n\\n 结尾，否则前端收不到这条消息。"""
    return f'data: {json.dumps(data, ensure_ascii=False)}\n\n'


@chat_router.get('/chat')
async def chat(request: Request, question: str, user_id: str):
    """聊天接口：接通多智能体出题流程，流式返回（SSE）。

    关于 session_id：ExamGraph 用 checkpointer 保存多轮状态，靠 thread_id 区分会话。
    前端目前只传了 question 和 user_id，所以这里先用 user_id 当 thread_id
    —— 即"同一个用户的多轮对话共享记忆"，正好满足"出题 → 答题 → 再出题"的循环。
    将来前端支持多会话时，把 session_id 加成参数、这里优先用它即可。
    """
    print(f'用户问题{question},用户ID:{user_id}')
    exam_agent = request.app.state.exam_agent          # lifespan 里创建好的图
    session_id = user_id or "default"                  # 同一用户共享记忆

    async def generate(question, user_id, session_id):
        try:
            async for x in exam_agent.chat(question, user_id, session_id):
                yield sse({'data': x, 'done': False})
            yield sse({'data': '', 'done': True})
        except asyncio.CancelledError:
            # 客户端断开（关页面/点停止），交给 Starlette 正常收尾
            raise
        except Exception as e:
            print(f'流式输出异常: {e}')
            yield sse({'data': f'服务器内部错误: {e}', 'done': True})

    return StreamingResponse(
        generate(question, user_id, session_id),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
        },
    )


# ---------------- 语音输入 ----------------
@chat_router.websocket('/vosk')
async def vosk(ws: WebSocket):
    await ws.accept()
    print("语音连接已建立")
    try:
        agent = get_vosk_agent()          # 懒加载（第一次会等模型加载）
        await agent.speak(ws)             # 录音 + 识别 + 推送（识别到一句话即返回）
        while True:
            # 保持连接：识别完不等断开，等前端下次点语音时复用
            await ws.receive_text()
    except WebSocketDisconnect:
        print("语音连接已断开")            # 正常断开，安静收尾
    except Exception as e:
        print(f"语音接口异常: {e}")
