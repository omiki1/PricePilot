# Day 1：状态、Intent/Requirement 与双来源搜索

[返回看板](../03-进度看板.md) · [下一阶段](Day02-商品标准化与同款识别.md)

## 今天只解决什么

输入一段购物需求或受支持链接，得到有来源的候选；需要补充条件时能正常等待；两个会话互不干扰。

## 前置与阅读

先读 [产品边界](../00-产品边界与主线.md)、[State](../app/ai/agent/multi_agent/state/shopping_state.md)、[Schema](../app/ai/agent/multi_agent/schema/结构化数据合同.md)。选 MySQL 或 PostgreSQL 作为唯一业务主库，今天先定合同，Day 5 完成持久化。

## 未来要写的文件

app/main.py；shopping_state.py；shopping_graph.py；manager_node.py；intent_node.py；requirement_node.py；search_node.py；购物需求 Schema；intent_node.yaml、requirement_node.yaml；product_search_tool.py 与 product_detail_tool.py；chat_router.py 的最薄运行与事件接口。

## 按这个顺序实施

1. 新建购物项目，按参考项目层级建立目录。只迁移模型与 YAML 加载等必要能力，先不带语音和面试题库。
2. 记录当前环境版本，确认模型结构化输出可用。
3. 定义 session_id、run_id、当前 query、requirements、pending_question 和 candidates。
4. 先写 Intent 四类动作识别，再写 Requirement 的字段校验，准备预算明确、预算模糊、链接输入三类案例。
5. 建演示来源适配器：约 10～15 个报价，覆盖 3 款耳机、多个店铺、缺字段与失败情况；每条带演示标记。
6. 串起 Manager → Intent → Requirement → Search，输出阶段事件与候选列表。澄清后合并原需求，不丢通勤等条件。
7. 分别列出 Amazon 与京东的可用渠道、凭证、地区和用途能力缺口。若已具备接入条件，验证一次关键词搜索和一次详情查询。

## 当天应该看到

“预算 2000，通勤，戴眼镜”被解析成头戴式降噪耳机场景（若用户未明确佩戴形式，应询问或明确待确认），预算 2000 为硬上限，会员资格未知。候选包含来源、原始标题、规格线索、时间；今天不宣称已完成最低价。

## 验收清单

- [ ] 当前输入读自 query，第二条消息不会继续分析第一条需求。
- [ ] 预算不明确时给出一次必要澄清，回答后继续。
- [ ] 无结果、来源超时都能结束，前端不永久加载。
- [ ] 两个 session 的需求与候选相互隔离。
- [ ] 重复 client_request_id 不重复创建运行。
- [ ] 所有样本明确是演示数据；真实来源状态另行登记。

保留三次运行的输入、结构化意图与候选输出，作为后续回归基线。来源接不通可以进入 Day 2，但 M7/M8 继续未完成。
## V2 新增的当天门槛

Amazon 和京东都要注册为来源，逐项记录 search/details/images/affiliate_links/review_text 能力，未接通显示 not_configured。没有用户给定 Amazon marketplace 时，不猜测真实站点；演示模式可使用明确虚构数据。先 Tool，暂不做 MCP。

## 参考代码：动作和条件分别验证（模块演示）

依赖统一 Schema，可放到 app/test/test_intent_contract.py。这里只验证合同，不代表已经验证模型理解能力；模型节点示例见节点章。

```python
from app.ai.agent.multi_agent.schema.shopping_schema import (
    IntentSchema, RequirementSchema,
)

intent = IntentSchema(action="search", reason="用户希望寻找耳机候选")
requirements = RequirementSchema(
    budget_max="2000.00", currency="CNY",
    use_cases=["通勤"], requirements=["降噪", "眼镜佩戴舒适"],
    avoid=["夹头"], destination="CN-示例地区",
)
assert intent.action == "search"
assert str(requirements.budget_max) == "2000.00"
assert requirements.target_price is None
for action in ("search", "compare", "price", "track"):
    assert IntentSchema(action=action, reason="合同样例").action == action
```
