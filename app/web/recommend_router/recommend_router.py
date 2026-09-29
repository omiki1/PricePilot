"""首页推荐接口"""
from fastapi import APIRouter, Depends, Query

from app.ai.tool.recommend_service import get_recommendations
from app.web.deps import get_current_user_id

recommend_router = APIRouter(tags=['recommendations'])


@recommend_router.get('/recommendations')
def read_recommendations(
    user_id: str = Depends(get_current_user_id),     # 当前用户统一走依赖，接 token 时只改 deps.py
    refresh: int = Query(default=0, ge=0, le=1),
) -> dict:
    try:
        payload = get_recommendations(user_id, refresh=bool(refresh))
    except Exception as exc:                    # noqa: BLE001  兜底：服务层漏掉的异常也不 500
        print(f'[recommend] 未预期的异常：{exc}')
        payload = {'user_id': user_id, 'mode': 'samples', 'products': [], 'error': True,
                   'cached': False, 'round': 0, 'exhausted': False}
    # 指纹只给缓存判断用，不下发
    payload = {k: v for k, v in payload.items() if k not in ('fingerprint', 'favorites_fingerprint')}
    return payload
