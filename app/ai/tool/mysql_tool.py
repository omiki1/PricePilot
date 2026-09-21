import pymysql
import os
from dotenv import load_dotenv
#
load_dotenv()


class MySQL:
    """MySQL 连接管理类"""
    @staticmethod
    def get_conn():
        """获取 MySQL 连接"""
        return pymysql.connect(
            host=os.getenv('MYSQL_HOST'),
            port=int(os.getenv('MYSQL_PORT')),
            user=os.getenv('MYSQL_USER'),
            password=os.getenv('MYSQL_PASSWORD'),
            database=os.getenv('MYSQL_DATABASE'),
            charset=os.getenv('MYSQL_CHARSET'),
            cursorclass=pymysql.cursors.DictCursor
        )

    @staticmethod
    def close(cursor, conn):
        """关闭游标和连接"""
        cursor.close()
        conn.close()