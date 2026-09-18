import requests

url = "https://catalog.shopify.com/api/ucp/mcp"

payload = {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "id": 1,
    "params": {
        "name": "search_catalog",
        "arguments": {
            "meta": {
                "ucp-agent": {
                    "profile": (
                        "https://shopify.dev/ucp/"
                        "agent-profiles/2026-08-25/"
                        "valid-with-capabilities.json"
                    )
                }
            },
            "catalog": {
                "query": "wireless mechanical keyboard"
            }
        }
    }
}

response = requests.post(
    url,
    json=payload,
    timeout=30
)

print(response.status_code)
print(response.json())