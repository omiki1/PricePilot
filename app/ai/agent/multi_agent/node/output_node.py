from app.ai.agent.multi_agent.schema.shopping_schema import Product
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.model import MyModel
from app.ai.prompt.builder_prompt import BuilderPromptYaml

prompt = BuilderPromptYaml.get_prompt('output_node.yaml')


def _as_product(item) -> Product:
    """把 state 里的候选统一成 Product。

    recommend_node 写入的是 Product 对象，但 LangGraph 的 checkpoint 会把它们
    序列化后再还原（unregistered type 警告指的就是这一步），因此下游不该假定
    拿到的永远是 Product——两种形状都要能吃下。
    """
    if isinstance(item, Product):
        return item
    if isinstance(item, dict):
        return Product(**item)
    return item


def _price_text(product: Product) -> str:
    """价格展示：有区间就显示区间，只有一个价就显示单值。

    min_price / max_price 都是“可能为空”的字段（货源只给了一端时另一端为 None），
    所以不能直接参与字符串运算。
    """
    low, high = product.min_price, product.max_price
    if low is None and high is None:
        return '价格待确认'
    if low is None:
        body = str(high)
    elif high is None or high == low:
        body = str(low)
    else:
        body = str(low) + '~' + str(high)
    return ((product.currency or '') + ' ' + body).strip()


def build_context(state):
    """拼接商品信息。"""
    lines = [
        '用户需求：' + state.get("category", ""),
        '预算：' + str(state.get("price", 0)) + '（人民币）',
    ]

    for rank, raw in enumerate(state.get('ranked_top') or [], start=1):
        product = _as_product(raw)
        lines.append('')
        lines.append('商品 ' + str(rank) + '：' + product.title)
        lines.append('  价格：' + _price_text(product)
                     + '｜评分：' + str(product.rating) + ' 分 / '
                     + str(product.rating_count) + ' 条')
        lines.append('  商品链接：' + str(product.url))

        if product.evidence:
            lines.append('  第三方证据：')
            for evidence in product.evidence:
                lines.append('    ' + evidence["title"]
                             + '（' + evidence["site"] + ' ' + evidence["date"] + '）')
                lines.append('        ' + evidence["snippet"])
        else:
            lines.append('  第三方证据：（未检索到）')

    return '\n'.join(lines)


async def output_node(state: ShoppingState):
    context = build_context(state)
    reply = await MyModel.get_model().ainvoke(prompt.format(context=context))

    products = []
    for raw in (state.get('ranked_top') or [])[:3]:
        product = _as_product(raw)
        products.append({
            'title': product.title,
            'image_url': product.image_url,
            'url': product.url,
            'min_price': product.min_price,
            'max_price': product.max_price,
            'price_text': _price_text(product),
            'currency': product.currency,
            'score': product.score,
            'evidence': product.evidence,
        })

    return {'answer': {'text': reply.content, 'products': products}}
