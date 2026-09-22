from fastapi import APIRouter
from pydantic import BaseModel

from app.web.login_router.service import UserService
user_router = APIRouter()
register_router = APIRouter()
email_router = APIRouter()

# 账号密码登录
@user_router.post(
    path="/login",
    summary="用户登录",
    description="""
            用户登录
            访问路径：http://localhost:8000/user/login
            请求参数：
                account：字符串类型，用户输入的账号
                password：字符串类型，用户输入的密码
            返回值：
                {
                    "code": 状态码，成功200、失败500，int
                    "msg": 提示信息，字符串
                    "data": None，数据内容，Object
                }
            """,
)
def login(account: str,password: str):
    return UserService.login(account,password)

class registerUser(BaseModel):
    name: str
    email: str
    password: str
    phone: str
@register_router.post(
    path="/register",
    summary="用户注册",
    description="""
            用户注册
            访问路径：http://localhost:8000/user/register
            请求参数：
                username：字符串类型，用户输入的用户名
                email：字符串类型，用户输入的邮箱号
                password：字符串类型，用户输入的密码
                phone：字符串类型，用户输入的手机号
            返回值：
                {
                    "code": 状态码，成功200、失败500，int
                    "msg": 提示信息，字符串
                    "data": None，数据内容，Object
                }
            """,
)
def register(user: registerUser):
    return UserService.register(user.name, user.email, user.password, user.phone)
#邮箱验证码登录
@email_router.get(
    path="/sendEmail",
    summary="发送邮件",
    description="""
            给用户输入的邮箱号发送验证码
            访问路径：http://localhost:8000/users/sendEmail
            请求参数：
                email：字符串类型，用户输入的邮箱号
            返回值：
                {
                    "code": 状态码，成功200、失败500，int
                    "msg": 提示信息，字符串
                    "data": None，数据内容，Object
                }
        """,
)
def send_email(email: str):
    return UserService.send_email(email)

@email_router.get(
    path="/verifyCode",
    summary="验证码验证",
    description="""
            验证用户输入的验证码
            访问路径：http://localhost:8000/users/verifyCode
            请求参数：
                email：字符串类型，用户输入的邮箱号
                code：字符串类型，用户输入的验证码
            返回值：
                {
                    "code": 状态码，成功200、失败500，int
                    "msg": 提示信息，字符串
                    "data": None，数据内容，Object}"""
)
def verify_code(email: str, code: str):
    return UserService.verify_code(email, code)