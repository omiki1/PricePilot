import time

import requests
from app.ai.agent.multi_agent.schema.shopping_schema import Product
SHOPIFY_MCP_URL  = "https://catalog.shopify.com/api/ucp/mcp"

# ── [B 修改 2026-09-23] 抗抖动 ──────────────────────────────────────────────
# 原实现 requests.post(..., timeout=30) 一次定生死。实测 catalog.shopify.com
# 延迟波动很大（裸 GET 曾耗 14.6s；正常 tools/call 是 0.9~1.6s），偶发一次读超时
# 就会让整个问答轮次崩成「服务器内部错误」，用户一句话都拿不到。
# 这里补三件事：
#   1) 连接/读取超时分开 (5, 60)：连不上就快速换下一次，服务端慢则给足时间；
#   2) 复用模块级 Session，免掉每次 1.5s 级别的 TLS 握手；
#   3) 超时/连接错误/5xx 自动重试 3 次，线性退避。
# 有意不重试 4xx：那是请求本身有问题，重试只会更慢。
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.8

_SESSION = requests.Session()
_RETRYABLE = (requests.exceptions.Timeout, requests.exceptions.ConnectionError)


class ShopifySearchError(RuntimeError):
    """MCP 检索在重试后仍然失败。

    专门抛这个类型，而不是在这里返回空列表：空列表和「检索失败」对上游是
    两件完全不同的事，调用方需要能区分，才能决定降级话术。
    """


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
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = _SESSION.post(
                SHOPIFY_MCP_URL,
                json=payload,
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            )
            # 5xx 是服务端抖动，值得重试；4xx 走到下面的 RequestException 直接失败
            if response.status_code >= 500:
                raise ShopifySearchError(
                    f'MCP 返回 {response.status_code}')
            response.raise_for_status()
            data = response.json()
            return (
                data
                .get("result", {})
                .get("structuredContent", {})
                .get("products", [])
            )
        except _RETRYABLE as error:
            last_error = error
        except ShopifySearchError as error:
            last_error = error
        except requests.exceptions.RequestException as error:
            # 非可重试的请求异常（4xx 等）：立即失败，不再浪费一次往返
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
    price_range = item.get("price_range") or {}
    min_price_info = price_range.get("min") or {}
    max_price_info = price_range.get("max") or {}

    min_amount = min_price_info.get("amount")
    max_amount = max_price_info.get("amount")
    min_price = (
        min_amount / 100
        if min_amount is not None
        else None
    )

    max_price = (
        max_amount / 100
        if max_amount is not None
        else None
    )
    currency = (
            min_price_info.get("currency")
            or max_price_info.get("currency")
    )
    variants = item.get("variants") or []
    variant = (
        variants[0]
        if variants
        else {}
    )
    seller_info = (
        variant.get("seller")
        or {}
    )
    rating_info = (
        item.get("rating")
        or {}
    )
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