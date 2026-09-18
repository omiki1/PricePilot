# ShoppingGraph：Intent 与 Requirement 分离

主线为 START → Manager → Intent → Requirement → Search → Normalize → Price / Review → Compare → Reporter → END。Manager 保持入口调度职责，固定阶段用图的边表达，不额外绕回 Manager 重复调度。

## 四种动作如何落地

- search：按需求搜 Amazon 与京东候选。
- compare：优先解析用户指定的 2～3 个链接；不足则澄清，不任意替换目标。
- price：取得指定商品，再找严格同款报价；非同款只能作为另列建议。
- track：若没有明确产品/阈值先澄清；明确后输出监控配置确认卡，由 `/watches` 接口保存。LLM 识别出 track 不自动订阅邮件。

普通查价不是定时任务；定时监控在 jobs 中执行。真实 Amazon 相关配置必须经过 [来源能力门槛](../../../tool/Amazon与京东接入.md)，未获准时只有演示监控。

## 参考代码：构图与双分支汇合（模块参考）

目标：`app/ai/agent/multi_agent/graph/shopping_graph.py`。参数 nodes 是已实现节点函数的映射，不是框架内置对象。

```python
from langgraph.graph import StateGraph, START, END
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState

def build_graph(nodes: dict, checkpointer):
    builder = StateGraph(ShoppingState)
    required = [
        "manager", "intent", "requirement", "search", "normalize",
        "price", "review", "compare", "reporter", "track_config",
    ]
    for name in required:
        builder.add_node(name, nodes[name])
    builder.add_edge(START, "manager")
    builder.add_edge("manager", "intent")
    builder.add_edge("intent", "requirement")

    def next_after_requirement(state):
        if state.get("run_status") == "waiting_input":
            return "wait"
        return "track" if state["action"] == "track" else "search"

    builder.add_conditional_edges(
        "requirement", next_after_requirement,
        {"wait": END, "track": "track_config", "search": "search"},
    )
    builder.add_edge("track_config", END)
    builder.add_conditional_edges(
        "search", lambda s: "found" if s.get("candidates") else "empty",
        {"found": "normalize", "empty": "reporter"},
    )
    builder.add_edge("normalize", "price")
    builder.add_edge("normalize", "review")
    # 等待两个前驱都完成，Compare 执行一次。
    builder.add_edge(["price", "review"], "compare")
    builder.add_edge("compare", "reporter")
    builder.add_edge("reporter", END)
    return builder.compile(checkpointer=checkpointer)
```

多前驱 `add_edge` 的等待行为见 [官方 API](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_edge)。Price / Review 需捕获可预期的超时并返回各自 failed 状态，否则异常会直接中断图。Reporter 兼容无候选路径。

## 先串行后并行

Day 1～3 先用 Normalize → Price → Review → Compare；Day 4 再替换为上面的两个分支及汇合边。替换时删除串行边，不同时保留两套路径。

第一次没有必要实现动态子图或无限 Agent 自主规划。每个运行设置节点超时、有限重试、最大跳转数；用户取消后结果不能继续覆盖新运行。

## 本例未实现什么

节点内部逻辑、用户认证、run 管理、错误事件持久化与 checkpointer 生命周期由对应章节实现。本例展示真实构图方式，但不声称复制这一段就得到了完整应用。
