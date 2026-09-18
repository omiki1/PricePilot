# Day 4：评论分析与比较报告

[上一阶段](Day03-价格引擎与证据.md) · [返回看板](../03-进度看板.md) · [下一阶段](Day05-收藏历史与降价提醒.md)

## 今天只解决什么

价格可信之后，解释“哪个更适合我”，每项优缺点能追溯到实际评论样本。

## 前置与阅读

Day 3 价格用例通过。读 [节点说明](../app/ai/agent/multi_agent/node/节点实施说明.md)、[提示词](../app/ai/prompt/提示词与结构化输出.md)、[图编排](../app/ai/agent/multi_agent/graph/shopping_graph.md)。

## 未来要写的文件

review_fetch_tool.py；review_node.py；compare_node.py；reporter_node.py；ReviewAnalysis/ComparisonReport Schema；review_node.yaml 与 reporter_node.yaml；可选图分支改造。

## 按这个顺序实施

1. 为每款准备或获取评论样本，记录来源、实际数量和采样范围；演示评论照样标识。
2. 去重、过滤明显无信息内容，保留统计。评论很多时分批归纳，再按证据 ID 合并。
3. 模型输出优缺点主题和评论 ID，程序验证 ID 并统计提及数。
4. 将“通勤降噪”“眼镜佩戴舒适”等用户偏好与主题关联，分别写支持/冲突/未知。
5. 程序先过滤硬限制再排序，形成独立的价格榜与需求匹配推荐。
6. Reporter 只填写解释，不修改 quote_id、金额和排名。
7. 串行跑通后再决定是否并行 Price/Review。若并行，验证任一分支失败时能汇合且 Compare 只执行一次。

## 当天应该看到

A 适合通勤且价格在预算内；B 价格更低但佩戴证据不足；C 的舒适性样本较好但某方面存在不足。没有证据的降噪性能不能被模型写成确定事实。

## 验收清单

- [ ] 所有优缺点至少关联一个可查看的评论证据。
- [ ] “高频”有明确样本数、分母与去重口径。
- [ ] 无评论、少评论、重复评论能正确降级。
- [ ] 模型不能通过评论中的指令改变系统规则。
- [ ] 超预算商品单列，不伪装为预算内首选。
- [ ] 候选不足三款时如实展示。
- [ ] 同样的结构化输入得到同样排序；文字可以不同。

当天交付一份完整结构化报告与三条不同需求的比较结果。RAG 留到后续，今天不接向量库。
## V2 评论能力与卡片输出

Amazon/JD 搜索 API 不自动等于评论正文 API；先记录实际 review_text 能力。报告中加入图片、平台与普通/推广链接，数据不足就标记；不要用别的平台商品图或评论冒充本商品证据。

## 参考代码：同口径合格报价筛选（模块参考）

目标：compare_node.py 中的确定性帮助函数。输入 offers 必须已经通过 Normalize 的严格规格核验；本函数只负责报价关联、口径过滤和每产品最低价，不替代 SKU 判定或偏好推荐。

```python
from datetime import datetime


def select_quotes(offers, quotes, *, currency: str, destination: str,
                  buyer_context_hash: str, data_mode: str, now: datetime):
    by_id = {offer.offer_id: offer for offer in offers}
    best_by_product = {}
    for quote in quotes:
        offer = by_id.get(quote.offer_id)
        if offer is None or quote.product_id != offer.product_id:
            continue
        if offer.currency != currency or quote.currency != currency:
            continue
        if (offer.destination != destination
                or offer.buyer_context_hash != buyer_context_hash
                or offer.data_mode != data_mode):
            continue
        if (quote.verification_level != "verified" or quote.freshness != "fresh"
                or quote.payable_amount is None or now >= quote.valid_until
                or offer.stock_status != "in_stock"):
            continue
        old = best_by_product.get(offer.product_id)
        if old is None or (quote.payable_amount, quote.offer_id) < (
            old.payable_amount, old.offer_id
        ):
            best_by_product[offer.product_id] = quote
    return sorted(best_by_product.values(),
                  key=lambda q: (q.payable_amount, q.product_id, q.offer_id))
```

调用方再按用户预算和硬限制过滤，结合有证据的偏好排序。比较资格为空、目的地不同或币种不同的卡片仍可另栏展示，不叫“更便宜”。
