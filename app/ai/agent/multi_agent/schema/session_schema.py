"""会话接口的请求体。响应直接返回 dict，字段见 session_repository。"""
from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    user_id: str | None = Field(default=None, max_length=64, description='临时：接入 token 后废弃')


class SessionRenameRequest(BaseModel):
    user_id: str | None = Field(default=None, max_length=64, description='临时：接入 token 后废弃')
    title: str = Field(..., max_length=128)
