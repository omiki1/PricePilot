"""默认页面路由。

【临时方案】当前页面通过 /pages 静态挂载访问：
    http://localhost:8000/pages/chat.html

这里**故意不再**把聊天页挂到根路径 /，
目的是让后端只做"API 服务 + 静态文件托管"，为后续前后端分离做准备。

前后端分离后本文件可以直接删除/停用，届时：
    - 前端独立工程（如 Vite）跑在 5173，通过完整地址调用 http://localhost:8000/chat
    - 后端不再托管任何 HTML，app/html 目录整体移除
    - 后端需要加 CORSMiddleware 允许前端源跨域
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

default_page_router = APIRouter()

# app/web/default_page_router/__init__.py -> parents[2] = app 目录
_HTML_DIR = Path(__file__).resolve().parents[2] / 'html'


@default_page_router.get('/login', include_in_schema=False)
async def login_page():
    """登录页（仅作演示；正式分离后由前端路由接管）。"""
    return FileResponse(_HTML_DIR / 'login.html')
