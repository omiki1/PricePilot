from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field

class FavoriteItem(BaseModel):
    """收藏夹里的一行。"""
    id: int = Field(description="收藏主键")
    user_id: str = Field(description="用户 ID")
    product_id: str = Field(description="来源商品 ID")
    title: str = Field(description="商品名称")
    image_url: str | None = Field(default=None, description="主图链接")
    product_url: str | None = Field(default=None, description="商品页链接")
    price: str | None = Field(default=None, description="收藏时的价格")
    time: str = Field(default="", description="收藏时刻")

class FavoriteProduct(BaseModel):
    """收藏时前端回传的商品快照。"""
    model_config = ConfigDict(extra="ignore")
    product_id: str = Field(..., min_length=1, max_length=191, description="来源商品 ID")
    title: str = Field(default="", max_length=512, description="商品名称")
    image_url: str | None = Field(default=None, max_length=1024, description="主图链接")
    product_url: str | None = Field(default=None, max_length=1024, description="商品页链接")
    url: str | None = Field(default=None, max_length=1024, description="商品页链接")
    price: float | None = Field(default=None, ge=0, description="当前价格")


class PricePoint(BaseModel):
    """一个价格点，前端逐行渲染。"""
    price: str = Field(description="价格")
    recorded_at: str = Field(description="记录时刻（UTC）")


class FavoriteAddRequest(BaseModel):
    """POST /api/favorites"""

    user_id: str = Field(default="default", max_length=64, description="用户 ID")
    product: FavoriteProduct = Field(description="商品快照")


class FavoriteRemoveRequest(BaseModel):
    """DELETE /api/favorites"""

    user_id: str = Field(default="default", max_length=64, description="用户 ID")
    product_id: str = Field(..., max_length=191, description="要移除的商品 ID")


class FavoriteListResponse(BaseModel):
    """GET /api/favorites"""

    user_id: str = Field(description="用户 ID")
    total: int = Field(description="收藏总条数")
    favorites: list[FavoriteItem] = Field(default_factory=list, description="收藏列表，最近收藏在前")


class FavoriteMutationResponse(BaseModel):
    """收藏/取消收藏的返回。"""

    ok: bool = Field(description="本次操作是否真的改动了数据")
    message: str = Field(description="给用户看的一句话")
    user_id: str = Field(description="用户 ID")
    total: int = Field(default=0, description="操作后的总条数")
    item: FavoriteItem | None = Field(default=None, description="本次写入的那一行")


class PriceHistoryResponse(BaseModel):
    """GET /api/products/price-history。只返回一串价格记录，不做任何计算。"""

    product_id: str = Field(description="商品 ID")
    points: list[PricePoint] = Field(default_factory=list, description="价格记录，时间正序")


class PriceRefreshRequest(BaseModel):
    """POST /api/products/price-history/refresh：回查商品当前价，再决定是否记一笔。"""

    user_id: str = Field(default="default", max_length=64, description="用户 ID")
    product_id: str = Field(..., min_length=1, max_length=191, description="来源商品 ID")
    fallback_price: float | None = Field(
        default=None, ge=0,
        description="回查不到时用这个价格兜底（前端卡片上那份）；不给就不写",
    )


class PriceRecordResponse(BaseModel):
    """回查 + 记账的结果。是否真的写入由仓储层判重决定（与上一条相同就不写）。"""

    product_id: str = Field(description="商品 ID")
    recorded: bool = Field(description="本次是否真的新增了一条（价格没变则为 false）")
    reason: str = Field(default="", description="ok / unchanged / no_price / not_found / no_title / no_price_fallback")
    message: str = Field(default="", description="给用户看的一句话")
    price: float | None = Field(default=None, description="本次用的价格（原币种金额）")
    source: str = Field(default="", description="价格来源：shopify=回查到的；fallback=卡片兜底价")
    points: list[PricePoint] = Field(default_factory=list, description="写入后的价格记录，时间正序")
