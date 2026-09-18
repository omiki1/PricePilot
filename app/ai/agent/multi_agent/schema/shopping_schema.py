"""购物业务的共享数据结构。

命名沿用手册《结构化数据合同》的口径：来源适配器把平台返回映射成 Offer，
前端只展示后端给的字段，不自己从文字里抠价格。

当前只落地闲鱼（goofish）一条来源需要的字段；Amazon / 京东适配器接进来时
继续往 Offer 上加字段，不要另起一套结构。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Offer(BaseModel):

    source: str = Field(..., description='来源适配器名：xianyu / amazon / jd')
    platform: str = Field(..., description='展示用平台名：闲鱼 / Amazon / 京东')
    source_id: str = Field(..., description='来源侧的商品标识，如闲鱼 itemId、Amazon ASIN')
    title: str
    price: float | None = Field(default=None, description='挂牌价，数字；缺价时为 None')
    currency: str = Field(default='CNY')
    url: str = Field(..., description='商品页链接，必须来自来源返回，不由模型生成')
    image_url: str | None = None
    city: str | None = None
    seller: str | None = None
    want_count: int | None = Field(default=None, description='闲鱼"想要"人数')
    free_shipping: bool | None = None
    accepts_bargain: bool | None = None
    fetched_at: str | None = Field(default=None, description='采集时间，ISO8601')
    data_mode: str = Field(default='live_showcase', description='demo / live_showcase / live_full')
    # ---- Amazon 扩展（闲鱼/淘宝侧留空）----
    brand: str | None = None
    rating: float | None = Field(default=None, description='星级评分')
    reviews_count: int | None = None
    list_price: float | None = Field(default=None, description='划线价（原价）')
    shipping_price: float | None = None
    in_stock: bool | None = None
    condition: str | None = None

    # ---- 淘宝/天猫扩展 ----
    shop_name: str | None = Field(default=None, description='店铺名')
    sales: int | None = Field(default=None, description='销量')
    coupon_price: float | None = Field(default=None, description='券后价')
    is_tmall: bool | None = None
    sku_count: int | None = None


class SearchOutcome(BaseModel):
    """一次来源检索的结果，带状态，便于前端如实展示"没查到/没开权限/timeout"。"""

    source: str
    mode: str = Field(..., description='来源自己的模式：闲鱼 feed/search；Amazon search/detail')
    keyword: str | None = None
    status: str = Field(..., description='completed / not_configured / needs_session / failed / timeout')
    offers: list[Offer] = Field(default_factory=list)
    message: str | None = Field(default=None, description='给用户看的说明，不含密钥与堆栈')
    compliance_note: str | None = Field(
        default=None,
        description='该来源的展示/缓存约束提示，例如 Amazon 的商品数据缓存限制',
    )
