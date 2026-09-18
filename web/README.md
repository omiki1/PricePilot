# web：PricePilot 前端（Vue3 + Vite，前后端分离）

当前只接入**已完成的意图识别业务**（后端 `START → intent → END`），其余页面待业务节点实现后再加。

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
| POST | `/api/products/search` | `{keyword, sources[], mode?, limit}` → 每个来源一个 `SearchOutcome` + `cache` 命中情况 |
| GET | `/api/sources` | 当前启用的来源、凭证状态、**计费说明**、缓存状态 |
| POST | `/api/xianyu/search` | 旧接口（闲鱼来源未启用时返回 503 说明） |
| GET | `/health` | `{status, components:{graph, sources{}}, cache}` |

## 来源与花费（实测，2026-09-18）

| 来源 | 状态 | 计费 | 关键词查询 |
|---|---|---|---|
| **taobao**（`zen-studio/taobao-search-scraper`） | **当前启用** | 每次运行 **$0.05 启动费** + $0.00001/条 | ✅ `keyword` 必填；`maxItems` **下限 10** |
| xianyu（`piotrv1001/...`） | 代码保留、未启用 | $0.00005 启动 + $0.002/条 | ❌ 需闲鱼登录态 |
| amazon（`junglee/amazon-crawler`） | 代码保留、未启用 | **包月 $40–60**，非按条 | ✅ 关键词要拼搜索页 URL |

启停用 `.env` 的 `PRICEPILOT_ENABLED_SOURCES`（逗号分隔），默认 `taobao`。
未启用的来源不会装配、也不出现在前端可选项里。

## 怎么少花钱

1. **TTL 结果缓存**（主要手段）：`PRICEPILOT_CACHE_TTL`（默认 600 秒）。同一来源 + 同一关键词 + 同一模式
   在 TTL 内重复检索直接命中缓存，**不再触发 actor 运行**——因为按事件计费的来源有固定启动费，
   "少取几条"几乎不省钱，"少跑几次"才省钱。实测第二次检索 0.0s、`cache.hit=["taobao"]`。
2. **硬上限**：`.env` 的 `APIFY_MAX_CHARGE_USD`（默认 0.2）会作为 `maxTotalChargeUsd` 传给 Apify，
   本次运行花费达到上限即被中止。
3. **展示条数**：`limit` 只影响返回给前端的条数（淘宝侧实际仍取 `maxItems>=10`），
   减少展示不减少费用，但能省前端渲染与上下文。
4. 失败的检索不写入缓存，避免把故障缓存 10 分钟。

> 想再省，还可以在 Apify 控制台给账号设**月度花费上限**（这是最硬的闸）；额度用尽时接口会返回
> `status="failed"` 并带上受控的错误信息，而不会静默返回空列表。

后端对应实现：`app/web/intent_router/`、`app/web/shopping_router/`、`app/web/system_router/`，
来源适配器在 `app/ai/tool/xianyu_tool.py` 与 `app/ai/tool/amazon_tool.py`，
数据结构在 `app/ai/agent/multi_agent/schema/shopping_schema.py`（`Offer` / `SearchOutcome`）；
在 `app/main.py` 里用 `include_router` 挂载，图与两个来源适配器都在 `lifespan` 中创建并放到 `app.state`。

> 采集走 Apify 的 HTTP API（同一个 `APIFY_TOKEN` 也能通过 `mcp.apify.com` 的 MCP 网关用）。
> 仓库根目录 `.env` 里相关变量：
> `APIFY_TOKEN`、`PRICEPILOT_ENABLED_SOURCES`、`PRICEPILOT_CACHE_TTL`、`APIFY_MAX_CHARGE_USD`、
> `APIFY_TAOBAO_ACTOR`（以及暂未启用的 `APIFY_XIANYU_ACTOR`、`APIFY_AMAZON_ACTOR`、`APIFY_AMAZON_COUNTRY`）。
