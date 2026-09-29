from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from app.ai.agent.multi_agent.graph.shopping_graph import ShoppingGraph
from app.web.chat_router import chat_router
from app.web.favorite_router import favorite_router
from app.web.login_router import email_router, register_router, user_router
from app.web.recommend_router import recommend_router
from app.web.session_router import session_router
from app.web.system_router import system_router


@asynccontextmanager
async def content_manager(app: FastAPI):
    app.state.shopping_agent = ShoppingGraph()
    print('购物助手已启动')
    yield
    app.state.shopping_agent = None


application = FastAPI(title='PricePilot', version='0.1.0', lifespan=content_manager)
application.include_router(chat_router)
application.include_router(system_router)
application.include_router(favorite_router, prefix='/api')
application.include_router(session_router, prefix='/api')
application.include_router(recommend_router, prefix='/api')
application.include_router(user_router, prefix='/user')
application.include_router(register_router, prefix='/user')
application.include_router(email_router, prefix='/user')

app = application

if __name__ == '__main__':
    uvicorn.run(app, host='localhost', port=8000)
