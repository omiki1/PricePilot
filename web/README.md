# web：PricePilot 前端（Vue3 + Vite，前后端分离）

当前只接入**已完成的意图识别业务**（后端 `START → intent → END`）。

> 商品检索（多来源 tool、价格过滤、结果缓存）的代码已按你的要求撤掉，
> 完整源码与实测字段档案保留在
> `PricePilot-购物决策Agent开发手册/附录/Apify检索接入-代码存档与实测.md`。

## 启动

```powershell
# 1) 后端（仓库根目录下）
cd C:\workspace\PricePilot
C:\Users\freeing1\anaconda3\envs\langchain_env\python.exe -m app.main   # http://127.0.0.1:8000

# 2) 前端（本目录，端口固定 8080）
npm install
npm run dev                                                            # http://127.0.0.1:8080
```

## 请求怎么走

1. `src/api.js` 里 `API_BASE = import.meta.env.VITE_API_BASE || ''`，默认留空 → 请求用相对路径 `/api/intent`。
2. 相对路径发给 8080，由 `vite.config.js` 的 `server.proxy` 转发到 `http://127.0.0.1:8000`（`/api`、`/health` 两条），同源无预检。
3. 想直连后端做真跨域：设 `VITE_API_BASE=http://127.0.0.1:8000`，由后端 `CORSMiddleware` 放行（源可用 `PRICEPILOT_CORS_ORIGINS` 配置）。

## 目前用到的接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/intent` | `{question, user_id, session_id}` → `{user_id, session_id, text}` |
| POST | `/api/intent/stream` | 同上，`text/plain` 流式（前端暂未接） |
| GET | `/health` | `{status, components:{graph}}`，页面右上角的状态就来自这里 |

后端对应实现：`app/web/intent_router/`（业务）与 `app/web/system_router/`（运维），
在 `app/main.py` 里用 `include_router` 挂载；图在 `lifespan` 中创建并放到 `app.state.shopping_graph`。
