"""报价、评论证据和商品卡片的数据结构。"""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# 金额统一类型：非负、有限、禁止 NaN/Inf
Money = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Currency = Literal["CNY", "USD"]

# 平台使用字符串，兼容 Shopify 等来源。
Platform = Literal["shopify", "jd", "amazon"]
DataMode = Literal["demo", "live"]
StockStatus = Literal["in_stock", "out_of_stock", "unknown"]
Eligibility = Literal["eligible", "ineligible", "unknown"]


class StrictModel(BaseModel):
    """所有合同的基类：禁止未声明字段。"""

    model_config = ConfigDict(extra="forbid")


class ProductIdentity(StrictModel):
    """商品的严格身份：同款判断的输入。"""

    brand: str | None = None
    model: str | None = None
    generation: str | None = None
    variant: str | None = None
    storage: str | None = None
    color: str | None = None
    region: str | None = None
    condition: str | None = None
    bundle: str | None = None
    warranty: str | None = None
    # 每个硬字段对应的证据 ID；没有证据的字段在 match_identity 里会判 uncertain
    field_evidence: dict[str, list[str]] = Field(default_factory=dict)


class Promotion(StrictModel):
    """一条优惠（券/补贴/立减）。资格、门槛、互斥关系必须由来源适配器先确认。"""

    promotion_id: str
    description: str = ""
    amount: Money                                   # 定额优惠金额
    min_spend: Money = Decimal("0")                 # 原价门槛（对商品标价，不含运费）
    eligibility: Eligibility = "unknown"
    exclusive_group: str | None = None              # 同组互斥（如 store / platform）
    stackable_with: list[str] = Field(default_factory=list)   # 双向声明才可叠加
    valid_until: AwareDatetime
    evidence_ids: list[str] = Field(default_factory=list)


class Offer(StrictModel):
    """某个平台或店铺对指定商品规格的一次报价。"""

    offer_id: str
    product_id: str
    source_product_id: str | None = None
    platform: Platform
    marketplace: str = ""
    title: str = ""
    identity: ProductIdentity
    product_url: str = ""
    # 缺图时留空；推广链接仅填写已获准的来源。
    image_url: str | None = None
    affiliate_url: str | None = None
    currency: Currency
    destination: str = ""
    buyer_context_hash: str = ""
    item_price: Money
    shipping: Money | None = None
    tax: Money | None = None
    stock_status: StockStatus = "unknown"
    eligibility: Eligibility = "unknown"
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    promotions: list[Promotion] = Field(default_factory=list)
    estimated_cashback: Money = Decimal("0")
    evidence_ids: list[str] = Field(default_factory=list)
    data_mode: DataMode = "demo"


class PriceQuote(StrictModel):
    """一次价格计算的完整结果 —— 全项目「金额口径」的唯一载体。"""

    quote_id: str
    offer_id: str
    product_id: str
    currency: Currency
    payable_amount: Money | None
    estimated_net_cost: Money | None
    applied_promotions: list[str] = Field(default_factory=list)
    excluded_promotions: dict[str, str] = Field(default_factory=dict)
    verification_level: Literal["verified", "unverified"]
    freshness: Literal["fresh", "stale", "unavailable"]
    verified_at: AwareDatetime
    valid_until: AwareDatetime
    reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ReviewTheme(StrictModel):
    """一个评论主题（优点或缺点）及其证据。"""

    label: str
    review_ids: list[str]                      # 必须回指真实评论 ID
    inference: bool = False                    # True = 模型推断，非评论原话


class ReviewSample(StrictModel):
    """一条原始评论样本 —— 外部来源文本，一律按不可信输入处理。"""

    review_id: str
    product_id: str
    text: str = ""
    rating: float | None = None                # 未知 = None，不是 0
    author: str = ""
    created_at: AwareDatetime | None = None
    source: str = ""                           # 来源平台/渠道，用于标注与溯源
    data_mode: DataMode = "demo"               # 演示样本必须能被识别出来（验收 U01）
    # 采集时是否已确认有权使用该来源的评论正文；False 的样本不许进报告
    usage_permitted: bool = True


class ReviewAnalysis(StrictModel):
    """一款商品的评论分析结果。"""

    product_id: str
    sample_size: int = Field(ge=0)             # 去重后的实际样本数（「高频」必须有分母）
    pros: list[ReviewTheme] = Field(default_factory=list)
    cons: list[ReviewTheme] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ProductCard(StrictModel):
    """给前端渲染的商品卡；金额直接来自 PriceQuote，前端不二次计算。"""

    product_id: str
    offer_id: str
    title: str
    platform: str
    marketplace: str = ""
    image_url: str | None = None
    product_url: str = ""
    purchase_url: str = ""
    currency: Currency
    original_price: Money
    payable_amount: Money | None
    estimated_net_cost: Money | None
    data_mode: DataMode = "demo"
    price_label: str = ""                      # 如「已核验付款金额」「运费未知」
    comparison_eligible: bool = False          # 比较资格由后端定，前端不参与判断
    tracking_enabled: bool = False
    checked_at: AwareDatetime


__all__ = [
    "Money", "Currency", "Platform", "DataMode", "StockStatus", "Eligibility",
    "StrictModel", "ProductIdentity", "Promotion", "Offer", "PriceQuote",
    "ReviewSample", "ReviewTheme", "ReviewAnalysis", "ProductCard",
]
