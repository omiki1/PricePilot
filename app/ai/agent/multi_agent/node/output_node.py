from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.model import MyModel
from app.ai.prompt.builder_prompt import BuilderPromptYaml

prompt = BuilderPromptYaml.get_prompt('output_node.yaml')
def build_context(state):
    """拼接商品信息。"""
    lines = [
        '用户需求：' + state.get("category", ""),
        '预算：' + str(state.get("price", 0)) + '（人民币）',
    ]

    for rank, product in enumerate(state.get('ranked_top') or [], start=1):
        lines.append('')
        lines.append('商品 ' + str(rank) + '：' + product.title)
        lines.append('  价格：' + product.currency + ' ' + str(product.price)
                     + '｜评分：' + str(product.rating) + ' 分 / '
                     + str(product.rating_count) + ' 条')
        lines.append('  商品链接：' + product.url)

        if product.evidence:
            lines.append('  第三方证据：')
            for index, evidence in enumerate(product.evidence, start=1):
                tag = 'S' + str(rank) + str(index)   # S11、S12
                evidence['id'] = tag                 # 写回，前端做超链接用
                lines.append('    [' + tag + '] ' + evidence["title"]
                             + '（' + evidence["site"] + ' ' + evidence["date"] + '）')
                lines.append('        ' + evidence["snippet"])
        else:
            lines.append('  第三方证据：（未检索到）')

    return '\n'.join(lines)
async def output_node(state: ShoppingState):
    context = build_context(state)
    reply = await MyModel.get_model().ainvoke(prompt.format(context=context))

    products = []
    for product in (state.get('ranked_top') or [])[:3]:
        products.append({
            'title': product.title,
            'image_url': product.image_url,
            'url': product.url,
            'price': product.price,
            'currency': product.currency,
            'score': product.score,
            'evidence': product.evidence,
        })

    return {'answer': {'text': reply.content, 'products': products}}