from fastapi import APIRouter, Request

system_router = APIRouter(tags=['ops'])


@system_router.get('/health')
async def health(request: Request) -> dict:
    """健康检查：只报告装配情况，不暴露密钥与路径。

    属性名 shopping_agent 要和 main.py 的 lifespan、chat_router 保持一致 ——
    三处用同一个名字，换名字会让这里静默报 degraded（取不到图但不报错）。
    """
    graph = getattr(request.app.state, 'shopping_agent', None)
    return {
        'status': 'ok' if graph is not None else 'degraded',
        'components': {'graph': graph is not None},
    }
