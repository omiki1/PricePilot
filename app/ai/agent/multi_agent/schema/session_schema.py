"""会话接口的请求体（omiki 2026-09-29）。响应直接返回 dict，字段见 session_repository。

user_id 字段只是为了接口文档里看得到「现在要传」：路由里的身份一律来自
app/web/deps.py 的 get_current_user_id，不读这里的值。接入 token 后可以删掉这个字段。
"""
from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    user_id: str | None = Field(default=None, max_length=64, description='临时：接入 token 后废弃')


class SessionRenameRequest(BaseModel):
    user_id: str | None = Field(default=None, max_length=64, description='临时：接入 token 后废弃')
    title: str = Field(..., max_length=128)
