from __future__ import annotations
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from dotenv import load_dotenv
load_dotenv()
from app.web.chat_router import chat_router
from app.web.favorite_router import favorite_router
from app.web.login_router import email_router, register_router, user_router
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

# 收藏与价格记录：router 里定义的路径是 /favorites、/products/price-history，
# 而前端调的是 /api/favorites、/api/products/price-history（vite 把 /api 代理到后端）。
# 前缀在注册时补，别去改 router 文件里已有的路径。
application.include_router(favorite_router, prefix='/api')

# 账号相关：router 里定义的是 /login、/register、/sendEmail、/verifyCode，
# login_router.py 的文档字符串里写的访问路径本来就是 /user/xxx。
application.include_router(user_router, prefix='/user')
application.include_router(register_router, prefix='/user')
application.include_router(email_router, prefix='/user')
app = application
if __name__ =="__main__":
    uvicorn.run(app,host="localhost",port=8000)
