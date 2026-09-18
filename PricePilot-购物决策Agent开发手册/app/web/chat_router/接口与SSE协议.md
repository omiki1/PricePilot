# API 与 SSE：聊天、商品卡、比较页共用一份报告

运行由服务层创建，SSE 只订阅，不重复启动搜索。使用服务端身份和 run/session/watch 归属检查，不相信浏览器提交的 user_id。

## 接口合同

| 方法与路径 | 职责 |
|---|---|
| POST /sessions | 创建归属当前用户的 session |
| POST /shopping/runs | query、session_id、client_request_id；创建或返回同一运行 |
| GET /shopping/runs/{run_id} | 当前状态与最终结构化报告 |
| GET /shopping/runs/{run_id}/events | 进度与卡片快照，支持重连游标 |
| POST /shopping/runs/{run_id}/answers | 回答澄清，保留已确认条件 |
| POST /shopping/runs/{run_id}/cancel | 取消当前运行 |
| POST /watches | 用户确认规格、币种、目的地、阈值后创建监控 |
| GET /watches | 自己的收藏与监控状态 |
| PATCH /watches/{id} | 更新阈值或暂停/恢复 |
| DELETE /watches/{id} | 停止并删除 |
| GET /products/{id}/prices | 在来源许可范围内返回同口径历史 |

/watches 同时检查站点配置与来源 tracking_allowed；未启用时返回明确原因，不能只在前端禁用按钮。

## 事件

每个事件包含 schema_version、event_id、run_id、event_type、stage、emitted_at、payload。event_id 在单运行内递增。

run_started → stage_started/stage_completed → candidate_update → report_ready → run_finished。来源失败用 warning，整个运行失败用 error 和 failed 终态。clarification_required 对应 waiting_input；watch_confirmation_required 对应等待用户确认监控，不代表订阅已创建。

candidate_update 携带完整卡片快照及核验状态，未核验不得显示确定最低价。report_ready 是最终权威报告，金额与链接来自后端。第一版只使用 custom 流转应用事件；不把内部 messages token 再重复发一次。

## 参考代码：创建运行与 SSE 订阅路由（集成参考）

目标：`app/web/chat_router/chat_router.py`。需要实现 service 和 current_user。service 负责鉴权、幂等创建、任务启动、事件存储与心跳；本段只实现 HTTP 边界，不伪装完整任务系统。

```python
import json
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

class RunRequest(BaseModel):
    session_id: str
    client_request_id: str
    query: str = Field(min_length=1, max_length=4000)

def build_chat_router(service, current_user):
    router = APIRouter()

    @router.post("/shopping/runs", status_code=202)
    async def create_run(body: RunRequest, user=Depends(current_user)):
        # create_run 必须先校验 session 归属，再原子处理请求ID与启动。
        return await service.create_run(user["id"], body.model_dump())

    @router.get("/shopping/runs/{run_id}")
    async def get_run(run_id: str, user=Depends(current_user)):
        return await service.snapshot(user["id"], run_id)

    @router.get("/shopping/runs/{run_id}/events")
    async def events(
        run_id: str, request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        user=Depends(current_user),
    ):
        await service.assert_owner(user["id"], run_id)
        try:
            cursor = int(last_event_id or 0)
            if cursor < 0:
                raise ValueError
        except ValueError:
            raise HTTPException(400, "事件游标必须为非负整数")
        # 开始响应前检查游标是否超出缓冲范围，过期则让客户端重取快照。
        await service.assert_cursor(run_id, cursor)

        async def stream():
            # events 应约每15秒产出一次 None 心跳，避免无限静默阻塞。
            async for event in service.events(run_id, after=cursor):
                if await request.is_disconnected():
                    break
                if event is None:
                    yield ": heartbeat\n\n"
                    continue
                payload = json.dumps(event, ensure_ascii=False)
                yield f"id: {event['event_id']}\ndata: {payload}\n\n"
                if event["event_type"] in {
                    "run_finished", "clarification_required",
                    "watch_confirmation_required",
                }:
                    break
        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return router
```

service.events 返回可 JSON 序列化的 dict，Decimal 用字符串、时间用 ISO8601。不能直接 json.dumps 原始 Pydantic 对象。SSE 格式基础参见 [MDN Event stream format](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#event_stream_format)。

## service 至少实现的行为

同用户同请求 ID 原子防重；同 session 单活跃 run；run 完成先保存快照再发终态；事件有限缓冲并按游标回放；断开订阅不创建新任务；取消标识阻止晚到结果；重启失效有明确错误。单进程先实现内存运行管理，业务收藏仍落主库。

Cookie 认证时 POST/PATCH/DELETE 需要相应 CSRF 防护；API 密钥不放到 SSE URL。真实来源抓取错误不要把凭证和原始异常堆栈发给浏览器。
