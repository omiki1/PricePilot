"""商品搜索的离线回归测试。"""
from unittest.mock import Mock

import pytest
import requests

from app.ai.tool import search_shopify as search


def test_normalize_keeps_price_range_and_first_variant():
    item = {
        'id': 'p1',
        'title': '手办',
        'media': [{'url': 'https://example.com/image.png'}],
        'price_range': {
            'min': {'amount': 65000, 'currency': 'CNY'},
            'max': {'amount': 85000, 'currency': 'CNY'},
        },
        'variants': [{
            'url': 'https://example.com/p1',
            'seller': {'name': '商家'},
            'availability': {'available': True},
        }],
        'rating': {'value': 4.5, 'count': 20},
    }

    product = search.normalize_shopify_product(item)
    assert (product.min_price, product.max_price, product.currency) == (650, 850, 'CNY')
    assert product.image_url == 'https://example.com/image.png'
    assert product.url == 'https://example.com/p1'
    assert product.seller == '商家'
    assert product.available is True
    assert (product.rating, product.rating_count) == (4.5, 20)


def test_normalize_keeps_unknown_values_as_none():
    product = search.normalize_shopify_product({'id': 'p1'})

    assert product.min_price is None
    assert product.max_price is None
    assert product.currency is None
    assert product.image_url is None
    assert product.available is None


@pytest.mark.parametrize('first_failure', ['timeout', 'server_error'])
def test_temporary_failure_retries(monkeypatch, first_failure):
    success = Mock(status_code=200)
    success.json.return_value = {
        'result': {'structuredContent': {'products': [{'id': 'p1'}]}},
    }
    failure = requests.Timeout() if first_failure == 'timeout' else Mock(status_code=503)
    post = Mock(side_effect=[failure, success])
    sleep = Mock()
    monkeypatch.setattr(search._SESSION, 'post', post)
    monkeypatch.setattr(search.time, 'sleep', sleep)

    assert search.search_shopify({'query': '手办'}) == [{'id': 'p1'}]
    assert post.call_count == 2
    sleep.assert_called_once_with(search.BACKOFF_BASE_SECONDS)


def test_client_error_does_not_retry(monkeypatch):
    response = Mock(status_code=400)
    response.raise_for_status.side_effect = requests.HTTPError('bad request')
    post = Mock(return_value=response)
    monkeypatch.setattr(search._SESSION, 'post', post)

    with pytest.raises(search.ShopifySearchError, match='Shopify MCP 请求失败'):
        search.search_shopify({'query': '手办'})
    assert post.call_count == 1
