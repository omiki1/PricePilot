import requests
from app.ai.agent.multi_agent.schema.shopping_schema import Product
SHOPIFY_MCP_URL  = "https://catalog.shopify.com/api/ucp/mcp"
def search_shopify(arguments:dict) -> list[dict]:
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 1,

        "params": {
            "name": "search_catalog",
            "arguments": arguments
        }
    }
    response = requests.post(
        SHOPIFY_MCP_URL,
        json=payload,
        timeout=30
    )
    data = response.json()
    return (
        data
        .get("result", {})
        .get("structuredContent", {})
        .get("products", [])
    )
def normalize_shopify_product(
    item: dict
) -> Product:

    # 图片
    media = item.get("media") or []

    image_url = (
        media[0].get("url")
        if media
        else None
    )

    # 价格
    price_info = (
        item
        .get("price_range", {})
        .get("min", {})
    )

    amount = price_info.get("amount")

    price = (
        amount / 100
        if amount is not None
        else None
    )

    currency = price_info.get("currency")

    # variant
    variants = item.get("variants") or []

    variant = (
        variants[0]
        if variants
        else {}
    )

    # seller
    seller_info = (
        variant.get("seller")
        or {}
    )

    # rating
    rating_info = (
        item.get("rating")
        or {}
    )

    return Product(
        platform="shopify",
        product_id=item.get("id"),
        title=item.get("title", ""),
        price=price,
        currency=currency,
        image_url=image_url,
        url=variant.get("url"),
        seller=seller_info.get("name"),
        rating=rating_info.get("value"),
        rating_count=rating_info.get("count"),
        available=(
            variant
            .get("availability", {})
            .get("available")
        )
    )
def normalize_shopify_products(
    items: list[dict]
) -> list[Product]:

    return [
        normalize_shopify_product(item)
        for item in items
    ]