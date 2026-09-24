import operator
from typing_extensions import TypedDict,Annotated
from langchain_core.messages import AnyMessage

class ShoppingState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    session_id: int
    category:str
    price: float
    # ── [B 修改 2026-09-24] 定性价格偏好 ────────────────────────────────────
    # "便宜的秋季外套" 这类说法里没有数字，price 只能填 0，于是预算约束整个消失，
    # 排在前面的全是上千的贵货。price_pref 把"便宜/平价/高端"这类**定性**倾向
    # 单独存下来（'' / 'cheap' / 'premium'），由 adapter 在候选集内部按相对价格
    # 收窄（不发明绝对数字，见 adapter._keep_cheaper_half）。
    price_pref: str
    # 淘宝返回的统一商品
    products: list
    # 意图识别，走哪一个节点
    router: str
    ranked_top: list  # 排名后的商品（前 3 个带证据）；键名必须和节点读写一致，
    answer: dict
    question: str
    # ── [B 修改 2026-09-23] 四层记忆接入用 ────────────────────────────────
    # user_id：跨会话记忆（L3 长期记忆 / L4 用户画像）按它隔离，
    #          由 shopping_graph.chat() 从 HTTP 层带进来。
    # memory_block：本轮的四层记忆段落（历史摘要 + 长期记忆 + 用户画像），
    #          在进图前组装一次，output 节点直接复用，避免重复调嵌入接口。
    user_id: str
    memory_block: str
    # ── [B 修改 2026-09-24] 对比报告链路字段 ──────────────────────────────
    # 与上面「搜索→推荐」那一套是**两条独立分支**，字段名刻意错开，互不覆盖：
    #   requirement/offers/.../comparison_result 只由对比链路读写；
    #   category/price/products/ranked_top/answer 仍归原来的搜索链路。
    # 手册《shopping_state.md》的字段表就是这么分的（各分支只写自己那段）。
    # requirements：结构化需求（预算、币种、目的地、用户关注点、避雷项），
    #           compare 节点靠它做预算内外分栏与偏好支持判断，所以必须是结构化字段，
    #           不能从自然语言现推。
    # offers：报价（某平台某店铺对某商品规格的一次报价）。注意它和 products 不是一回事：
    #           products 是"搜到的商品"，offers 才带运费/税费/资格，价格是否可信取决于它。
    # price_results：价格计算结果（PriceQuote），付款金额的唯一来源。
    # review_results / review_status / review_error：评论分支的产出与状态（completed/empty/failed）。
    # review_evidence：每款的去重口径报告（原始条数、各类丢弃数、有效样本数），
    #           报告里的分母必须来自它，而不是模型或临时计算。
    # comparison_result：程序过滤与排序后的分组结果，reporter 只读不写。
    # final_report：结构化报告（卡片 + 解释 + 限制），不是一段字符串。
    requirements: dict
    offers: list
    price_results: list
    prepare_notes: list
    review_results: list
    review_status: str
    review_error: str | None
    review_evidence: dict
    review_limitations: list
    # review_notes：product_id → 这一款为什么没有分析结果。
    # 用来区分「无可用评论样本」（商品冷门）与「分析超时/失败」（我们的问题）——
    # 两者都不该被用户读成"这款没人买"。
    review_notes: dict
    comparison_result: dict
    final_report: dict | None

