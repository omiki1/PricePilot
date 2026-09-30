import operator
from typing_extensions import TypedDict,Annotated
from langchain_core.messages import AnyMessage

class ShoppingState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    session_id: str
    category: str
    price: float

    # 无具体预算时，用 cheap / premium 表示价格偏好。
    price_pref: str
    # 搜索结果与排名后的商品。
    products: list
    # 意图识别，走哪一个节点
    router: str
    ranked_top: list
    answer: dict
    question: str

    # 用户归属和本轮读取的记忆。
    user_id: str
    memory_block: str


    requirements: dict
    offers: list
    price_results: list
    prepare_notes: list
    review_results: list
    review_status: str
    review_error: str | None
    review_evidence: dict
    review_limitations: list
    # 商品 ID → 评论缺失或分析失败的原因。
    review_notes: dict
    comparison_result: dict
    final_report: dict | None

