# 应用入口：生命周期与明确的运行配置

参考原 FastAPI lifespan。启动时创建模型入口、来源适配器、检查点、ShoppingGraph 与运行服务；关闭时清理资源。选择 demo_full、live_showcase 或 live_full 的条件见 [平台接入](ai/tool/Amazon与京东接入.md)。

## 参考代码：应用工厂（集成参考）

目标：`app/main.py`。依赖 FastAPI、LangGraph。为了不假装其他模块已实现，使用三个依赖注入函数：graph_factory(checkpointer)、service_factory(graph)、router_factory(service)。后两者需要按接口章节实现。

```python
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.memory import InMemorySaver

def create_app(graph_factory, service_factory, router_factory) -> FastAPI:
    graph = graph_factory(InMemorySaver())
    service = service_factory(graph)

    @asynccontextmanager
    async def lifespan(app):
        await service.start()
        app.state.shopping_service = service
        try:
            yield
        finally:
            await service.aclose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(router_factory(service))
    static_dir = Path(__file__).resolve().parent / "html"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
```

完成这些工厂函数后再在入口创建 app；当前片段本身不包含 uvicorn 启动对象。同步构图可在工厂中完成，网络客户端连接在 start() 中打开，aclose() 关闭；启动异常不能留下未关闭资源。

## 第一版部署约定

单个 Web 进程＋单个独立监控工作进程。不要每个 Web worker 都启动监控循环。InMemorySaver 不跨进程/重启恢复；业务收藏与历史在选定的 MySQL 或 PostgreSQL 中保存。

Redis 后续可以共享事件缓冲/缓存，但不能只加 Redis 就声称所有图状态和任务都可恢复。相同用户的同会话并发由运行服务管理。

## 启动验收

换工作目录时静态文件路径仍正确；演示模式不依赖真实平台凭证；关闭服务后无遗留邮件任务；平台权限缺失时明确状态；健康检查不暴露密钥。
