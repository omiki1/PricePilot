"""统一读取用户 ID。目前由前端提供，尚未实现 token 鉴权。"""
from fastapi import HTTPException, Query, Request

USER_ID_MAX = 64


async def get_current_user_id(
    request: Request,
    user_id: str | None = Query(default=None, max_length=USER_ID_MAX,
                                description='临时：前端传的用户 ID，接入 token 后废弃'),
) -> str:
    """返回当前用户 ID。读不到身份时 401。"""
    value = (user_id or '').strip()
    if not value and request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        try:
            body = await request.json()      # Starlette 会缓存 body，后面的请求体解析不受影响
        except Exception:                    # noqa: BLE001  没有 body / 不是 JSON
            body = None
        if isinstance(body, dict):
            value = str(body.get('user_id') or '').strip()
    if not value:
        raise HTTPException(status_code=401, detail='缺少用户身份')
    if len(value) > USER_ID_MAX:
        raise HTTPException(status_code=422, detail='user_id 过长')
    return value
