import os
import secrets
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
from app.ai.tool.redis import Redis
from app.web.login_router.dao import UserDao
import re
load_dotenv()
class UserService:
    """用户服务类"""

    @staticmethod
    def register(name, email, password, phone):
        # 验证是否注册过
        try:
            # 判断格式
            pattern_email = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            pattern_phone = r'^1[3-9]\d{9}$'
            pattern_password = r'^[A-Za-z0-9]{8,16}$'
            if not re.match(pattern_email, email):  # 开头匹配
                return {"code": 400,
                        "msg": "邮箱格式错误",
                        "data": None
                        }
            if not re.match(pattern_phone, phone):
                return {"code": 400,
                        "msg": "手机号格式错误",
                        "data": None
                        }
            if not re.match(pattern_password, password):
                return {"code": 400,
                        "msg": "密码必须大于8位且包含字母和数字",
                        "data": None
                        }

            if not name:
                return {"code": 400,
                        "msg": "信息不全",
                        "data": None
                        }
            if not UserDao.check_email(email):  # 判断邮箱是否注册过
                return UserDao.register_dao(name, email, password, phone)
            else:
                return {"code": 409,
                        "msg": "邮箱已注册",
                        "data": None
                        }
        except Exception as e:
            return {"code": 500,
                    "msg": "注册失败",
                    "data": None
                    }

    @staticmethod
    def login(account, password):
        if not account or not password:
            return {"code": 400,
                    "msg": "信息不全",
                    "data": None
                    }
        result = UserDao.login_dao(account, password)
        return result

    @staticmethod
    def send_email(email):

        # 1 验证是否注册过
        # check_email 返回的是查询结果（可能 list 也可能 tuple，看游标实现），
        # 所以不能判断类型 —— 空结果本身是假值，直接 bool() 取真假即可。
        # 之前写 isinstance(..., list) 导致 flag 永远是 False，连已注册的邮箱都发不出去。
        if not UserDao.check_email(email):
            return {"code": 400,
                    "msg": "邮箱未注册",
                    "data": None
                    }

        # 2 生成 6 位验证码
        # 用 secrets 而不是 random：random 是可预测的伪随机，
        # 拿它生成验证码等于给爆破开绿灯。
        code = "".join(str(secrets.randbelow(10)) for _ in range(6))
        # 发邮件
        sender = os.getenv("SENDER_EMAIL")  # 发送者
        sender_pwd = os.getenv("SENDER_EMAIL_PASSWORD")  # 发送者授权码
        subject = "验证码"
        content = f"你的验证码是：{code}，60s过期"
        # 创建发送邮件对象
        message = MIMEText(content, "plain", "utf-8")  # 内容，类型，编码
        message["From"] = sender
        message["To"] = email
        message["Subject"] = subject  # 邮件主题
        # 先赋 None：finally 里才能判断"到底连上没有"，
        # 否则未连上时引用未定义变量会 NameError
        smtp = None
        r = None
        try:
            smtp = smtplib.SMTP(
                host=os.getenv("SMTP_HOST"),  # SMTP服务器地址
                port=int(os.getenv("SMTP_PORT"))  # SMTP服务器端口
            )
            smtp.starttls()                  # 开启tls加密
            smtp.login(sender, sender_pwd)   # 验证授权码和账号
            smtp.sendmail(sender, email, message.as_string())

            r = Redis.get_conn()
            if r:
                # 验证码只存 60 秒，不写日志（写进日志等于泄露）
                r.set(f"email_code:{email}", code, ex=60)

            return {"code": 200, "msg": "发送成功", "data": None}

        except Exception as e:
            print(f"邮件发送失败：{e}")
            return {"code": 500, "msg": "发送失败", "data": None}

        finally:
            # 不管成功还是异常，两条连接都要关掉，否则异常路径会泄漏
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    pass          # 连接早就断了，忽略
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

            # 不打印验证码本身：日志谁都能看，打出来等于泄露
            if not stored_code:
                return {"code": 400, "msg": "验证码已过期，请重新发送", "data": None}
            if stored_code != code:
                return {"code": 400, "msg": "验证码错误", "data": None}

            # 验证成功立刻删掉，防止同一个码被重复使用
            r.delete(key)

            # 从数据库查用户信息；查不到就如实报错，别让 [0] 抛 IndexError
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