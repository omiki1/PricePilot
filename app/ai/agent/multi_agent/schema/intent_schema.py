from pydantic import BaseModel, Field
# class SearchSchema(BaseModel):
#     category: str = Field(..., description='商品类型')
#     price: float = Field(..., description='价格')
class IntentSchema(BaseModel):
    router:str = Field(...,description='路由')
    category: str = Field('', description='英文检索词，品牌+品类')
    price: float = Field(0, description='预算，没说填 0')
    question: str = Field('', description='clarify/reject 时给用户看的一句话')

class QuerySchema(BaseModel):
    pass