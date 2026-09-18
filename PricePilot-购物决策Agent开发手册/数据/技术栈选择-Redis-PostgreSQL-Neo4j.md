# 你已掌握的技术栈：放在合适的位置

你补充说明会一点 Redis、PostgreSQL、Neo4j。本手册把它们视为可使用的已有能力；参考项目暂未展示对应实现，并不表示你不会。

## 推荐选择

| 技术 | 本项目位置 | 第一版安排 |
|---|---|---|
| MySQL | 商品、报价历史、收藏、通知日志 | 默认主库，最接近参考项目 |
| PostgreSQL | 可替换 MySQL 的业务主库 | 二选一；若想练 PG，从 Day 1 就选定并沿用 |
| Redis | 共享报价缓存、来源限流、短期运行事件 | 核心闭环通过后再加；数据始终有来源与过期时间 |
| Neo4j | 品牌—系列—型号—别名—规格—适用场景的关系查询 | 第二版；先以明确的查询需求证明必要性 |

**建议路线 A：** MySQL + 内存检查点 → 完成六阶段 → Redis 缓存 → 按需要评估 Neo4j。

**可选路线 B：** PostgreSQL 作为唯一业务库 → 完成六阶段 → 验证并引入兼容的持久化检查点 → Redis → Neo4j。

两条路线的业务规则完全相同，主要变化是数据库连接、迁移与持久化适配。不要同时维护 MySQL 和 PostgreSQL 的同一份商品业务数据。

## Redis 怎么加入

先记录来源查询耗时与重复次数，有重复请求压力后再加缓存。缓存键至少覆盖 source、SKU、地区、资格口径与规则版本；私有会员价不能被其他用户共用。

保留原 observed_at 和 valid_until，缓存命中时不能刷新成“刚刚核验”。缓存 TTL 不超过价格有效期，过期回源。缓存失效或 Redis 暂时不可用时，可以限流后直接查来源；数据库仍是业务事实存储。

多工作进程的任务排他优先用数据库任务认领与唯一约束。若加 Redis 锁，需设计过期、续租和持有者校验，通知去重仍由数据库保证。Redis 锁不能代替业务幂等。

## PostgreSQL 怎么替换

把 product_repository 作为数据库访问边界，节点继续读写相同字段合同。更换驱动、连接管理和迁移方式，确认定点金额、时间、唯一约束、事务与并发认领语义，重跑全部价格历史和通知测试。

如果以后持久化 LangGraph 检查点，单独检查所选适配器与实际 LangGraph 版本的兼容性、初始化方式和迁移要求。业务表能持久化不代表图就会自动恢复。

## Neo4j 什么时候有价值

当你已经有多品类、复杂型号别名、系列/代际/配件关系，且确实需要沿关系查询时再加入。先写出三条具体问题，例如“同系列有哪些明确升级代际”“这个别名指向哪款标准型号”“某型号有哪些已确认兼容配件”。

每条关系都带来源、时间和确认状态。相似/同系列关系不能变成 same SKU；图里距离近也不意味着可以直接比较最低价。到手价计算与通知事务仍由程序和主库负责。

知识图谱的数据量和关系维护成本往往比安装数据库更重要。只有几款耳机时，用主库别名表已经足够。

## 参考代码 1：Redis 报价缓存（模块片段）

用于获准缓存的报价；调用方提供真实的 valid_until 与 source_ttl_limit。只有 verified 核验结果才缓存为可用报价。Redis 故障可回源，缓存不会改变业务数据库的最终事实。

```python
import hashlib
import json
from datetime import datetime


def cache_quote(redis_client, offer, quote, now: datetime, source_ttl_limit: int):
    if quote.offer_id != offer.offer_id or quote.currency != offer.currency:
        raise ValueError("缓存报价与商品来源不一致")
    if quote.verification_level != "verified":
        return False
    ttl = min(int((quote.valid_until - now).total_seconds()), source_ttl_limit, 900)
    if ttl <= 0:
        return False
    context = {
        "source": offer.platform, "marketplace": offer.marketplace,
        "sku": offer.offer_id, "destination": offer.destination,
        "currency": offer.currency, "buyer": offer.buyer_context_hash,
        "mode": offer.data_mode, "rule_version": "fixed-discount-v1",
    }
    digest = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    redis_client.setex("quote:" + digest, ttl, quote.model_dump_json())
    return True
```

此例依赖 redis-py 客户端和统一 Offer/PriceQuote；没有连接凭证。不能用默认TTL覆盖更严格的来源许可；不允许持久保存的内容也不能通过 Redis 绕过。

## 参考代码 2：PostgreSQL 精确金额（SQL片段）

仅在选择 PG 为业务主库时采用；这是演示报价表的精度与唯一约束片段。完整字段仍以数据库章节为准。numeric 支持精确十进制金额，参见 [官方数值类型](https://www.postgresql.org/docs/current/datatype-numeric.html)。

```sql
CREATE TABLE demo_price_history (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    offer_id TEXT NOT NULL,
    sample_batch TEXT NOT NULL,
    payable_amount NUMERIC(18, 2),
    currency CHAR(3) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    UNIQUE (offer_id, sample_batch)
);
```

入口仍需拒绝非有限金额；数据库精度不能代替领域模型校验。

## 参考代码 3：Neo4j 关系查询（Cypher片段）

先用关系表示系列和别名，不直接根据关系推断严格同款。参数通过驱动绑定，不拼接用户输入。以下假定 Series、Product、Alias 已有数据和来源属性。

```cypher
MATCH (a:Alias {name: $alias})-[:REFERS_TO]->(p:Product)
OPTIONAL MATCH (p)-[:BELONGS_TO]->(s:Series)
RETURN p.product_id AS product_id,
       p.model AS model,
       s.name AS series,
       p.evidence_ids AS evidence_ids
LIMIT 20
```

关系返回的候选还要走 ProductIdentity 硬规则。Redis、PG、Neo4j 三段是各自的使用示例，不要求在六阶段里全部接入。
