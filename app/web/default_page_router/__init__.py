"""默认页面路由。"""

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
