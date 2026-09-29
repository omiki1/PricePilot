# PricePilot · 多智能体购物比价助手

一个会「先问清楚再推荐」的购物助手。用户说一句模糊需求（比如「1000 以内的通勤耳机」），
系统先判断这句话该怎么处理——闲聊、追问，还是去检索商品——再把候选商品拉回来，
用程序（而不是模型）排序，最后给出带第三方证据的推荐结论。

**核心主张：排序和金额不由模型决定。** 模型可以说不清楚、可以说得难听，
但它没有机会改变「谁排第一」，也没有机会编造一个价格。

---

## 目录

- [功能概览](#功能概览)
- [技术栈](#技术栈)
- [架构](#架构)
- [核心设计取舍](#核心设计取舍)
- [快速开始](#快速开始)
- [环境变量](#环境变量)
- [数据库](#数据库)
- [测试](#测试)
- [目录结构](#目录结构)

---

## 功能概览

| 能力 | 说明 |
| --- | --- |
| 意图分流 | 一句话分到闲聊 / 追问 / 商品检索三支；**检索词为空时退回追问**，避免用空 query 去打检索接口 |
| 商品检索 | 通过 MCP 调用 Shopify catalog，统一转换成内部 `Product` 对象，本地按预算二次复核 |
| 多轮澄清 | 需求不明确时先追问；带话题切换守卫，避免把上一轮的品类继承过来 |
| 用户记忆 | 四层记忆（窗口 / 摘要 / 语义偏好 / 结构化画像），跨会话累积，任一层故障只降级不影响主链路 |
| 价格引擎 | 券互斥、门槛、有效期、返现上限的合同化校验；多币种折算 |
| 证据体系 | 抓取第三方评价作为证据；报告里**查无出处的金额会被自动拦下** |
| 排序 | 贝叶斯加权排序取 Top3，解决「5.0 分只有 3 条评价」压过「4.6 分有 656 条」 |
| 对比报告 | 独立的对比子图：预处理 → 评价分析 → 确定性比较 → 报告生成 |
| 首页推荐 | 按用户画像推荐；画像为空时依次降级到收藏夹、示例问题 |
| 会话管理 | 会话列表 / 历史消息 / 重命名 / 软删除，按 `user_id` 校验归属 |
| 用户账号 | 注册、登录（bcrypt）、邮箱验证码 |
| 前端 | Vue 3 + Vite，SSE 流式输出，商品卡、收藏夹、价格历史 |

---

## 技术栈

**后端**

- Python 3.12 + FastAPI（async）
- LangGraph — 多智能体编排、条件路由、检查点
- LangChain — Agent 构建与结构化输出
- Pydantic — 结构化输出 schema 与数据校验
- Redis — 对话窗口记忆、用户画像、推荐缓存
- PostgreSQL — 会话摘要、LangGraph checkpoint
- MySQL — 用户、收藏夹、价格历史、商品/报价/证据
- ChromaDB — 长期记忆向量检索（本地中文嵌入模型）

**前端**

- Vue 3（`<script setup>`）+ Vite
- SSE（`EventSource`）流式接收

---

## 架构

### 主图：意图分流

```
START → intent ─┬─(chat)──────────→ chat ──────────────→ END
                │
                ├─(clarify)───────→ clarify ───────────→ END
                │
                └─(shopify_search)→ shopify_search → recommend → output → END
```

路由函数 `route_after_intent` 的判定逻辑：

```python
if router == 'chat':                    return 'chat'
if router == 'search' and category:     return 'shopify_search'   # 有检索词才检索
return 'clarify'                                                  # 否则一律追问
```

> 最后一行是刻意的：`search` 但抽不到检索词时**不许**去打检索接口。
> Shopify catalog 是宽松语义检索，给什么 query 都返回 50 条——
> 实测 `'鸣潮'` 会返回一味中药（`Rhizoma`），中文长句会返回一本讲鸡的书。
> 空查询等于「随机抽 50 个商品给模型推荐」，比追问更糟。

### 对比子图

商品对比是独立编排的，与主图解耦：

```
START → prepare → review → compare → reporter → END
```

| 节点 | 职责 |
| --- | --- |
| `prepare` | 归一化候选商品与报价 |
| `review` | 抓取、清洗、分析第三方评价，产出证据与去重口径报告 |
| `compare` | 程序主导的确定性比较（硬约束过滤、同口径分组、排序键计算） |
| `reporter` | 生成商品卡与解释文字；核对解释里的金额是否可溯源 |

### 四层记忆

| 层 | 存储 | 内容 | 时效 |
| --- | --- | --- | --- |
| L1 窗口 | Redis List | 最近若干轮原始对话 | 本次会话 |
| L2 摘要 | PostgreSQL | 更早内容的压缩摘要 | 本次会话 |
| L3 长期 | Chroma 向量库 | 一贯偏好（语义检索 Top-N） | 跨会话 |
| L4 画像 | Redis Hash | 结构化属性（城市、预算习惯、偏好品牌…） | 跨会话 |

组装顺序为 **窗口 → 摘要 → 长期 → 画像**（由近到远，冲突时模型应更信靠前的），
进图前拼成一段文本注入 state，各层独立 `try/except`——单层故障只让该段留白。

---

## 核心设计取舍

这几条是项目里最值得说明的决定，都对应代码注释中记录的实测过程。

### 1. 排序交给程序，不交给模型

`rank_top3.py` 用贝叶斯平均（同 IMDB Top 250 口径）：

```
score = (v/(v+m))·R + (m/(v+m))·C      m = 50，C 取本次候选均值
```

排序键全部来自结构化字段：**有证据支持的偏好数 ↓ → 同币种金额 ↑ → 稳定商品 ID ↑**。
同一份输入重跑必然得到同一份排序。无评价商品 `score = None` 并标注「暂无评价，无法评估」，
**而不是当 0 分**——否则「没有评价」和「评价很差」会被混为一谈。

### 2. 价格是有约束的合同对象，不是一个 float

一次付款同时受券互斥组、券门槛、有效期、返现上限、币种约束。
`price_schema.py` 把校验放在合同层：负价 / 零价直接拒绝、三位小数拒绝、
返现超过付款金额报错、优惠大于商品金额被排除、`now` 必须带时区、
有效期取**选中券里最早的截止时间**。金额全程 `Decimal`。

### 3. 结论必须能溯源，溯源不到就丢掉

`reporter_node` 里有一道事后核对：报告解释中出现的金额必须能对应到证据 ID，
对不上的会被判定为模型编造并揪出（同时避免把「条数」「比例」这类统计数字误判成金额）。
`review_evidence.sanitize_analysis` 同理——**引用不到的结论直接丢弃**。

### 4. 预算语义是「上限」，不是「区间」

`adapter.py` 里有一条被记录下来的修正：`BUDGET_MIN_RATIO` 原为 `0.1`，
它把「1000 以内」解释成 900~1000 的区间。实测后果是——接口按 ≤上限 返回 50 条，
本地复核却把这 50 条全部判为「低于下限」丢弃，最终候选 0 条、前端显示空白。
置 0 后只保上限，与接口侧口径一致。

### 5. 记忆接入必须是可失败的

四层记忆是「锦上添花」，不是主链路的一部分。`shopping_graph.py` 里它的 import
被包在 `try/except` 中：import 不到、或 Redis / PG / 向量库任一挂掉，
都只降级成「本轮无记忆」，绝不让整次对话失败。
记忆的**写入**丢到后台 task（L2/L3/L4 都要调模型，耗时数秒），不阻塞 SSE 的结束帧。

### 6. 追问轮的记忆要取 `question`，不能取 `answer`

`answer` 在 LangGraph state 里是普通 channel——本轮没跑 `output` / `chat` 时它不会更新，
会残留上一轮的商品解读。如果直接写进 L1 窗口，记忆里就会出现「答非所问」的假历史
（本轮只是追问「想买哪类？」，却被记成一段商品推荐）。
所以 `clarify` / `reject` 轮必须取 `state['question']`。

### 7. Windows 上 psycopg 必须用同步驱动

psycopg 的异步模式需要 `SelectorEventLoop`，而 uvicorn 在 Windows 上硬编码返回
`ProactorEventLoop`，且 `set_event_loop_policy()` 管不着它（那行是直接返回类，不看 policy）。
异步连接必然报 `Psycopg cannot use the 'ProactorEventLoop' to run in async mode`。
解法是同步驱动 + `asyncio.to_thread`，连接在哪个线程跑都行，与事件循环类型无关。

---

## 快速开始

### 前置依赖

- Python 3.12（建议用 conda 环境）
- Node.js 18+
- Redis、MySQL、PostgreSQL、ChromaDB（Chroma 为嵌入式，无需单独启动服务）

### 1. 安装后端依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，按注释填写（见[环境变量](#环境变量)）。

### 3. 初始化数据库

```bash
# MySQL：建表 + 演示数据
mysql -u root -p < db/schema_mysql.sql

# PostgreSQL：记忆模块表
psql -U postgres -f db/schema_memory_pg.sql
```

### 4. 启动后端

```bash
python -m uvicorn app.main:app --port 8000
```

健康检查：`GET http://127.0.0.1:8000/health` → `{"status":"ok","components":{"graph":true}}`

### 5. 启动前端

```bash
cd web
npm install
npm run dev
```

打开 `http://127.0.0.1:8080`。

> **端口约定**：前端固定 8080，后端固定 8000，vite 的代理在 `web/vite.config.js` 里
> 写死指向 `http://127.0.0.1:8000`。改后端端口时这里要同步改，否则页面「发出去没有任何回应」。

---

## 环境变量

| 变量 | 用途 |
| --- | --- |
| `LINE_MODEL_NAME` | 对话模型名（回退：`MAIN_MODEL_NAME` / `MODEL_LINE_NAME`） |
| `LINE_MODEL_API_KEY` | 模型 API Key（回退：`MAIN_MODEL_API_KEY` / `COMMANDCODE_API_KEY`） |
| `LINE_MODEL_BASE_URL` | 兼容 OpenAI 协议的端点（回退：`MAIN_MODEL_BASE_URL` / `OPENAI_API_BASE`） |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` / `REDIS_PASSWORD` | Redis 连接（窗口记忆、画像、推荐缓存） |
| `WINDOW_MEMORY_ROUNDS` | L1 窗口保留的消息条数（user 与 ai 各算一条） |
| `WINDOW_MEMORY_TIME` | L1 窗口过期秒数 |
| `POSTGRESQL_URL` | PostgreSQL 连接串（会话摘要、checkpoint） |
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` / `MYSQL_CHARSET` | MySQL 连接（用户、收藏、价格历史） |
| `CHROMA_PATH` | 向量库持久化目录 |
| `EMBEDDING_LOCAL_PATH` | 本地嵌入模型路径（中文用 `bge-base-zh` 一类；不配则退回 Chroma 默认英文模型） |
| `EMBEDDING_DEVICE` | 嵌入模型运行设备，如 `cpu` |
| `SENDER_EMAIL` / `SENDER_EMAIL_PASSWORD` / `SMTP_HOST` / `SMTP_PORT` | 注册邮箱验证码 |

模型配置的自查命令：

```bash
python -c "from app.ai.model.my_model import describe; print(describe())"
```

---

## 数据库

| 脚本 | 内容 |
| --- | --- |
| `db/schema_mysql.sql` | `users`、`products`、`offers`、`evidence`、`price_history`、`watch_list`、`notification_log`、`review_samples`、`chat_session`、`chat_message` |
| `db/schema_memory_pg.sql` | `conversation_summary`（L2 摘要，`session_id` 为 TEXT） |

Redis 键约定：

| 键 | 类型 | 内容 |
| --- | --- | --- |
| `window_memory:{session_id}` | List | L1 窗口消息（JSON） |
| `profile:{user_id}` | Hash | L4 用户画像字段 |
| 推荐缓存键 | String | 首页推荐结果（带画像指纹，画像变化自动失效） |

---

## 测试

```bash
# MySQL 相关用例需要真实数据库，没有就关掉
export PRICEPILOT_TEST_MYSQL=0      # Windows PowerShell: $env:PRICEPILOT_TEST_MYSQL='0'

python -m pytest app/tests -q --disable-warnings
```

当前结果：**149 passed, 2 skipped**。

部分测试文件自带 runner，也可直接运行：

```bash
python -m app.tests.test_price
python -m app.tests.test_intent_routing
python -m app.tests.test_compare_report
```

测试覆盖的重点是业务规则而不是 CRUD，例如：

- 券缺证据则被排除；负价 / 三位小数在合同层就被拒绝
- 报告解释里查无出处的金额会被揪出，而纯统计数字不会被误判
- 避雷项只做字面匹配（不命中近义词），且命中即硬排除而非降权
- 意图路由：话题切换不得继承上一轮品类；空检索词必须转追问

---

## 目录结构

```
app/
├── main.py                     应用入口，注册各路由
├── ai/
│   ├── agent/
│   │   ├── multi_agent/
│   │   │   ├── graph/          主图 shopping_graph、对比子图 comparison_graph
│   │   │   ├── node/           各节点：intent / chat / clarify / shopify_search
│   │   │   │                            / recommend / output / compare / review / reporter
│   │   │   ├── schema/         结构化输出 schema 与适配层
│   │   │   └── state/          ShoppingState（图内共享状态）
│   │   └── memory/             四层记忆：save（存储）/ retrieval（提取）/ manager（调度）
│   ├── model/                  模型封装与单例
│   ├── prompt/                 提示词加载（YAML）
│   └── tool/                   检索、价格、证据、排序、仓储等工具层
├── web/                        路由层：chat / session / favorite / recommend / login …
└── tests/                      测试
db/                             建表脚本
web/                            前端（Vue 3 + Vite）
docs/                           设计说明
tools/                          调试与探针脚本
```

---

## 设计文档

- `docs/后端精简说明.md` — 后端结构整理记录
- `docs/git-workflow.md` — Git 协作流程说明
