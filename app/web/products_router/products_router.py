"""商品检索路由（只读，跑图取 state["products"]，不复制检索逻辑）。
  意图识别接口只回一句话，`shopify_search_node` 写进 state 的 products 拿不到。
  前端要验证 Shopify 接入效果，必须有个把 products 读出来的出口；
  本文件不重写检索逻辑，只做「跑图 → 读检查点 state → 返回」，
  与 intent_router 同一套约定（图从 request.app.state 取、没装配就 503）。
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.ai.agent.multi_agent.schema.shopping_schema import Product

products_router = APIRouter(tags=['products'])


class ProductSearchRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description='用户想买什么')
    user_id: str = Field(default='default', max_length=64)
    session_id: str = Field(default='', max_length=64, description='留空时用 user_id 作为会话')


class ProductSearchResponse(BaseModel):
    user_id: str
    session_id: str
    text: str
    category: str = ''
    price: float = 0
    products: list[Product] = Field(default_factory=list, description='shopify_search_node 写入的统一商品')


def get_graph(request: Request):
    graph = getattr(request.app.state, 'shopping_graph', None)
    if graph is None:
        raise HTTPException(status_code=503, detail='ShoppingGraph 未装配，请查看服务端日志')
    return graph


@products_router.post('/products/search', response_model=ProductSearchResponse)
async def products_search(body: ProductSearchRequest, request: Request) -> ProductSearchResponse:
    graph = get_graph(request)
    session_id = body.session_id or body.user_id or 'default'

    chunks: list[str] = []
    try:
        async for chunk in graph.chat(body.question, body.user_id, session_id):
            if isinstance(chunk, str) and chunk:
                chunks.append(chunk)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'检索失败：{exc}') from exc

    text = ''.join(chunks).strip()
    values: dict = {}
    try:
        snapshot = await graph.agent.aget_state({'configurable': {'thread_id': session_id}})
        values = dict(snapshot.values or {})
    except Exception:
        values = {}
    raw_products = values.get('products') or []
    products = [item if isinstance(item, Product) else Product(**item) for item in raw_products]

    return ProductSearchResponse(
        user_id=body.user_id,
        session_id=session_id,
        text=text,
        category=str(values.get('category') or ''),
        price=float(values.get('price') or 0),
        products=products,
    )