import time

import requests

from app.ai.agent.multi_agent.schema.shopping_schema import Product

SHOPIFY_MCP_URL = "https://catalog.shopify.com/api/ucp/mcp"
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.8

_SESSION = requests.Session()


class ShopifySearchError(RuntimeError):
    """MCP 检索在重试后仍然失败。"""


def search_shopify(arguments: dict) -> list[dict]:
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 1,

        "params": {
            "name": "search_catalog",
            "arguments": arguments
        }
    }
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = _SESSION.post(
                SHOPIFY_MCP_URL,
                json=payload,
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            )
            # 服务端错误重试，其他 HTTP 错误直接返回。
            if response.status_code >= 500:
                raise ShopifySearchError(
                    f'MCP 返回 {response.status_code}')
            response.raise_for_status()
            data = response.json()
            content = data.get("result", {}).get("structuredContent", {})
            return content.get("products", [])
        except (requests.Timeout, requests.ConnectionError, ShopifySearchError) as error:
            last_error = error
        except requests.exceptions.RequestException as error:
            raise ShopifySearchError(
                f'Shopify MCP 请求失败：{error}') from error
        except ValueError as error:
            # response.json() 解析失败
            raise ShopifySearchError(
                f'Shopify MCP 返回无法解析为 JSON：{error}') from error

        if attempt < MAX_ATTEMPTS:
            wait = BACKOFF_BASE_SECONDS * attempt
            print(f'[shopify] 第 {attempt} 次检索失败（{last_error}），'
                  f'{wait:.1f}s 后重试')
            time.sleep(wait)

    raise ShopifySearchError(
        f'Shopify MCP 连续 {MAX_ATTEMPTS} 次失败：{last_error}')


def normalize_shopify_product(item: dict) -> Product:
    """转换目录字段；来源金额以分为单位。"""
    media = item.get("media") or []
    image_url = media[0].get("url") if media else None
    price_range = item.get("price_range") or {}
    min_price_info = price_range.get("min") or {}
    max_price_info = price_range.get("max") or {}

    min_amount = min_price_info.get("amount")
    max_amount = max_price_info.get("amount")
    min_price = min_amount / 100 if min_amount is not None else None
    max_price = max_amount / 100 if max_amount is not None else None
    currency = min_price_info.get("currency") or max_price_info.get("currency")
    variants = item.get("variants") or []
    variant = variants[0] if variants else {}
    seller_info = variant.get("seller") or {}
    rating_info = item.get("rating") or {}
    return Product(
        platform="shopify",
        product_id=item.get("id"),
        title=item.get("title", ""),
        min_price=min_price,
        max_price=max_price,
        currency=currency,
        image_url=image_url,
        url=variant.get("url"),
        seller=seller_info.get("name"),
        rating=rating_info.get("value"),
        rating_count=rating_info.get("count"),
        available=variant.get("availability", {}).get("available"),
    )


def normalize_shopify_products(items: list[dict]) -> list[Product]:
    return [normalize_shopify_product(item) for item in items]
