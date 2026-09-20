from pydantic import BaseModel, Field
class SearchSchema(BaseModel):
    category: str = Field(..., description='商品类型')
    price: float = Field(..., description='价格')

class IntentSchema(BaseModel):
    router:str = Field(...,description='路由')


class QuerySchema(BaseModel):
    pass