"""系统路由：健康检查等运维接口。"""

from fastapi import APIRouter, Request

system_router = APIRouter(tags=['ops'])


@system_router.get('/health')
async def health(request: Request) -> dict:
    """健康检查：只报告装配情况，不暴露密钥与路径。"""
    graph = getattr(request.app.state, 'shopping_graph', None)
    sources = getattr(request.app.state, 'sources', {}) or {}
    cache = getattr(request.app.state, 'search_cache', None)
    return {
        'status': 'ok' if graph is not None else 'degraded',
        'components': {
            'graph': graph is not None,
            # 每个来源单独报告是否装配成功、凭证是否齐全
            'sources': {name: bool(source.configured) for name, source in sources.items()},
        },
        'cache': cache.stats() if cache is not None else None,
    }
