"""PricePilot 应用入口：FastAPI 生命周期、运行模式与组件装配。

对应手册章节：`PricePilot-购物决策Agent开发手册/app/main.md`

职责边界（只做装配与生命周期，不含业务实现）：

1. 三个依赖注入工厂，顺序固定：checkpointer -> graph -> service -> router。
   ``graph_factory(checkpointer)`` / ``service_factory(graph)`` / ``router_factory(service)``。
   本文件不实现节点、工具、仓储与页面；工厂未传入时对应组件记为未装配，
   由日志与 ``/health`` 的 ``unresolved`` 明确报告，不用假数据路由顶替。
2. 模型入口、来源适配器、数据库连接等网络客户端在 ``service.start()`` 中打开，
   ``service.aclose()`` 关闭；启动异常不能留下未关闭资源。
3. 单进程单 worker。定时监控属于 jobs 的独立进程，不要每个 Web worker 各起一份。
4. 静态目录按入口文件定位，换工作目录启动时仍然正确。
5. 健康检查只报告状态与装配情况，不返回路径、环境变量或任何密钥。

本地运行::

    python -m app.main                                        # 开发启动
    uvicorn app.main:application --reload                     # 需要热重载时
    uvicorn app.main:create_app --factory --reload            # 或在工厂上热重载

依赖 FastAPI + uvicorn；图与检查点还需要 langgraph，未安装时入口以骨架模式启动。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("pricepilot.main")

# 静态目录相对入口文件定位，不使用 "./html" 这类依赖当前工作目录的写法。
APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "html"

# 手册 main 章：demo_full / live_showcase / live_full 的选择条件见平台接入章节。
DATA_MODES = ("demo_full", "live_showcase", "live_full")
DEFAULT_DATA_MODE = "demo_full"

Factory = Callable[[Any], Any]


class ConfigError(RuntimeError):
    """运行配置不合法：直接拒绝启动，不把真实运行悄悄降级成演示模式。"""


def resolve_data_mode(raw: str | None = None) -> str:
    """确定数据模式；未知取值直接报错，避免 live_* 被当成 demo_* 跑。"""
    mode = (raw or os.environ.get("SHOPPING_DATA_MODE") or DEFAULT_DATA_MODE).strip()
    if mode not in DATA_MODES:
        raise ConfigError(
            "未知的 SHOPPING_DATA_MODE={!r}；可选值：{}".format(mode, "、".join(DATA_MODES))
        )
    return mode


def default_checkpointer() -> Any | None:
    """单进程内存检查点。

    InMemorySaver 不跨进程、不跨重启恢复，只承诺单进程存续期内的会话；
    业务收藏与历史必须落主库，不能靠检查点充当持久化。
    """
    try:
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError:
        logger.warning("未安装 langgraph，图与检查点不可用；入口以骨架模式启动")
        return None
    return InMemorySaver()


def create_app(
    graph_factory: Factory | None = None,
    service_factory: Factory | None = None,
    router_factory: Factory | None = None,
    *,
    data_mode: str | None = None,
    checkpointer_factory: Callable[[], Any] = default_checkpointer,
) -> FastAPI:
    """按手册顺序装配组件，返回 FastAPI 应用。

    三个工厂都可以传 ``None``：对应组件记为未装配，入口只提供 ``/health``
    与静态目录，并在 ``/health`` 的 ``unresolved`` 中明确报告。
    """
    mode = resolve_data_mode(data_mode)
    missing: list[str] = []

    checkpointer = None
    graph = None
    service = None
    router = None

    if graph_factory is None:
        missing.append("graph_factory")
    else:
        checkpointer = checkpointer_factory()
        if checkpointer is None:
            missing.append("checkpointer(langgraph)")
        else:
            graph = graph_factory(checkpointer)

    if service_factory is None:
        missing.append("service_factory")
    elif graph is not None:
        service = service_factory(graph)

    if router_factory is None:
        missing.append("router_factory")
    elif service is not None:
        router = router_factory(service)

    wired = [
        name
        for name, component in (("graph", graph), ("service", service), ("router", router))
        if component is not None
    ]

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        logger.info(
            "PricePilot 启动 data_mode=%s 已装配=%s 未装配=%s",
            mode,
            "、".join(wired) or "无",
            "、".join(missing) or "无",
        )
        if service is not None:
            try:
                # 网络客户端、模型入口与来源适配器在 start() 中打开。
                await service.start()
            except BaseException:
                # 启动异常不能留下未关闭资源。
                await service.aclose()
                raise
        try:
            yield
        finally:
            if service is not None:
                await service.aclose()
                logger.info("PricePilot 已关闭，资源已释放")

    application = FastAPI(title="PricePilot", version="0.1.0", lifespan=lifespan)
    application.state.data_mode = mode
    application.state.shopping_service = service
    application.state.unresolved_components = tuple(missing)

    if router is not None:
        application.include_router(router)

    if STATIC_DIR.is_dir():
        application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    else:
        logger.info("静态目录 %s 尚未创建，/static 暂不挂载", STATIC_DIR.name)

    @application.get("/health", tags=["ops"])
    async def health() -> dict[str, Any]:
        """健康检查：只报告状态与装配情况，不暴露密钥、路径与环境变量。"""
        return {
            "status": "ok" if not missing else "degraded",
            "data_mode": mode,
            "components": {
                "graph": graph is not None,
                "service": service is not None,
                "router": router is not None,
            },
            "unresolved": list(missing),
        }

    return application


# 模块级应用对象：``uvicorn app.main:application`` 直接可用。
# 三个工厂实现后在这里传入，例如 create_app(graph_factory=..., service_factory=..., router_factory=...)。
application = create_app()


def main() -> None:
    """开发启动入口：``python -m app.main``。"""
    logging.basicConfig(
        level=os.environ.get("PRICEPILOT_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    host = os.environ.get("PRICEPILOT_HOST", "127.0.0.1")
    port = int(os.environ.get("PRICEPILOT_PORT", "8000"))

    import uvicorn

    # 单进程单 worker：监控循环属于独立进程，不要每个 worker 各起一份。
    uvicorn.run(application, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
