# Day 2：商品标准化与同款识别

[上一阶段](Day01-状态意图与搜索.md) · [返回看板](../03-进度看板.md) · [下一阶段](Day03-价格引擎与证据.md)

## 今天只解决什么

让程序明确知道哪些报价是同一款、哪些只是替代产品、哪些还无法确认。没有这个门槛，便宜的二手或旧款会污染最低价。

## 前置与阅读

Day 1 的候选已经带来源和时间。读 [Schema](../app/ai/agent/multi_agent/schema/结构化数据合同.md) 与 [工具说明的同款规则](../app/ai/tool/搜索同款与价格引擎.md)。

## 未来要写的文件

normalize_node.py；ProductIdentity 与匹配结果 Schema；normalize_node.yaml；product_detail_tool.py；同款规则测试。

## 按这个顺序实施

1. 定义耳机必要字段：品牌、完整型号/代际、子型号、地区、成色、套装、保修与用户要求的颜色。
2. 建小型品牌/型号别名表；明确规则可处理的先用规则，不让模型重复猜测。
3. 模型提取其余字段并返回证据 ID。标题缺失时去详情补充。
4. 编写硬字段比较规则，输出 same / different / uncertain 和理由。
5. 形成“标准产品 → 多个平台/店铺报价”的结构；其他型号作为独立产品。
6. 展示不合并原因，允许后续补充证据后重新判断。

## 最小测试集

| 比较对象 | 预期 |
|---|---|
| 已确认别名指向同型号，其他规格一致 | same |
| 同系列不同代 | different |
| 全新与官翻 | different |
| 大陆版与其他地区版 | different |
| 单机与赠配件套装 | different |
| 用户限定黑色，而报价是白色 | different |
| 只有品牌与模糊标题，型号不全 | uncertain |
| 标题写全新但详情写二手 | uncertain，并指出冲突 |

## 验收清单

- [ ] 每个 same 组有完整可追溯的硬字段。
- [ ] 低价旧款、二手和套餐不会混入指定商品组。
- [ ] uncertain 不直接丢弃，也不参加已核验同款最低价。
- [ ] 同一批输入重复运行，硬字段判定保持稳定。
- [ ] 没有足够证据的模型“高置信度”不能推翻硬规则。

当天交付一份匹配样例表和实际分组输出。如果模型抽取不稳定，减少支持型号并增加规则，不增加更多平台。
## V2 平台与地区差异

Amazon 的 ASIN 和京东商品/SKU ID 都作为来源标识，不相互覆盖。相同外观但销售地区、套装或保修不同仍不能直接同款比价。商品图片只能辅助展示，不能仅凭图片判定同款。

## 参考代码：同款边界回归（模块演示）

依赖 Schema 与工具章 sku_matcher.py；数据为自建演示。目标 app/test/test_sku.py。

```python
from app.ai.agent.multi_agent.schema.shopping_schema import ProductIdentity
from app.ai.tool.sku_matcher import match_identity, HARD_FIELDS

fields = dict(
    brand="DemoAudio", model="Commute One", generation="1",
    variant="standard", storage="not_applicable", color="black",
    region="CN", condition="new", bundle="standard", warranty="CN-1year",
)
evidence = {key: ["fixture-evidence-1"] for key in HARD_FIELDS}
a = ProductIdentity(**fields, field_evidence=evidence)
b = ProductIdentity(**fields, field_evidence=evidence)
assert match_identity(a, b)[0] == "same"
assert match_identity(a, b.model_copy(update={"condition": "used"}))[0] == "different"
assert match_identity(a, b.model_copy(update={"region": None}))[0] == "uncertain"
assert match_identity(a, b.model_copy(update={"field_evidence": {}}))[0] == "uncertain"
```

实际抽取字段需由来源证据支撑；fixture-evidence-1 只是测试标识，不表示平台证据。
