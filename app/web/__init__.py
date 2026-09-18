"""Web 层：按业务拆分的 FastAPI 路由包。

约定（与参考工程一致）：每个子包 `<name>_router/` 里
  - `<name>_router.py` 定义 `APIRouter` 实例
  - `__init__.py` 只负责 `from ... import xxx_router` + `__all__`
由 `app/main.py` 统一 `include_router` 挂载，路由内部不自己 new 图，
一律从 `request.app.state` 取应用启动时装配好的对象。

当前状态：
  - intent_router/    意图识别业务（已接通 ShoppingGraph）→ POST /api/intent
  - system_router/    运维接口（健康检查）→ GET /health
  - chat_router/      聊天+语音骨架，依赖 ExamGraph/VoskAgent 等尚未迁过来的模块，暂不挂载
  - websocket_router/ WebSocket 示例骨架，暂未挂载
  - default_page_router/  页面路由骨架，前后端分离后由前端路由接管，暂未挂载
"""
