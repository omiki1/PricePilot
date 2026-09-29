from fastapi import APIRouter
from pydantic import BaseModel

from app.web.login_router.service import UserService

user_router = APIRouter()
register_router = APIRouter()
email_router = APIRouter()


class registerUser(BaseModel):
    name: str
    email: str
    password: str
    phone: str


@user_router.post('/login', summary='用户登录')
def login(account: str, password: str):
    return UserService.login(account, password)


@register_router.post('/register', summary='用户注册')
def register(user: registerUser):
    return UserService.register(user.name, user.email, user.password, user.phone)


@email_router.get('/sendEmail', summary='发送验证码')
def send_email(email: str):
    return UserService.send_email(email)


@email_router.get('/verifyCode', summary='验证验证码')
def verify_code(email: str, code: str):
    return UserService.verify_code(email, code)
