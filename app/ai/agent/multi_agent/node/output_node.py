from app.ai.agent.multi_agent.schema.shopping_schema import Product
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.model import MyModel
from app.ai.prompt.builder_prompt import BuilderPromptYaml

from app.ai.tool.currency import enrich_product, format_range, rate_note

prompt = BuilderPromptYaml.get_prompt('output_node.yaml')


def _as_product(item) -> Product:
    """把 state 里的候选统一成 Product。"""
    if isinstance(item, Product):
        return item
    if isinstance(item, dict):
        return Product(**item)
    return item


def _price_text(product: Product) -> str:
    """价格展示：有区间就显示区间，只有一个价就显示单值，并附人民币换算。"""
    return format_range(product.min_price, product.max_price, product.currency or 'USD')


def build_context(state):
    """拼接商品信息。"""
    lines = []


    # memory_block 由 shopping_graph.chat() 在进图前组装好（历史摘要 + 长期记忆 +。
    memory_block = (state.get('memory_block') or '').strip()
    if memory_block:
        lines.append('【关于该用户的记忆】（跨会话累积，供参考；'
                     '与本次需求冲突时一律以本次需求为准）')
        lines.append(memory_block)
        lines.append('')

    lines += [
        '用户需求：' + state.get("category", ""),
        '预算：' + str(state.get("price", 0)) + '（人民币）',
    ]


    # 「便宜」这种没有数字的诉求，光给「预算：0」模型会当成"不限预算"。
    price_pref = (state.get('price_pref') or '').strip().lower()
    if price_pref == 'cheap':
        lines.append('价格偏好：用户要"便宜 / 平价"，候选已只保留价格偏低的那一档，'
                     '推荐理由里要体现这一点。')
    elif price_pref == 'premium':
        lines.append('价格偏好：用户偏向"高端 / 旗舰"，不特别省钱，重品质。')


    # 商品是美元价、预算是人民币，不给汇率说明模型容易自己编一个。
    fx = rate_note()
    if fx:
        lines.append(fx)

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

        # 保证和 recommend 节点推给前端的商品帧字段口径一致。
        products.append(enrich_product({
            'title': product.title,
            'image_url': product.image_url,
            'url': product.url,
            'min_price': product.min_price,
            'max_price': product.max_price,
            'price_text': _price_text(product),
            'currency': product.currency,
            'score': product.score,
            'evidence': product.evidence,
        }))

    return {'answer': {'text': reply.content, 'products': products}}
