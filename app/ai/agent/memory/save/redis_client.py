import os

import redis.asyncio as redis
from dotenv import load_dotenv

load_dotenv()


def create_redis_client(db_default=0, **overrides):
    """窗口记忆和用户画像共用连接配置。"""
    options = {
        'host': os.getenv('REDIS_HOST', 'localhost'),
        'port': int(os.getenv('REDIS_PORT', 6379)),
        'db': int(os.getenv('REDIS_DB', db_default)),
        'socket_timeout': 3,
        'decode_responses': True,
    }
    if os.getenv('REDIS_PASSWORD'):
        options['password'] = os.getenv('REDIS_PASSWORD')
    for name, value in overrides.items():
        if value is not None:
            options[name] = value
    return redis.StrictRedis(**options)
