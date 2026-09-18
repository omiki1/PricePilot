# Amazon + 京东接入：先 Tool，后 MCP

首批目标固定为 Amazon 与京东；淘宝下一阶段，拼多多再后，闲鱼因成色/保修/真伪差异最后。优先官方或联盟 API，不在第一版写登录绕过、浏览器自动购买或反爬对抗。

## 接入前真正要确认什么

| 来源 | 官方入口与已确认能力 | 项目还需核对 |
|---|---|---|
| Amazon | Creators API 提供 SearchItems、GetItems 与图片等资源 | 账号审核、目标 marketplace、已开通权限、实际可得报价字段 |
| 京东 | 京东开放平台列出联盟商品/优惠信息查询与转链流程 | 应用权限、签名方式、配额与当前返回字段 |

Amazon 注册与市场权限见 [注册说明](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/onboarding/register-for-creators-api) 和 [FAQ](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/frequently-asked-questions)；操作与资源见 [API Reference](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference)。京东资料见 [官方联盟接入页](https://jos.jd.com/jdunion)。本手册不伪造 SDK 方法、HTTP 签名和已获批权限。

返回评分不等于返回100～300条评论正文。评论能力必须单独验证；无授权正文来源时 Review 返回 unavailable，或使用明确的自建演示评论。

## Amazon 对这份产品设计的实际影响

截至2026-09-17，本次核对的 Amazon.com 联盟政策要求价格追踪/提醒得到另行同意；它描述的是站点功能限制，不能仅关闭 Amazon 单张卡的提醒就认为整个带京东提醒的站点已满足要求。政策还限制内容分析利用、缓存与图片存储，并规定比较展示和评论使用条件。见 [官方 Program Policies](https://affiliate-program.amazon.com/help/operating/policies)。

因此本项目区分三个运行配置：

- `demo_full`：自建虚构数据，全功能学习，不调用真实商品 API。
- `live_showcase`：按已批准用途展示/跳转，关闭站点级追踪、价格历史和提醒；数据分析与跨平台比较也必须在授权用途内。
- `live_full`：完整真实比较/历史/提醒；只有相关来源和站点用途均取得必要许可后启用。

Amazon 商品信息必须关联其对应 Amazon 链接；图片用获准 URL，不默认长期下载。比较模式若来源要求附带其他成色报价，单独展示，绝不混入全新同款排名。真实上线按实际市场的条款重新核对，本章不替代账号审批。

## 地区与币种

京东以 CN/CNY 为起点；Amazon 的 US/USD 只是示例配置，不替用户选定真实站点。前端允许并列显示两地候选，但只有同规格、同目的地、同币种且费用完整的报价才进入同一最低价榜。第一版不做汇率换算后的“跨境到手最低价”。

## 参考代码：适配器合同与超时降级（模块参考）

目标：`app/ai/tool/product_search_tool.py`。适配器名称固定为 amazon 或 jd；实现时把官方 SDK 返回映射到 Offer。下面的类是本项目接口，不是官方 SDK。

```python
import asyncio
from typing import Protocol
from pydantic import BaseModel, Field
from app.ai.agent.multi_agent.schema.shopping_schema import Offer

class SourceCapabilities(BaseModel):
    search: bool = False
    details: bool = False
    review_text: bool = False
    images: bool = False
    affiliate_links: bool = False
    analysis_allowed: bool = False
    comparison_allowed: bool = False
    history_allowed: bool = False
    tracking_allowed: bool = False
    approval_refs: list[str] = Field(default_factory=list)

class ProductSource(Protocol):
    name: str
    capabilities: SourceCapabilities
    async def search(self, keyword: str, marketplace: str) -> list[Offer]: ...
    async def get_product(self, source_id: str, marketplace: str) -> Offer: ...

async def search_sources(sources, keyword: str, markets: dict[str, str]):
    async def one(source):
        if not source.capabilities.search:
            return source.name, [], "not_configured"
        if not source.capabilities.analysis_allowed:
            return source.name, [], "purpose_not_enabled"
        market = markets.get(source.name)
        if not market:
            return source.name, [], "marketplace_required"
        try:
            offers = await asyncio.wait_for(source.search(keyword, market), 8)
            return source.name, offers, "completed"
        except TimeoutError:
            return source.name, [], "timeout"
        except Exception:
            # 在服务日志记录受控错误码；不将密钥/原始响应推给浏览器。
            return source.name, [], "failed"
    rows = await asyncio.gather(*(one(source) for source in sources))
    return {
        "candidates": [offer for _, offers, _ in rows for offer in offers],
        "source_status": {name: status for name, _, status in rows},
    }
```

这段完成多来源调用与失败降级，未实现真实认证和字段映射。凭证只在后端配置，不写进提示词、前端或示例。demo adapter 应使用自建商品、图片占位和明确的 data_mode=demo。

## Tool 与 MCP 的边界

节点可以直接调上述函数，也可以包装为 LangChain Tool。MCP 只是后续标准化发布 search_products/get_product/compare_price/track_price 的接口，不会提供平台账号、数据权限或自动解决优惠核验。

## 接入验收记录

记录平台、marketplace、批准用途、官方文档版本、可用能力、缺失字段、成功样本及限流错误。只获得 API 密钥不代表已获准所有展示、分析、保存和提醒场景。
