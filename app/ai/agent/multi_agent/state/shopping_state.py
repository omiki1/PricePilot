import operator
from typing_extensions import TypedDict,Annotated
from langchain_core.messages import AnyMessage

class ShoppingState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    session_id: int
    category:str
    price: float
