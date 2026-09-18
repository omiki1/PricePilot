# Day 5：收藏、历史与降价提醒

[上一阶段](Day04-评论分析与比较报告.md) · [返回看板](../03-进度看板.md) · [下一阶段](Day06-页面联调与交付.md)

## 今天只解决什么

把用户关注的商品持续保存下来，定时用相同口径核验价格，达阈值时生成一次可追踪的通知。

## 前置与阅读

价格规则稳定。完整阅读 [数据库与监控](../数据/数据库与降价监控.md)。确认使用 Day 1 选定的 MySQL 或 PostgreSQL，不临时增加第二套主库。

## 未来要写的文件

product_repository.py；watch_router.py；price_monitor.py；send_email_tool.py 的业务包装；表结构迁移说明；监控与去重测试。

## 按这个顺序实施

1. 落地商品、来源报价、证据、价格历史、收藏、通知日志等逻辑表及唯一约束。
2. 写明确的存取操作：保存快照、列自己的收藏、更新阈值、认领任务、登记通知；不用模型执行任意 SQL。
3. 实现只收藏与开启提醒两种状态，用户阈值采用付款金额。
4. 先手动运行一个监控项，确认复采、核规格、算金额、落库的完整链路。
5. 加入 armed/generation 与通知日志，再模拟重复执行和发送失败。
6. 在测试模式生成通知记录；真实发信先向自己的测试邮箱发送一封。
7. 确认站点配置和来源权限允许后，单实例任务固定周期运行；与网页进程分开，避免多个 worker 重复调度。

## 最小价格序列测试

目标 1800，采样依次为 1900 → 1799 → 1750 → 1850 → 1780。预期在 1799 和最后 1780 各生成一次提醒；1750 时不重复；1850 时重新布防。过期/资格未知价格不参与这一序列。

## 验收清单

- [ ] 刷新页面和重启服务后，收藏与价格历史还在。
- [ ] 同一采样或同一触发代次重复执行，不重复登记通知。
- [ ] 发信失败重试同一记录；不确定投递状态有明确处理。
- [ ] 不匹配 SKU、无库存、资格未知不触发。
- [ ] 暂停/删除后不再产生新提醒。
- [ ] 用户不能修改别人的收藏或通知地址。
- [ ] 历史不足时不输出“历史低价”。

当天交付数据库记录样例、一次测试提醒和上述价格序列记录。没有邮件配置时可以先验收模拟通知，但“真实邮件发送”必须保留未完成状态。
## V2 必须先验证的能力

真实 Amazon 接入与站点提醒功能的组合不能默认放行，见 [平台接入](../app/ai/tool/Amazon与京东接入.md)。demo_full 只用自建样本和模拟通知；live_showcase 全站不启用价格历史/提醒；live_full 在实际许可范围内运行。

## 参考代码：价格序列只触发两次（模块演示）

依赖统一价格引擎、演示工厂和数据库章节的 advance_watch；目标 app/test/test_monitor.py。本例只验证状态机，不发送邮件。

```python
from datetime import datetime, timezone
from decimal import Decimal
from app.test.fixtures import make_offer
from app.ai.tool.price_calculator import calculate_quote
from app.jobs.price_monitor import WatchMemory, advance_watch

now = datetime.now(timezone.utc)
watch = WatchMemory("demo-watch", Decimal("1800"), "CNY")
notifications = []
for price in ("1900", "1799", "1750", "1850", "1780"):
    offer = make_offer(now, item_price=price)
    quote = calculate_quote(offer, now)
    watch, event = advance_watch(watch, quote, now, True, True)
    if event:
        notifications.append(event["dedup_key"])
assert notifications == ["demo-watch:0", "demo-watch:1"]
assert watch.armed is False
```

并发和数据库事务要另外验收。内存序列通过不代表 SMTP 已验证，也不能保证生产环境恰好发送一次。
