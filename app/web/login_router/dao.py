import bcrypt

from app.ai.tool.mysql_tool import MySQL


class UserDao:
    """用户 DAO。密码用 bcrypt 直接哈希，不经 passlib。

    为什么不用 passlib.CryptContext：
        passlib 1.7.4 与 bcrypt >= 4.1 不兼容 —— passlib 初始化时会跑一次
        bug 探测（handlers/bcrypt.py 的 detect_wrap_bug），它调 _bcrypt.hashpw
        传了一个超长字符串，而新版 bcrypt 直接抛：
            ValueError: password cannot be longer than 72 bytes
        结果注册/登录全挂，而 service 层把异常吞了，只显示"注册失败"。
        直接用 bcrypt 没有这层，行为也更可控。
    """

    # bcrypt 只取前 72 字节；本项目的密码规则是 8~16 位字母数字，不会触及上限。
    _MAX_BYTES = 72

    @staticmethod
    def _hash(password: str) -> str:
        raw = password.encode("utf-8")[:UserDao._MAX_BYTES]
        return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def _verify(password: str, hashed: str) -> bool:
        raw = password.encode("utf-8")[:UserDao._MAX_BYTES]
        try:
            return bcrypt.checkpw(raw, hashed.encode("utf-8"))
        except (ValueError, TypeError):
            # 库里存的不是合法 bcrypt 串（脏数据/旧格式），当验证失败处理，别抛出去
            return False

    @staticmethod
    def check_email(email):
        """按邮箱查用户。只取需要的列 —— 原来 SELECT * 会把 password_hash 一起捞出来。"""
        conn = MySQL.get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT user_id, username, email, phone, password_hash FROM user WHERE email = %s",
            [email],
        )
        results = cur.fetchall()
        MySQL.close(cur, conn)
        return results

    @staticmethod
    def register_dao(name, email, password, phone):
        conn = MySQL.get_conn()
        try:
            cur = conn.cursor()
            password_hash = UserDao._hash(password)
            cur.execute(
                "INSERT INTO user (username, email, password_hash, phone, create_time) "
                "VALUES (%s, %s, %s, %s, NOW())",
                [name, email, password_hash, phone],
            )
            conn.commit()
        finally:
            MySQL.close(cur, conn)
        return {"code": 200, "msg": "注册成功", "data": None}

    @staticmethod
    def login_dao(email_or_phone, password):
        conn = MySQL.get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT user_id, username, email, phone, password_hash FROM user "
            "WHERE email = %s OR phone = %s",
            [email_or_phone, email_or_phone],
        )
        user = cur.fetchone()
        MySQL.close(cur, conn)

        if not user:
            return {"code": 400, "msg": "用户不存在", "data": None}

        if not UserDao._verify(password, user["password_hash"]):
            return {"code": 400, "msg": "密码错误", "data": None}

        return {
            "code": 200,
            "msg": "登录成功",
            "data": {
                "user_id": user["user_id"],
                "username": user["username"],
                "email": user["email"],
                "phone": user["phone"],
            },
        }
