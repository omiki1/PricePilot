import os
import re
import secrets
import smtplib
from email.mime.text import MIMEText

from dotenv import load_dotenv

from app.ai.tool.redis import Redis
from app.web.login_router.dao import UserDao

load_dotenv()


class UserService:
    """注册、登录和邮箱验证。"""

    @staticmethod
    def register(name, email, password, phone):
        try:
            pattern_email = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            pattern_phone = r'^1[3-9]\d{9}$'
            pattern_password = r'^[A-Za-z0-9]{8,16}$'
            if not re.match(pattern_email, email):
                return {"code": 400, "msg": "邮箱格式错误", "data": None}
            if not re.match(pattern_phone, phone):
                return {"code": 400, "msg": "手机号格式错误", "data": None}
            if not re.match(pattern_password, password):
                return {"code": 400, "msg": "密码必须大于8位且包含字母和数字", "data": None}

            if not name:
                return {"code": 400, "msg": "信息不全", "data": None}
            if not UserDao.check_email(email):
                return UserDao.register_dao(name, email, password, phone)
            return {"code": 409, "msg": "邮箱已注册", "data": None}
        except Exception as e:
            print(f"注册异常：{type(e).__name__}: {e}")
            return {"code": 500, "msg": "注册失败", "data": None}

    @staticmethod
    def login(account, password):
        if not account or not password:
            return {"code": 400, "msg": "信息不全", "data": None}
        return UserDao.login_dao(account, password)

    @staticmethod
    def send_email(email):
        if not UserDao.check_email(email):
            return {"code": 400, "msg": "邮箱未注册", "data": None}

        # 生成 6 位随机验证码。
        code = "".join(str(secrets.randbelow(10)) for _ in range(6))
        sender = os.getenv("SENDER_EMAIL")
        sender_pwd = os.getenv("SENDER_EMAIL_PASSWORD")
        subject = "验证码"
        content = f"你的验证码是：{code}，60s过期"
        message = MIMEText(content, "plain", "utf-8")
        message["From"] = sender
        message["To"] = email
        message["Subject"] = subject
        smtp = None
        r = None
        try:
            smtp = smtplib.SMTP(
                host=os.getenv("SMTP_HOST"),
                port=int(os.getenv("SMTP_PORT"))
            )
            smtp.starttls()
            smtp.login(sender, sender_pwd)
            smtp.sendmail(sender, email, message.as_string())

            r = Redis.get_conn()
            if r:
                # 验证码 60 秒后过期。
                r.set(f"email_code:{email}", code, ex=60)

            return {"code": 200, "msg": "发送成功", "data": None}

        except Exception as e:
            print(f"邮件发送失败：{e}")
            return {"code": 500, "msg": "发送失败", "data": None}

        finally:
            # 发送失败时也释放连接。
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    pass
            if r is not None:
                Redis.close(r)

    @staticmethod
    def verify_code(email, code):
        r = Redis.get_conn()
        if not r:
            print("Redis连接失败")
            return {"code": 500, "msg": "Redis连接失败", "data": None}

        try:
            key = f"email_code:{email}"
            stored_code = r.get(key)

            if not stored_code:
                return {"code": 400, "msg": "验证码已过期，请重新发送", "data": None}
            if stored_code != code:
                return {"code": 400, "msg": "验证码错误", "data": None}

            # 验证码只能使用一次。
            r.delete(key)

            users = UserDao.check_email(email)
            if not users:
                return {"code": 400, "msg": "邮箱未注册", "data": None}

            user = users[0]
            return {
                "code": 200,
                "msg": "验证成功",
                "data": {
                    "user_id": user["user_id"],
                    "username": user["username"],
                    "email": user["email"],
                },
            }
        finally:
            Redis.close(r)
