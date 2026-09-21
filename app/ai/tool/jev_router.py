import os
import requests
URL = 'https://api.typesafe.ai/v1/systemone'
def should_clarify(user_input: str) -> bool:
    key = os.getenv('TYPESAFE_API_KEY')
    if not key:
        return True
    body = {
        'state': user_input,
        'model': os.getenv('TYPESAFE_DEFAULT_MODEL', 'jev-latest'),
        'questions': {
            'router': {
                'type': 'choice',
                'instructions': '用户这句话的意图属于哪一类',
                'criteria': {
                    'search': '想购买某类具体商品',
                    'chat': '打招呼、闲聊，或与购物无关',
                    'clarify': '想买东西但没说清是什么商品',
                    'reject': '想买但系统做不到',
                },
            },
        },
    }
    resp = requests.post(URL, json=body, timeout=10,headers={'Authorization': 'Bearer ' + key})
    answer = resp.json()['answers']['router']
    choice = answer['choice']
    confidence = answer.get('confidence') or 0.0
    print(f'[jev] choice={choice} confidence={confidence}')
    # Jev 说有商品可搜、而且它很确定 → 别追问了
    return not (choice == 'search' and confidence >= 0.6)
