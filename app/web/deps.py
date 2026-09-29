"""路由公共依赖：当前用户身份（omiki 2026-09-29）

所有新接口（会话管理、首页推荐、聊天落库）都通过 Depends(get_current_user_id) 拿「当前是谁」，
路由里不再自己读 user_id 参数。

⚠️ 现状是临时方案：登录接口还不发 token，这里只是从请求里读前端传的 user_id
（先看 query 参数，再看 JSON body），**任何人都可以伪造**。
接入 token 鉴权时只改这一个函数：从 Authorization 头解析 token → 校验 → 返回其中的 user_id，
调用方（路由、归属校验、落库）一行都不用动。测试里也可以用
app.dependency_overrides[get_current_user_id] 直接换身份。
"""
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
