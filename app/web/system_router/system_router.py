from fastapi import APIRouter, Request

system_router = APIRouter(tags=['ops'])


@system_router.get('/health')
async def health(request: Request) -> dict:
    """健康检查：只报告装配情况，不暴露密钥与路径。

    只报图装没装上。收藏表在不在不在这里探测 ——
    缺表时收藏接口自己会返回 503 并带上原因，没必要在启动和健康检查里多查一次。
    """
    graph = getattr(request.app.state, 'shopping_graph', None)
    return {
        'status': 'ok' if graph is not None else 'degraded',
        'components': {'graph': graph is not None},
    }
