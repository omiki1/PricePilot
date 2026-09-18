from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# 入口先读 .env：模型配置从环境变量取，不各自重复加载。
load_dotenv()

# 路由与参考工程一致：app/web/<name>_router/__init__.py 导出 xxx_router，这里只做 include。
from app.web.intent_router import intent_router
from app.web.system_router import system_router

logger = logging.getLogger("pricepilot.main")

# 前端（前后端分离）开发服务器地址，默认 Vite 的 8080；可用逗号分隔配置多个。
DEFAULT_CORS_ORIGINS = "http://127.0.0.1:8080,http://localhost:8080"


def cors_origins() -> list[str]:
    raw = os.environ.get("PRICEPILOT_CORS_ORIGINS") or DEFAULT_CORS_ORIGINS
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭钩子：在 lifespan 里建图，关闭时释放。

    为什么放在这里而不是模块级：
      ① 模块级创建会在 import 时执行，测试/脚本一 import 就被连带跑起来；
      ② lifespan 里创建，服务真正启动时才初始化，关闭时能优雅清理；
      ③ 图挂在 app.state 上，路由里用 request.app.state.shopping_graph 取
         （app/web/intent_router 就是这么拿的），检查点生命周期由应用统一管理。
    """
    from app.ai.agent.multi_agent.node.graph.shopping_graph import ShoppingGraph

    try:
        app.state.shopping_graph = ShoppingGraph()
        logger.info("ShoppingGraph 创建成功（START → intent → END）")
    except Exception as exc:
        # 依赖或模型配置有问题时不假装成功：/health 报 degraded，接口返回 503。
        app.state.shopping_graph = None
        logger.error("ShoppingGraph 创建失败，意图识别接口将返回 503：%s", exc)

    try:
        yield
    finally:
        app.state.shopping_graph = None
        logger.info("PricePilot 已释放，资源已清理")


application = FastAPI(title="PricePilot", version="0.1.0", lifespan=lifespan)

# 允许前端开发服务器（8080）跨域直连；走 vite 代理时同源，不产生预检。
application.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 意图识别业务：POST /api/intent、POST /api/intent/stream
application.include_router(intent_router, prefix="/api")
# 运维接口：GET /health
application.include_router(system_router)

# 模块级应用对象：``uvicorn app.main:application`` 直接可用。
app = application


def main() -> None:
    """开发启动入口：``python -m app.main``，默认 http://127.0.0.1:8000。"""
    logging.basicConfig(
        level=os.environ.get("PRICEPILOT_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    host = os.environ.get("PRICEPILOT_HOST", "127.0.0.1")
    port = int(os.environ.get("PRICEPILOT_PORT", "8000"))

    import uvicorn

    logger.info("PricePilot 启动于 http://%s:%s（前端默认 http://127.0.0.1:8080）", host, port)
    uvicorn.run(application, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
