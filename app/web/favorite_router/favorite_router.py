from fastapi import APIRouter, HTTPException, Query

from app.ai.agent.multi_agent.schema.favorite_schema import (
    FavoriteAddRequest,
    FavoriteItem,
    FavoriteListResponse,
    FavoriteMutationResponse,
    FavoriteRemoveRequest,
    PriceHistoryResponse,
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
    """列出某个用户自己的收藏
    """
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
    """某个商品的价格记录，按时间正序，前端直接从上往下列。

    只给数据不做判断：不在这里算涨跌、不判历史最低价 ——
    样本太少时那种结论本身就是误导。
    """
    try:
        points = price_history(product_id, limit=limit)
    except PriceHistoryError as exc:
        raise _fail(exc) from exc

    return {'product_id': product_id, 'points': points}


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
