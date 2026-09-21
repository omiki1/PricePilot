from app.ai.tool.mysql_tool import MySQL
from passlib.context import CryptContext
class UserDao:
    """用户 DAO"""
    crypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    @staticmethod
    def check_email(email):
        conn = MySQL.get_conn()
        cur = conn.cursor()
        sql = "SELECT * FROM user where email=%s;"
        cur.execute(sql, [email])
        results = cur.fetchall()
        MySQL.close(cur, conn)
        return results

    @staticmethod
    def register_dao(name, email, password, phone):
        conn = MySQL.get_conn()
        cur = conn.cursor()
        password_hash = UserDao.crypt_context.hash(password)
        sql = "INSERT INTO user (user_id,username,email,password_hash,phone,create_time) VALUES (null,%s,%s,%s,%s,now());"
        cur.execute(sql, [name, email, password_hash, phone])
        conn.commit()
        MySQL.close(cur, conn)
        return {"code": 200, "msg": "注册成功", "data": None}

    @staticmethod
    def login_dao(email_or_phone, password):
        conn = MySQL.get_conn()
        cur = conn.cursor()
        sql = "SELECT user_id,username,email,password_hash,phone FROM user where email=%s or phone=%s;"
        cur.execute(sql, [email_or_phone, email_or_phone])
        user = cur.fetchone()
        MySQL.close(cur, conn)
        if not user:
            print("用户不存在")
            return {"code": 400, "msg": "用户不存在", "data": None}
        stored_password_hash = user['password_hash']
        if UserDao.crypt_context.verify(password, stored_password_hash):
            print("登录成功", user['username'])
            return {"code": 200, "msg": "登录成功", "data": {
                "user_id": user['user_id'],
                "username": user['username'],
                "email": user['email'],
                "phone": user['phone']
            }}
        else:
            print("密码错误")
            return {"code": 400, "msg": "密码错误", "data": None}