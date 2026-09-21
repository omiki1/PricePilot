"""
贝叶斯平均排名：解决"5.0 分只有 3 条评价"压过"4.6 分有 656 条"的问题。

公式（IMDB Top 250 同款）：
    score = (v/(v+m)) * R + (m/(v+m)) * C
    R = 商品评分    v = 评价条数
    m = 先验权重（多少条评价才算可信），默认 50
    C = 先验均值（用本次候选自己算）
"""
DEFAULT_M = 50
DEFAULT_PRIOR = 4.0
def bayes_rank(products: list, m: int = DEFAULT_M) -> list:
    """算分并排序，返回排好序的列表（就地写回 score / score_reason）。"""
    if not products:
        return []
    rated = [p.rating for p in products if p.rating and p.rating_count]
    prior = sum(rated) / len(rated) if rated else DEFAULT_PRIOR

    for p in products:
        if not p.rating or not p.rating_count:
            p.score = None
            p.score_reason = '暂无评价，无法评估'
            continue
        p.score = (p.rating_count / (p.rating_count + m)) * p.rating \
                  + (m / (p.rating_count + m)) * prior
        p.score = round(p.score, 3)
        p.score_reason = f'{p.rating} 分 × {p.rating_count} 条 → 加权 {p.score}'
    products.sort(
        key=lambda p: (p.score is not None, p.score or 0, p.rating_count or 0),
        reverse=True,
    )
    return products
