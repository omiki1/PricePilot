"""聊天链路冒烟探针"""
from __future__ import annotations

import argparse
import json
import os
import sys

import requests

DEFAULT_BASE = os.environ.get("CHAT_PROBE_BASE", "http://127.0.0.1:8008/chat")


def _product_line(product: dict) -> str:
    price = product.get("price_text") or f"{product.get('min_price')} {product.get('currency')}"
    return f"    - {product.get('title')} | {price}"


def ask(question: str, user_id: str, session_id: str, base: str,
        label: str = "", show_text: int = 160) -> dict:
    """发一轮 /chat（SSE），把商品帧与文字帧收齐后打印。"""
    tag = f"[{label}] " if label else ""
    print("=" * 72)
    print(f"{tag}用户：{question}")
    params = {"question": question, "user_id": user_id, "session_id": session_id}
    text, products = [], []
    with requests.get(base, params=params, stream=True, timeout=300,
                      headers={"Accept-Encoding": "identity"},
                      proxies={"http": None, "https": None}) as response:
        response.raise_for_status()
        for raw in response.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data: "):
                continue
            payload = json.loads(raw[6:])
            if payload.get("type") == "products":
                products = payload.get("data") or []
            elif payload.get("type") == "text":
                text.append(payload.get("data") or "")
            if payload.get("done"):
                break

    body = "".join(text)
    print(f"{tag}商品数={len(products)}")
    for product in products[:3]:
        print(_product_line(product))
    if show_text:
        print(f"{tag}回复：{body[:show_text]}{'…' if len(body) > show_text else ''}")
    print()
    return {"products": products, "text": body}


def main() -> int:
    parser = argparse.ArgumentParser(description="聊天链路冒烟探针")
    parser.add_argument("questions", nargs="+", help="按顺序发的问题（同一会话连续多轮）")
    parser.add_argument("--session", default="probe", help="会话 ID（默认 probe）")
    parser.add_argument("--user", default="probe", help="用户 ID（默认 probe）")
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"接口地址（默认 {DEFAULT_BASE}）")
    parser.add_argument("--text", type=int, default=160, help="每轮回复打印多少字，0 为不打印")
    parser.add_argument("--json", action="store_true", help="额外输出每轮商品的原始 JSON")
    args = parser.parse_args()

    for index, question in enumerate(args.questions, start=1):
        result = ask(question, args.user, args.session, args.base,
                     label=f"轮{index}", show_text=args.text)
        if args.json:
            print(json.dumps(result["products"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
