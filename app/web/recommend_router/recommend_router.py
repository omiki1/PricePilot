"""首页推荐接口（omiki 2026-09-29）

main.py 以 prefix='/api' 注册：GET /api/recommendations?user_id=&refresh=0|1

返回：
    {
      "mode": "profile" | "favorites" | "samples",
      "products": [Product + price_text + match{category?, brand?, inBudget?, favoriteName?}],
      "error": false,       # true = 画像/检索挂了，前端显示「推荐暂时加载不出来…」+ 示例问题
      "cached": true,       # 命中 rec:{user_id} 缓存
      "round": 0,           # 第几次「换一批」
      "exhausted": false    # 换一批没换出新商品
    }
当前用户来自 Depends(get_current_user_id)；缺身份是 401（这是鉴权问题，不属于「推荐挂了」）。
除此之外这个接口永远返回 200：首页推荐是锦上添花，出任何错都不能让新对话页变成白屏。
普通 def：检索和 Redis 都是同步调用，交给线程池。
"""
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
