"""Web 层：按业务拆分的 FastAPI 路由包。

约定（与参考工程一致）：每个子包 <name>_router/ 里
  - <name>_router.py 定义 APIRouter 实例
  - __init__.py 只负责 from ... import xxx_router + __all__
由 app/main.py 统一 include_router 挂载，路由内部不自己 new 图，
一律从 request.app.state.shopping_graph 取应用启动时装配好的对象
（这个属性名只此一处，别再出现 shopping_agent 之类的第二个名字）。

当前挂载情况（见 app/main.py）：
  - chat_router/     聊天 + SSE 流式输出          → GET  /chat
  - products_router/ 商品检索结果（读检查点状态）  → POST /api/products/search
  - favorite_router/ 收藏夹读写                    → POST/GET/DELETE /api/favorites
  - system_router/   运维接口                      → GET  /health
  - websocket_router/ WebSocket 示例骨架，暂未挂载
  - default_page_router/ 页面路由骨架，前后端分离后由前端路由接管，暂未挂载

已删除：intent_router/（原先的 POST /api/intent 只回一句话、拿不到商品，
功能被 products_router 取代；目录里只剩 __pycache__，可以一并删掉）。
"""

from app.web.chat_router import chat_router
from app.web.favorite_router import favorite_router
from app.web.products_router import products_router
from app.web.system_router import system_router

__all__ = ['chat_router', 'favorite_router', 'products_router', 'system_router']
