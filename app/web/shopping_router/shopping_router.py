"""商品检索路由：把已装配的来源适配器暴露成 HTTP 接口。

【本次说明】
  1. 结构沿用参考工程 `app/web/<name>_router/`：`__init__.py` 只导出 `shopping_router`。
  2. 来源从 `request.app.state.sources`（dict）取，由 main.py 的 lifespan 按
     `PRICEPILOT_ENABLED_SOURCES` 装配 —— 当前只启用淘宝。
  3. `/products/search` 支持按来源挑选，多来源并行、各自降级；
     结果走 TTL 缓存（`request.app.state.search_cache`），同一关键词短时间内重复检索
     不会重复触发 actor 运行，这是省钱的**主要**手段（按事件计费的来源有固定启动费）。
  4. `/sources` 返回可用来源与计费说明，前端据此渲染来源标签、避免写死。
"""

import asyncio
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.ai.agent.multi_agent.schema.shopping_schema import SearchOutcome
from app.ai.tool.search_cache import SearchCache

shopping_router = APIRouter(tags=['shopping'])

# 各来源「查一次要花多少钱」的说明，直接展示给使用者，避免无意识烧额度。
COST_NOTES = {
    'taobao': '每次运行固定 $0.05 启动费 + $0.00001/条；maxItems 下限 10。少跑几次才省钱 → 同关键词 10 分钟内走缓存。',
    'xianyu': '每次运行 $0.00005 启动费 + $0.002/条挂牌；关键词搜索另需闲鱼登录态。',
    'amazon': 'actor 为包月计费（$40–60/月），不是按条；maxItems 调小不省钱。',
}


class ProductSearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=100)
    sources: list[str] = Field(default_factory=list, description='留空用当前启用的全部来源')
    mode: str = Field(default='', description='留空用来源默认模式')
    limit: int = Field(default=6, ge=1, le=30, description='展示条数；来源侧实际取值可能更大（如淘宝下限 10）')


class ProductSearchResponse(BaseModel):
    keyword: str
    results: list[SearchOutcome] = Field(default_factory=list)
    cache: dict = Field(default_factory=dict, description='本次命中缓存的情况')


def get_sources(request: Request) -> dict:
    sources = getattr(request.app.state, 'sources', None)
    if not sources:
        raise HTTPException(status_code=503, detail='没有装配任何来源，请查看服务端日志')
    return sources


def get_cache(request: Request) -> SearchCache:
    cache = getattr(request.app.state, 'search_cache', None)
    if cache is None:
        cache = SearchCache(ttl_seconds=float(os.environ.get('PRICEPILOT_CACHE_TTL', '600')))
        request.app.state.search_cache = cache
    return cache


@shopping_router.get('/sources')
async def list_sources(request: Request) -> dict:
    """列出当前启用的来源、凭证状态与计费说明（不含密钥）。"""
    sources = getattr(request.app.state, 'sources', {}) or {}
    return {
        'enabled': list(sources),
        'items': [
            {
                'name': name,
                'platform': source.platform,
                'configured': source.configured,
                'cost_note': COST_NOTES.get(name),
            }
            for name, source in sources.items()
        ],
        'cache': get_cache(request).stats(),
    }


async def _one(source, keyword: str, mode: str, limit: int) -> SearchOutcome:
    """单个来源失败不影响其它来源：异常收敛成带状态的 SearchOutcome。"""
    try:
        if mode:
            return await source.search(keyword, mode=mode, limit=limit)
        return await source.search(keyword, limit=limit)
    except TypeError:
        return await source.search(keyword, limit=limit)
    except Exception as exc:
        return SearchOutcome(
            source=getattr(source, 'name', 'unknown'),
            mode=mode or 'default',
            keyword=keyword,
            status='failed',
            message=f'{type(exc).__name__}: {str(exc)[:200]}',
        )


@shopping_router.post('/products/search', response_model=ProductSearchResponse)
async def products_search(body: ProductSearchRequest, request: Request) -> ProductSearchResponse:
    """并行检索来源，返回各自结果与状态；命中缓存的来源不会重新触发采集。"""
    sources = get_sources(request)
    names = body.sources or list(sources)
    unknown = [name for name in names if name not in sources]
    if unknown:
        raise HTTPException(status_code=422, detail=f'未知来源：{unknown}；当前可用 {list(sources)}')

    cache = get_cache(request)
    keyword = body.keyword.strip()

    hits: list[str] = []
    misses: list[str] = []
    tasks = []
    for name in names:
        cached = cache.get(name, keyword, body.mode, body.limit)
        if cached is not None:
            hits.append(name)
            tasks.append(_cached_result(cached, body.limit))
        else:
            misses.append(name)
            tasks.append(_one(sources[name], keyword, body.mode, body.limit))

    results = list(await asyncio.gather(*tasks))

    # 只缓存成功的结果，失败/超时不缓存，避免把故障也缓存 10 分钟。
    for name, outcome in zip(names, results):
        if outcome.status == 'completed':
            cache.put(name, keyword, body.mode, body.limit, outcome)

    return ProductSearchResponse(
        keyword=keyword,
        results=results,
        cache={'hit': hits, 'miss': misses, 'ttl_seconds': cache.ttl_seconds},
    )


async def _cached_result(outcome: SearchOutcome, limit: int) -> SearchOutcome:
    """缓存命中：按请求条数裁剪，并在 message 里说明是缓存。"""
    trimmed = outcome.model_copy(deep=True)
    trimmed.offers = trimmed.offers[:limit]
    origin = trimmed.message or ''
    trimmed.message = (f'（缓存结果，未重复调用采集）{origin}').strip()
    return trimmed


# ---------------- 兼容旧路径（闲鱼来源，默认未启用）----------------
class XianyuSearchRequest(BaseModel):
    keyword: str = Field(default='', max_length=100, description='关键词；feed 模式下会被忽略')
    mode: str = Field(default='feed', description='feed（匿名推荐流）/ search（需闲鱼登录态）')
    limit: int = Field(default=12, ge=1, le=30)


@shopping_router.post('/xianyu/search', response_model=SearchOutcome)
async def xianyu_search(body: XianyuSearchRequest, request: Request) -> SearchOutcome:
    """闲鱼检索（保留旧接口）。闲鱼来源未启用时会明确报 503，而不是假装返回空。"""
    sources = get_sources(request)
    source = sources.get('xianyu')
    if source is None:
        raise HTTPException(
            status_code=503,
            detail='闲鱼来源当前未启用（PRICEPILOT_ENABLED_SOURCES 里没有 xianyu）',
        )
    if body.mode not in ('feed', 'search'):
        raise HTTPException(status_code=422, detail='mode 只能是 feed 或 search')
    return await source.search(keyword=body.keyword.strip() or None, mode=body.mode, limit=body.limit)
