from fastapi import FastAPI, WebSocket,WebSocketDisconnect
from fastapi import  APIRouter

websocket_router = APIRouter()
@websocket_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # 接受 WebSocket 连接
    await websocket.accept()
    print("客户端已连接")
    try:
       while True:
           # 接收客户端消息
           message = await websocket.receive_text()
           print(f"客户端：{message}")
           # 返回消息给客户端
           await websocket.send_text(f"服务器收到：{message}")
    except WebSocketDisconnect:
        print('客户端已经断开')
    except Exception as e:
        print(f'WebSokcet 异常: {e}')
