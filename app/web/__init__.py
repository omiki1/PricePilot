"""Web 层：按业务拆分的 FastAPI 路由包。"""

from app.web.chat_router import chat_router
from app.web.favorite_router import favorite_router
from app.web.products_router import products_router
from app.web.system_router import system_router

__all__ = ['chat_router', 'favorite_router', 'products_router', 'system_router']
