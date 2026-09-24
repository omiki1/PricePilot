"""对比报告冒烟探针（B · 2026-09-24）

一条命令跑完「商品 → 报价 → 评论证据 → 确定性比较 → 报告」整条流水线，
把卡片、排序依据、样本口径和限制说明都打出来。调模型只发生在最后一步（写解释），
用 `--no-explanation` 可以完全离线跑。

用法：
    cd D:\\TechAgentStu\\PricePilot
    # 演示数据（默认）：4 款耳机 + 演示评论集，能一次看到"预算内 / 超预算 / 硬约束排除"三种结局
    D:\\Anaconda3\\envs\\agent_env\\python.exe tools\\compare_probe.py
    # 不调模型，只看结构化报告
    D:\\Anaconda3\\envs\\agent_env\\python.exe tools\\compare_probe.py --no-explanation
    # 拿线上检索结果来比（评论能力不可用时会如实降级并写进限制说明）
    D:\\Anaconda3\\envs\\agent_env\\python.exe tools\\compare_probe.py --live "头戴式耳机"

看输出时先看这三处，它们是这个模块的全部承诺：
    「口径」——币种/目的地/数据模式不同就不放在一起比；
    「排序依据」——有证据支持的偏好数 → 金额 → 稳定 ID，不含模型意见；
    「限制」——样本不足、金额未核验、被排除的原因，一条都不省略。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.ai.agent.multi_agent.graph.comparison_graph import run_comparison  # noqa: E402
from app.ai.agent.multi_agent.schema.price_schema import Offer  # noqa: E402
from app.ai.tool.price_calculator import calculate_quote  # noqa: E402

# 演示商品：故意覆盖四种结局 —— 预算内够格的、被避雷项排除的、超预算的、没有评论样本的
DEMO_PRODUCTS = [
    {"product_id": "p-a", "title": "通勤降噪耳机 A（1299）", "min_price": 1299, "currency": "CNY",
     "available": True, "url": "https://example.com/p-a"},
    {"product_id": "p-b", "title": "低价耳机 B（499，评论提到夹头）", "min_price": 499,
     "currency": "CNY", "available": True, "url": "https://example.com/p-b"},
    {"product_id": "p-c", "title": "舒适佩戴耳机 C（1599）", "min_price": 1599, "currency": "CNY",
     "available": True, "url": "https://example.com/p-c"},
    {"product_id": "p-d", "title": "旗舰耳机 D（3200，超预算、无评论样本）", "min_price": 3200,
     "currency": "CNY", "available": True, "url": "https://example.com/p-d"},
]

DEMO_REQUIREMENTS = {
    "currency": "CNY",
    "destination": "CN",
    "data_mode": "demo",
    "budget_max": "2000",
    "preferences": ["通勤降噪", "眼镜佩戴舒适"],
    "avoid": ["夹头"],
}


def _assume_shipping(offers: list[Offer]) -> list[Offer]:
    """演示用：假设包邮且无额外税费。

    真实链路里运费/税费未知时付款金额就是 None（这是特性）。演示时如果不给，
    报告里所有金额都会是"暂不可核验"，看不到"已核验付款金额"的样子，
    所以这里显式假设一次，并在输出里写清楚这是假设。

    注意必须写 `Decimal("0.00")`：`model_copy(update=...)` **不做校验**，
    塞个 int 0 进去会一路溜到 `checked_amount` 才炸（`'int' object has no
    attribute 'is_finite'`）—— 金额字段永远只给 Decimal。
    """
    zero = Decimal('0.00')
    return [offer.model_copy(update={"shipping": offer.shipping if offer.shipping is not None else zero,
                                     "tax": offer.tax if offer.tax is not None else zero})
            for offer in offers]


def _products_from_live(query: str) -> list[dict]:
    """调一次真实的 Shopify 检索，把结果当候选。"""
    from app.ai.agent.multi_agent.schema.adapter import (
        build_shopify_arguments, filter_products_by_budget, map_state_to_shopify,
    )
    from app.ai.agent.multi_agent.schema.shopping_schema import ShopifySearchInput
    from app.ai.tool.search_shopify import normalize_shopify_products, search_shopify

    search_input = ShopifySearchInput(query=query)
    raw = search_shopify(build_shopify_arguments(search_input))
    products = normalize_shopify_products(raw)
    products, report = filter_products_by_budget(products, search_input)
    print(f'[live] 检索「{query}」得到 {len(products)} 个候选（{report}）\n', flush=True)
    return [product.model_dump() for product in products]


def _print_report(output: dict, *, note: str = '') -> None:
    report = output.get('final_report') or {}
    criteria = report.get('criteria') or {}

    print('=' * 74)
    print('比较口径')
    print(f"  币种 {criteria.get('currency')}｜目的地 {criteria.get('destination') or '（未指定）'}"
          f"｜预算上限 {criteria.get('budget_max') or '（未设）'}"
          f"｜数据模式 {criteria.get('data_mode')}")
    print(f"  用户关注点：{'、'.join(criteria.get('preferences') or []) or '（无）'}"
          f"｜避雷项：{'、'.join(criteria.get('avoid') or []) or '（无）'}")
    print(f"  排序依据：{criteria.get('sort')}")

    titles = {card['product_id']: card['title'] for card in report.get('cards') or []}
    for group in report.get('groups') or []:
        print('-' * 74)
        print(f"分组 [{group['currency']} / {group['destination'] or '未指定'} / "
              f"{group['data_mode']}] 共 {len(group['items'])} 款")
        for item in group['items']:
            matrix = item.get('preference_matrix') or {}
            hits = '、'.join(f'{name}={value["status"]}' for name, value in matrix.items())
            review = item.get('review') or {}
            print(f"  #{item['rank']} {titles.get(item['product_id'], item['product_id'])}")
            print(f"     金额：{item['amount_label']}（{item['currency']} {item['original_price']}"
                  + (f" → 付款 {item['payable_amount']}" if item.get('payable_amount') else '') + '）')
            print(f"     偏好：{hits or '（无）'}｜有证据支持 {item['supported_count']} 项"
                  f"｜未知 {item['unknown_count']} 项")
            print(f"     评论：{review.get('frequency_statement') or '（无样本）'}")
            for theme in (review.get('themes') or [])[:3]:
                kind = '优点' if theme['kind'] == 'pro' else '缺点'
                share = '样本为 0' if theme['share'] is None else f"{theme['mention_count']}/{theme['sample_size']}"
                print(f"       · [{kind}] {theme['label']}（{share}，证据 {theme['review_ids'][:3]}"
                      + ('…' if len(theme['review_ids']) > 3 else '') + '）')
        for note_line in group.get('notes') or []:
            print(f"  ! {note_line}")

    for bucket, title in (('over_budget', '超预算（单列，不作预算内首选）'),
                          ('excluded', '未参与比较')):
        items = output.get('comparison_result', {}).get(bucket) or []
        if not items:
            continue
        print('-' * 74)
        print(f'{title}：共 {len(items)} 款')
        for item in items:
            reason = item.get('excluded_reason') or f"超出预算 {item.get('over_budget_by')}"
            print(f"  · {titles.get(item['product_id'], item['product_id'])}｜{reason}")

    print('=' * 74)
    explanation = report.get('explanation') or ''
    print('解释：' + (explanation if explanation else '（未生成）'))
    print('-' * 74)
    print('限制说明：')
    for item in report.get('limitations') or ['（无）']:
        print('  - ' + item)
    if note:
        print('  - ' + note)


def main() -> int:
    parser = argparse.ArgumentParser(description='对比报告冒烟探针')
    parser.add_argument('--live', metavar='QUERY', help='用真实检索结果当候选（默认用演示数据）')
    parser.add_argument('--no-explanation', action='store_true', help='不调模型，只看结构化报告')
    parser.add_argument('--no-assume-shipping', action='store_true',
                        help='演示数据也不假设包邮（付款金额将全部不可核验）')
    parser.add_argument('--budget', default=None, help='覆盖预算上限，如 2000')
    parser.add_argument('--json', action='store_true', help='额外打印完整 JSON')
    args = parser.parse_args()

    requirements = dict(DEMO_REQUIREMENTS)
    if args.budget is not None:
        requirements['budget_max'] = args.budget

    note = ''
    if args.live:
        products = _products_from_live(args.live)
        requirements.update({'data_mode': 'live', 'budget_max': None})
        note = '本次候选来自真实检索；运费与税费未知，付款金额暂不可核验。'
        offers, quotes = None, None
    else:
        products = DEMO_PRODUCTS
        offers, quotes = None, None
        note = '演示运行：候选与评论均为演示数据。'

    if args.no_explanation:
        # 走"注入报价 + 空评论结果"的路径：完全离线，只验证结构化报告
        from app.ai.agent.multi_agent.schema.offer_builder import offers_from_products
        built, skipped = offers_from_products(
            products, destination=requirements.get('destination') or '',
            data_mode=requirements.get('data_mode') or 'demo')
        if not args.no_assume_shipping and not args.live:
            # 只有这条离线路径会真的假设包邮，所以只在这里这么说
            built = _assume_shipping(built)
            note += ' 且假设包邮、无额外税费。'
        elif not args.live:
            note += ' 未假设运费/税费，付款金额暂不可核验。'
        now = datetime.now(timezone.utc)
        output = asyncio.run(run_comparison(
            offers=built,
            quotes=[calculate_quote(offer, now) for offer in built],
            reviews=_load_demo_reviews([offer.product_id for offer in built]),
            requirements=requirements))
        if skipped:
            note = (note + ' ' if note else '') + '跳过：' + '；'.join(skipped)
    else:
        output = asyncio.run(run_comparison(
            products=products, requirements=requirements,
            review_provider=None, analyzer=None))
        if not args.live:
            # 默认走真实子图：offer_builder 不猜运费/税费（未知就是未知），
            # 所以付款金额会是"暂不可核验"，排序退回标价口径。
            note += ' 运费/税费未提供，付款金额暂不可核验，排序按商品标价口径。'
        if output.get('prepare_notes'):
            note = (note + ' ' if note else '') + '跳过：' + '；'.join(output['prepare_notes'])

    _print_report(output, note=note)
    if args.json:
        print()
        print(json.dumps(output.get('final_report'), ensure_ascii=False, indent=2))
    return 0


def _load_demo_reviews(product_ids: list[str]):
    """离线路径也要有评论结论，否则"有证据的排序"展示不出来。

    这里直接对演示样本套用**固定主题**（不调模型），主题里的 review_id 仍然取自
    真实样本集合 —— 所以"引用不存在的 ID 会被丢弃"这条仍然在被检验。
    """
    from app.ai.agent.multi_agent.schema.price_schema import (
        ReviewAnalysis, ReviewTheme,
    )
    from app.ai.tool.review_evidence import prepare_samples
    from app.ai.tool.review_fetch_tool import load_demo_provider

    provider = load_demo_provider()
    results = []
    for product_id in product_ids:
        try:
            samples, _ = prepare_samples(provider.fetch(product_id))
        except Exception:                                  # noqa: BLE001
            continue
        if not samples:
            continue
        ids = {sample.review_id for sample in samples}
        pick = lambda *candidates: [rid for rid in candidates if rid in ids]  # noqa: E731
        pros, cons = [], []
        if ids & {"r-a-01", "r-a-02", "r-a-03"}:
            pros.append(ReviewTheme(label="通勤降噪",
                                    review_ids=pick("r-a-01", "r-a-02", "r-a-03")))
        if ids & {"r-a-04", "r-a-05"}:
            cons.append(ReviewTheme(label="佩戴压耳",
                                    review_ids=pick("r-a-04", "r-a-05")))
        if ids & {"r-b-02"}:
            cons.append(ReviewTheme(label="夹头", review_ids=pick("r-b-02")))
        if ids & {"r-b-01", "r-b-03"}:
            cons.append(ReviewTheme(label="降噪弱", review_ids=pick("r-b-01", "r-b-03")))
        if ids & {"r-c-01", "r-c-02", "r-c-03"}:
            pros.append(ReviewTheme(label="眼镜佩戴舒适",
                                    review_ids=pick("r-c-01", "r-c-02", "r-c-03")))
        if ids & {"r-c-04"}:
            cons.append(ReviewTheme(label="降噪一般", review_ids=pick("r-c-04")))
        results.append(ReviewAnalysis(product_id=product_id, sample_size=len(samples),
                                      pros=pros, cons=cons))
    return results


if __name__ == '__main__':
    raise SystemExit(main())
