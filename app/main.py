from __future__ import annotations
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from dotenv import load_dotenv
load_dotenv()
from app.web.chat_router import chat_router
from app.web.system_router import system_router
from app.ai.agent.multi_agent.graph.shopping_graph import ShoppingGraph
@asynccontextmanager
async def content_manager(app:FastAPI):
    print("模型配置：")
    app.state.shopping_agent = ShoppingGraph()
    print("AI购物智能体创建成功")
    yield
    #消耗对象
    app.state.shopping_agent = None
    print("AI购物智能体消耗成功")
application = FastAPI(title="PricePilot", version="0.1.0", lifespan=content_manager)

# 聊天与 SSE 流式输出
application.include_router(chat_router)
application.include_router(system_router)
app = application
if __name__ =="__main__":
    uvicorn.run(app,host="localhost",port=8000)
