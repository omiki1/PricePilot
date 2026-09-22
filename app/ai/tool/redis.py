import redis
import os
from dotenv import load_dotenv

#加载环境变量
load_dotenv()
class Redis:
    """Redis 连接管理类"""

    @staticmethod
    def get_conn():
        """获取 Redis 连接"""
        return redis.Redis(
            host=os.getenv("REDIS_HOST"),
            port=int(os.getenv("REDIS_PORT")),
            password=os.getenv("REDIS_PASSWORD"),
            db=int(os.getenv("REDIS_DB")),
            decode_responses=True,
            protocol=2
        )

    @staticmethod
    def close(conn):
        """关闭连接"""
        conn.close()