from typing import Literal

from pydantic import BaseModel, Field


class IntentSchema(BaseModel):
    router: Literal['search', 'chat', 'clarify', 'reject'] = Field(..., description='路由')
    category: str = Field('', description='英文检索词，品牌+品类')
    price: float = Field(0, description='预算，没说填 0')
    # ── [B 修改 2026-09-24] 定性价格偏好 ────────────────────────────────────
    # 「便宜的秋季外套」里没有数字，price 只能填 0 → 预算约束消失 → 推上千的贵货。
    # 把"便宜/平价/高端"这类没有数字的**定性**倾向单独抽成 price_pref，
    # 交给 adapter 在候选集内做相对收窄（不凭空发明绝对价格）。
    price_pref: str = Field('', description='定性价格偏好：cheap / premium，没有填 ""')
    question: str = Field('', description='clarify/reject 时给用户看的一句话')


class QuerySchema(BaseModel):
    pass