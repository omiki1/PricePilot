# PricePilot V2：AI 购物决策 Agent＋可验证到手价比较

根据第二份需求材料更新，日期2026-09-17。本文件夹仍是开发手册；每篇 Markdown 都附对应参考代码，不生成或改动你的应用项目。

**主线：用户需求/链接 → Intent动作识别 → Requirement条件提取 → Amazon＋京东搜索 → SKU归一 → 价格/评论 → A/B/C比较 → 聊天＋商品卡＋比较页 → 收藏与获准场景下的价格提醒。**

## V2 新增与调整

- Intent 和 Requirement 分开；覆盖找商品、比较、查价、监控四类动作。
- 首批目标明确为 Amazon＋京东；优先官方/联盟 API，先 Tool 后 MCP。
- 商品模型加入 image_url、product_url、affiliate_url 与后端选择的 purchase_url。
- 付款金额与返现后预计成本分开；币种/收货地/规格不同的报价分组展示。
- 保留六阶段计划与原项目的 app/ai/agent/multi_agent 目录风格。
- 每章给出代码用途、依赖、放置位置和未实现边界。

真实平台权限与数据可用性没有在本次工作中申请或验证。Amazon 相关使用条件见 [平台接入](app/ai/tool/Amazon与京东接入.md)；完整演示和真实上线分别验收。

## 阅读顺序

1. [产品范围](00-产品边界与主线.md) → [参考项目迁移](01-参考项目与技术迁移.md)。
2. [目录地图](02-目录地图与文件职责.md) → [参考代码使用说明](附录/参考代码使用与验证.md)。
3. [进度看板](03-进度看板.md) → [Day 1](进度/Day01-状态意图与搜索.md)。
4. 编写模块前先读 [统一 Schema](app/ai/agent/multi_agent/schema/结构化数据合同.md)，不要让各章节字段各自演化。
5. 最后执行 [验收与演示](验收/01-验收用例与演示脚本.md)。

## 模块索引

| 内容 | 文档 |
|---|---|
| 应用启动 | [main](app/main.md) |
| 状态与图 | [State](app/ai/agent/multi_agent/state/shopping_state.md)、[Graph](app/ai/agent/multi_agent/graph/shopping_graph.md) |
| 节点 | [节点职责与示例](app/ai/agent/multi_agent/node/节点实施说明.md) |
| 模型与提示词 | [模型](app/ai/model/模型调用约定.md)、[YAML](app/ai/prompt/提示词与结构化输出.md) |
| 数据来源与价格 | [Amazon/JD](app/ai/tool/Amazon与京东接入.md)、[价格与同款](app/ai/tool/搜索同款与价格引擎.md) |
| API与商品卡 | [SSE](app/web/chat_router/接口与SSE协议.md)、[前端](app/html/页面与交互说明.md) |
| 存储与技术选择 | [数据库/监控](数据/数据库与降价监控.md)、[Redis/PG/Neo4j](数据/技术栈选择-Redis-PostgreSQL-Neo4j.md) |
| 图与后续路线 | [参考图](参考图/01-流程与页面草图.md)、[资料](附录/资料与后续路线.md) |

## 参考代码：先理解一次用户输入（独立演示）

仅用 Python 标准库，可单独运行；这是手工准备的需求示例，不伪装为模型提取或真实搜索。

```python
from decimal import Decimal

request = {
    "action": "search",
    "query": "预算2000，通勤戴眼镜，希望头戴式降噪耳机",
    "budget_max": Decimal("2000.00"),
    "currency": "CNY",
    "requirements": ["降噪", "眼镜佩戴舒适"],
    "avoid": ["夹头"],
    "platforms": ["amazon", "jd"],
    "data_mode": "demo",
}
assert request["budget_max"] == Decimal("2000.00")
assert request["platforms"] == ["amazon", "jd"]
print(request["action"], request["currency"], request["data_mode"])
```

六天指六个验收阶段，时间不足就按阶段继续，不跳过价格与同款核验。示例中的商品、价格、评论均为自建演示数据，不是实时行情。
