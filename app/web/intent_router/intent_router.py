"""意图识别路由。

【本次改造说明】
  1. 接口从 main.py 里的内联装饰器搬到这里，与参考工程的
     `app/web/<name>_router/` 结构保持一致：`__init__.py` 只负责导出 `intent_router`。
  2. ShoppingGraph 从 `request.app.state.shopping_graph` 获取（在 main.py 的 lifespan 里创建），
     不由本模块自己 new —— 图和它的检查点(inmemory memory)由应用统一管理、统一释放。
  3. 当前只接通已完成的意图识别业务（START → intent → END），
     搜索/标准化/比价等节点实现后再往这个 router 里加接口。
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

intent_router = APIRouter(tags=['intent'])


class IntentRequest(BaseModel):
    """意图识别请求体，只包含当前业务需要的字段。"""

    question: str = Field(..., min_length=1, max_length=2000, description='用户想买什么')
    user_id: str = Field(default='default', max_length=64)
    session_id: str = Field(default='', max_length=64, description='留空时用 user_id 作为会话')


class IntentResponse(BaseModel):
    user_id: str
    session_id: str
    text: str


def get_graph(request: Request):
    """取出应用启动时装配好的图；没装配好就明确报 503，不假装成功。"""
    graph = getattr(request.app.state, 'shopping_graph', None)
    if graph is None:
        raise HTTPException(status_code=503, detail='ShoppingGraph 未装配，请查看服务端日志')
    return graph


@intent_router.post('/intent', response_model=IntentResponse)
async def intent(body: IntentRequest, request: Request) -> IntentResponse:
    """把用户输入交给 ShoppingGraph 的意图识别流程，一次性返回识别结果文本。"""
    graph = get_graph(request)
    session_id = body.session_id or body.user_id or 'default'

    chunks: list[str] = []
    try:
        async for chunk in graph.chat(body.question, body.user_id, session_id):
            if isinstance(chunk, str) and chunk:
                chunks.append(chunk)
    except Exception as exc:  # 模型/网络异常统一转成 500，细节留给日志
        raise HTTPException(status_code=500, detail=f'意图识别失败：{exc}') from exc

    text = ''.join(chunks).strip()
    if not text:
        raise HTTPException(status_code=502, detail='模型没有返回任何内容')
    return IntentResponse(user_id=body.user_id, session_id=session_id, text=text)


@intent_router.post('/intent/stream')
async def intent_stream(body: IntentRequest, request: Request) -> StreamingResponse:
    """流式版本：逐段推送识别结果，前端用 fetch 流读取（text/plain）。"""
    graph = get_graph(request)
    session_id = body.session_id or body.user_id or 'default'

    async def generate():
        async for chunk in graph.chat(body.question, body.user_id, session_id):
            if isinstance(chunk, str) and chunk:
                yield chunk

    return StreamingResponse(generate(), media_type='text/plain; charset=utf-8')
