import operator
from typing_extensions import TypedDict,Annotated
from langchain_core.messages import AnyMessage

class ShoppingState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    session_id: int
    category:str
    price: float
    # 淘宝返回的统一商品
    products: list
    # 意图识别，走哪一个节点
    router: str
    ranked_top: list  # 排名后的商品（前 3 个带证据）；键名必须和节点读写一致，
    answer: dict

