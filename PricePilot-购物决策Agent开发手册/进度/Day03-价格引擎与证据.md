# Day 3：价格引擎与证据

[上一阶段](Day02-商品标准化与同款识别.md) · [返回看板](../03-进度看板.md) · [下一阶段](Day04-评论分析与比较报告.md)

## 今天只解决什么

同一规格的报价能算出付款金额，并回答“为什么是这个金额、对谁有效、什么时候核验的”。

## 前置与阅读

Day 2 已分出同款组。完整阅读 [搜索与价格引擎](../app/ai/tool/搜索同款与价格引擎.md) 和 PriceQuote 合同。

## 未来要写的文件

price_calculator.py；price_node.py；Promotion/PriceQuote Schema；详情适配器中的优惠、库存、运费解析；价格规则测试。

## 按这个顺序实施

1. 先约定金额单位和舍入规则，再做加减；禁止 float 充当金额事实。
2. 收集优惠的资格、门槛基数、互斥和叠加顺序，保存证据。
3. 先实现无优惠、单券、券加运费，再实现已知互斥与叠加。
4. 用当前 buyer_context 区分已确认价、条件价和未知价。
5. 按 eligible + fresh + verified + 有货 + 费用完整筛选，再在同款内比较。
6. 对优胜报价重新获取详情，失效就重排；保存计算过程而不是只保存最低数字。
7. 设计 price_history 字段供 Day 5 落库；今天可先保存在运行输出中。

## 当天应该看到

演示商品标价 2999，店铺券减 100，平台券减 150，补贴减 300，已确认零运费且无额外税费。卡片写付款 2449，未来可能返现 20，预计成本 2429。若没有证明三项优惠可叠加，就不能输出 2449 为核验结果。

## 验收清单

- [ ] 工具文档全部价格案例得到预期结果。
- [ ] 运费未知不变成包邮，会员未知不享会员价。
- [ ] 过期券、无货和失效报价被移出当前最低价。
- [ ] 两个互斥优惠不同时扣减。
- [ ] 金额保留精度，负价或非法数值被拒绝。
- [ ] 优惠到期边界、规则缺失、刷新后变价均有用例。
- [ ] 展示采集范围，不声称全网最低。

当天交付至少八组计算记录，以及一张明细完整的报价卡。此阶段的价格核心用例不通过，不进入正式推荐与提醒。
## V2 新增的比较口径

Amazon 原币种报价单独展示。CNY 和 USD 不放进同一个 min；缺目的地运税的 Amazon 商品只能展示已知价格部分。资格未知优惠另列条件场景。

## 参考代码：2999 → 2449 → 2429（模块演示）

依赖工具章 price_calculator.py、Schema，以及 [代码使用章](../附录/参考代码使用与验证.md) 的 make_offer 演示工厂。放到 app/test/test_price.py。

```python
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from app.test.fixtures import make_offer
from app.ai.agent.multi_agent.schema.shopping_schema import Promotion
from app.ai.tool.price_calculator import calculate_quote

now = datetime.now(timezone.utc)
ids = ["store", "platform", "subsidy"]
amounts = ["100", "150", "300"]
promotions = [
    Promotion(
        promotion_id=name, amount=amount, eligibility="eligible",
        stackable_with=[other for other in ids if other != name],
        valid_until=now + timedelta(minutes=10), evidence_ids=["demo-" + name],
    )
    for name, amount in zip(ids, amounts)
]
offer = make_offer(now, promotions=promotions, estimated_cashback=Decimal("20"))
quote = calculate_quote(offer, now)
assert quote.payable_amount == Decimal("2449")
assert quote.estimated_net_cost == Decimal("2429")
assert set(quote.applied_promotions) == set(ids)
```

这是明确知道三项优惠互相允许叠加的样本。实际接口未给叠加规则时，不能照抄此样本把所有券加入 stackable_with。
