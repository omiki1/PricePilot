"""会话增删查改，访问记录前检查归属。"""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.ai.agent.multi_agent.schema.session_schema import (
    SessionCreateRequest,
    SessionRenameRequest,
)
from app.ai.tool.session_repository import (
    SessionError,
    check_owner,
    create_session,
    delete_session,
    list_messages,
    list_sessions,
    rename_session,
)
from app.web.deps import get_current_user_id

session_router = APIRouter(tags=['sessions'])

FORBIDDEN_DETAIL = '会话不属于当前用户'
MISSING_DETAIL = '会话不存在或已删除'


def _unavailable(exc) -> HTTPException:
    print(f'[session] {exc}')
    return HTTPException(status_code=503, detail=str(exc))


def _require_owner(session_id: str, user_id: str) -> None:
    """归属校验：别人的 → 403；不存在 / 已删除 → 404。"""
    try:
        status = check_owner(session_id, user_id)
    except SessionError as exc:
        raise _unavailable(exc) from exc
    if status == 'forbidden':
        raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)
    if status != 'ok':
        raise HTTPException(status_code=404, detail=MISSING_DETAIL)


@session_router.post('/sessions')
def create(
    body: SessionCreateRequest | None = None,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """新建一个空会话，返回 {session_id, title: null, ...}。"""
    try:
        return create_session(user_id)
    except SessionError as exc:
        raise _unavailable(exc) from exc


@session_router.get('/sessions')
def read_sessions(
    user_id: str = Depends(get_current_user_id),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """当前用户的会话列表。只按 user_id 过滤，天然只返回自己的。"""
    try:
        sessions = list_sessions(user_id, limit=limit)
    except SessionError as exc:
        raise _unavailable(exc) from exc
    return {'user_id': user_id, 'sessions': sessions}


@session_router.get('/sessions/{session_id}/messages')
def read_messages(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    _require_owner(session_id, user_id)
    try:
        messages = list_messages(session_id)
    except SessionError as exc:
        raise _unavailable(exc) from exc
    return {'session_id': session_id, 'messages': messages}


@session_router.patch('/sessions/{session_id}')
def rename(
    session_id: str,
    body: SessionRenameRequest,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    title = ' '.join((body.title or '').split())
    if not title:
        raise HTTPException(status_code=400, detail='标题不能为空')
    _require_owner(session_id, user_id)
    try:
        return rename_session(session_id, title) or {}
    except SessionError as exc:
        raise _unavailable(exc) from exc


@session_router.delete('/sessions/{session_id}')
def remove(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """软删除：只改 is_deleted，聊天记录行和收藏夹都不动。"""
    _require_owner(session_id, user_id)
    try:
        deleted = delete_session(session_id)
    except SessionError as exc:
        raise _unavailable(exc) from exc
    return {'ok': bool(deleted), 'session_id': session_id}
