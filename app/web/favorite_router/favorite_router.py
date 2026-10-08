import asyncio

from fastapi import APIRouter, HTTPException, Query

from app.ai.agent.multi_agent.schema.favorite_schema import (
    FavoriteAddRequest,
    FavoriteItem,
    FavoriteListResponse,
    FavoriteMutationResponse,
    FavoriteRemoveRequest,
    PriceHistoryResponse,
    PriceRecordResponse,
    PriceRefreshRequest,
)
from app.ai.tool.favorite_repository import (
    FavoriteError,
    add_favorite,
    count_favorites,
    list_favorites,
    remove_favorite,
)
from app.ai.tool.price_history_repository import (
    PriceHistoryError,
    price_history,
    record_price,
)
from app.ai.tool.price_refresh import PriceRefreshError, current_price

favorite_router = APIRouter(tags=['favorites'])


def _fail(exc) -> HTTPException:
    message = str(exc)
    status = 400 if message.startswith('商品') or '不是合法数字' in message else 503
    return HTTPException(status_code=status, detail=message)


@favorite_router.post('/favorites', response_model=FavoriteMutationResponse)
async def create_favorite(body: FavoriteAddRequest) -> FavoriteMutationResponse:
    """收藏一个商品。"""
    try:
        item = add_favorite(body.user_id, body.product)
        total = count_favorites(body.user_id)
    except FavoriteError as exc:
        raise _fail(exc) from exc
    message = '已收藏「%s」' % item.get('title')
    try:
        history = record_price(item.get('product_id'), item.get('price'))
        message += '，已记下当前价格' if history['recorded'] else '（价格与上次相同，未重复记录）'
    except PriceHistoryError as exc:
        print('记录价格失败：%s' % exc)
        message += '（价格没能记上）'

    return FavoriteMutationResponse(ok=True, message=message, user_id=item['user_id'],
                                    total=total, item=FavoriteItem(**item))


@favorite_router.get('/favorites', response_model=FavoriteListResponse)
async def read_favorites(
    user_id: str = Query(default='default', max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
) -> FavoriteListResponse:
    """列出某个用户自己的收藏"""
    try:
        items = list_favorites(user_id, limit=limit)
        total = count_favorites(user_id)
    except FavoriteError as exc:
        raise _fail(exc) from exc

    return FavoriteListResponse(user_id=user_id or 'default', total=total,
                                favorites=[FavoriteItem(**item) for item in items])


@favorite_router.get('/products/price-history', response_model=PriceHistoryResponse)
async def read_price_history(
    product_id: str = Query(..., max_length=191),
    limit: int = Query(default=60, ge=1, le=500),
) -> PriceHistoryResponse:
    """某个商品的价格记录，按时间正序，前端直接从上往下列。"""
    try:
        points = price_history(product_id, limit=limit)
    except PriceHistoryError as exc:
        raise _fail(exc) from exc

    return {'product_id': product_id, 'points': points}


@favorite_router.post('/products/price-history/refresh', response_model=PriceRecordResponse)
async def refresh_product_price(body: PriceRefreshRequest) -> PriceRecordResponse:
    """刷新价格：重新去查这个商品的当前价，再决定要不要记一笔。

    流程：收藏里取标题 → 上游回查（只认 product_id 完全相同）→ 仓储层判重写入。
    回查不到（下架、改名、上游查不到）时，若前端给了 fallback_price 就按它记一笔，
    并如实说明来源；没给就不写 —— 不编价。
    """
    try:
        items = list_favorites(body.user_id, limit=500)
    except FavoriteError as exc:
        raise _fail(exc) from exc

    row = next((x for x in items if str(x.get('product_id')) == body.product_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail='这个商品不在当前用户的收藏夹里，无法回查价格')

    # 上游检索是同步阻塞调用（requests），丢线程池，别卡住事件循环
    try:
        price, how = await asyncio.to_thread(
            current_price, product_id=body.product_id, title=row.get('title') or '',
        )
    except PriceRefreshError as exc:
        raise HTTPException(status_code=503, detail=f'回查价格失败：{exc}') from exc

    source = 'shopify'
    if price is None:
        if body.fallback_price is None:
            messages = {
                'not_found': '没查到这件商品（可能已下架或改名），未记录',
                'no_price': '这件商品现在没有标价，未记录',
                'no_title': '收藏里没有商品名，无法回查',
                'no_product_id': '缺少商品 ID，无法回查',
            }
            try:
                points = price_history(body.product_id, limit=60)
            except PriceHistoryError as exc:
                raise _fail(exc) from exc
            return PriceRecordResponse(product_id=body.product_id, recorded=False,
                                       reason=how, message=messages.get(how, '没取到价格，未记录'),
                                       price=None, source='', points=points)
        # 回查不到但有兜底价：记它，但把来源说清楚
        price, source, how = float(body.fallback_price), 'fallback', 'price_fallback'

    try:
        result = record_price(body.product_id, price)
        points = price_history(body.product_id, limit=60)
    except PriceHistoryError as exc:
        raise _fail(exc) from exc

    recorded = bool(result.get('recorded'))
    reason = str(result.get('reason') or '')
    label = '最新价' if source == 'shopify' else '卡片上的价格'
    if recorded:
        message = f'已按{label} {price:g} 存入一条记录'
    elif reason == 'no_price':
        message = '没拿到价格，未记录'
    else:
        message = f'{label} {price:g} 与上一条相同，未重复记录'
    if source == 'fallback':
        message = '没查到最新价（可能已下架或改名），' + message

    return PriceRecordResponse(product_id=body.product_id, recorded=recorded, reason=reason,
                               message=message, price=price, source=source, points=points)


@favorite_router.delete('/favorites', response_model=FavoriteMutationResponse)
async def delete_favorite(body: FavoriteRemoveRequest) -> FavoriteMutationResponse:
    """取消收藏"""
    try:
        deleted = remove_favorite(body.user_id, body.product_id)
        total = count_favorites(body.user_id)
    except FavoriteError as exc:
        raise _fail(exc) from exc

    message = '已取消收藏' if deleted else '这件商品本来就不在收藏夹里'
    return FavoriteMutationResponse(ok=bool(deleted), message=message,
                                    user_id=body.user_id, total=total)
