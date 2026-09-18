# ShoppingState：明确动作与需求两个层次

沿用 ExamState 的 TypedDict 思路。V2 增加 action 与独立的 requirements；Intent 不再同时负责预算抽取。消息历史与当前业务结果分开。

## 谁更新哪些字段

| 字段 | 写入方 | 规则 |
|---|---|---|
| query、run_id、session_id、user_id | 服务入口 | 当前输入与可信归属 |
| action | Intent | search / compare / price / track |
| requirements、pending_question | Requirement | 澄清后合并，正常新查询重置 |
| candidates、source_status | Search | 按来源返回结构化数据与失败原因 |
| normalized_products | Normalize | 同款、不同款、待确认 |
| price_results、price_status | Price | 只写价格分支字段 |
| review_results、review_status | Review | 只写评论分支字段 |
| comparison_result | Compare | 程序过滤后形成分组与排序 |
| final_report、run_status | Reporter / 控制节点 | 报告为结构化对象，不只是字符串 |

并行分支不共同写 messages、phase、run_status 或共享 errors 列表；各分支独立返回错误，汇合处再合并。

## 参考代码：状态与新运行初始化（模块参考）

目标：`app/ai/agent/multi_agent/state/shopping_state.py`。依赖本手册统一 Schema 和 LangGraph。

```python
from typing import Annotated, Any, Literal, TypedDict
from uuid import uuid4
from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph.message import add_messages
from app.ai.agent.multi_agent.schema.shopping_schema import (
    Action, RequirementSchema, Offer, PriceQuote, ReviewAnalysis,
)

class ShoppingState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    user_id: str
    session_id: str
    run_id: str
    query: str
    action: Action
    requirements: RequirementSchema
    pending_question: str | None
    candidates: list[Offer]
    source_status: dict[str, str]
    normalized_products: list[dict[str, Any]]
    price_results: list[PriceQuote]
    price_status: Literal["completed", "empty", "failed"]
    review_results: list[ReviewAnalysis]
    review_status: Literal["completed", "empty", "failed"]
    price_error: str | None
    review_error: str | None
    comparison_result: dict[str, Any]
    final_report: dict[str, Any] | None
    run_status: Literal[
        "running", "waiting_input", "awaiting_watch_confirmation",
        "completed", "failed", "cancelled",
    ]

def new_run(query: str, user_id: str, session_id: str) -> ShoppingState:
    return {
        "messages": [HumanMessage(content=query)],
        "query": query,
        "user_id": user_id,
        "session_id": session_id,
        "run_id": str(uuid4()),
        "action": "search",  # Intent 会覆盖；不是识别结果
        "requirements": RequirementSchema(),
        "pending_question": None,
        "candidates": [], "source_status": {},
        "normalized_products": [], "price_results": [],
        "review_results": [], "price_status": "empty",
        "review_status": "empty", "price_error": None,
        "review_error": None, "comparison_result": {},
        "final_report": None, "run_status": "running",
    }
```

## 多轮与检查点

新查询清空业务字段，消息可以继续保留。澄清回复沿用原 run_id，服务层将回答追加到当前 query 或单独的需求补充中，保留已确认条件；随后重新进入 Intent / Requirement。不要继续读取 messages 第一条作为当前需求。

同一 session 只允许一个活跃运行。服务端建立 user_id → session_id → run_id 归属，thread_id 从这份映射取得。InMemorySaver 只适用于单进程开发，重启后明确失效。参见 [官方 Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。

`TypedDict` 不会执行运行时校验；HTTP 与工具边界使用 Pydantic。消息 reducer 的行为见 [官方 Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)。
