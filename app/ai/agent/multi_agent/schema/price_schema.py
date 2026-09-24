"""B · 决策引擎 —— 金额与证据类合同（主笔：B）

为什么单独建这个文件，而不是直接写进 `shopping_schema.py`：
    `shopping_schema.py` 由 A 主笔并持续改动。按三人协作约定「不与他人共改同一文件」，
    B 的合同落在这里，避免每次合并都冲突。
    手册 S4-4 里这几份合同的归属是 B，`Offer` / `ProductIdentity` 属 A；
    A 冻结后，本文件只需把这两个类改成 `from ...shopping_schema import ...`，
    字段名与类型保持不变，消费方代码零改动。

金额铁律（违反任何一条即视为 bug）：
    1. 金额一律 Decimal，禁止 float 充当金额事实。
    2. 未知就是 None，不是 0；0 的语义是「免费」，用它表示未知会误导。
    3. 付款金额与返现后成本分两个字段，界面不得混用。
    4. 演示数据必须带 data_mode="demo"。
"""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# 金额统一类型：非负、有限、禁止 NaN/Inf
Money = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Currency = Literal["CNY", "USD"]

# 检索实际走 Shopify；手册原写 Literal["jd","amazon"]，不放宽会把 Shopify 数据全部拦掉。
Platform = Literal["shopify", "jd", "amazon"]
DataMode = Literal["demo", "live"]
StockStatus = Literal["in_stock", "out_of_stock", "unknown"]
Eligibility = Literal["eligible", "ineligible", "unknown"]


class StrictModel(BaseModel):
    """所有合同的基类：禁止未声明字段。

    extra="forbid" 的价值：谁写错了字段名（如 payble_amount）会立即报错，
    而不是被静默忽略，几小时后表现为「价格怎么是空的」。
    """

    model_config = ConfigDict(extra="forbid")


class ProductIdentity(StrictModel):
    """商品的严格身份：同款判断的输入。

    非适用字段（如耳机没有 storage）由归一层明确写 not_applicable 并提供证据；
    缺失写 None，不要用空字符串伪装成「已确认」。
    """

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
    """某平台/店铺对某个商品规格的一次报价。属 A 主笔，A 冻结前由本文件先承载。

    注意 shipping / tax 的可空性：解析不到就是 None。
    含税场景由适配器明确填 0 表示「无额外税费」，不是「解析不到就填零」。
    """

    offer_id: str
    product_id: str
    source_product_id: str | None = None
    platform: Platform
    marketplace: str = ""
    title: str = ""
    identity: ProductIdentity
    product_url: str = ""
    # 图片与推广链接按手册补上：ProductCard 必须给图（缺失时前端占位，不自动下载归档），
    # affiliate_url 只能来自已获准渠道 —— 没获准就留 None，绝不由模型或前端捏造。
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
    """一次价格计算的完整结果 —— 全项目「金额口径」的唯一载体。

    payable_amount 为 None 表示「当前不可核验」，这是特性不是缺陷：
    运费未知、资格未知、无货、缺证据时都必须给 None，而不是硬算一个数字。
    """

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
    """一条原始评论样本 —— 外部来源文本，**一律按不可信输入处理**。

    为什么要有这个合同：评论正文来自外部，里面可能写着"忽略之前的规则"之类的内容。
    把它固定成一个只有数据字段的类型，是为了让「评论内容」和「系统指令」在类型层面
    就分得开 —— 下游只把它当字符串素材，不给它任何指令语义（验收 R03）。

    rating 未知就是 None，不是 0（0 分是"极差"，用 0 表示未知会把差评统计搞反）。
    """

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


class ComparisonReport(StrictModel):
    """最终对比报告：结构化的卡片 + 模型只填的解释文字。"""

    cards: list[ProductCard] = Field(default_factory=list)
    explanation: str = ""
    limitations: list[str] = Field(default_factory=list)


__all__ = [
    "Money", "Currency", "Platform", "DataMode", "StockStatus", "Eligibility",
    "StrictModel", "ProductIdentity", "Promotion", "Offer", "PriceQuote",
    "ReviewSample", "ReviewTheme", "ReviewAnalysis", "ProductCard", "ComparisonReport",
]
