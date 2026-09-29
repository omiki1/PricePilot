"""get_current_user_id 依赖（omiki 2026-09-29）：所有新接口的「当前用户」都从这里来。

现在读 query / JSON body 里的 user_id（临时，可伪造）；接 token 后只改这一个函数，这组用例随之改写。
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.web.deps import get_current_user_id  # noqa: E402


class Body(BaseModel):
    title: str = ''


def _client():
    app = FastAPI()

    @app.get('/who')
    def who(user_id: str = Depends(get_current_user_id)):
        return {'user_id': user_id}

    @app.post('/who')
    def who_post(body: Body, user_id: str = Depends(get_current_user_id)):
        return {'user_id': user_id, 'title': body.title}

    return TestClient(app)


def test_reads_query():
    assert _client().get('/who', params={'user_id': ' 1001 '}).json() == {'user_id': '1001'}


def test_reads_json_body_and_body_still_parsed():
    body = _client().post('/who', json={'user_id': 'alice', 'title': 't'}).json()
    assert body == {'user_id': 'alice', 'title': 't'}


def test_query_wins_over_body():
    assert _client().post('/who?user_id=q', json={'user_id': 'b'}).json()['user_id'] == 'q'


def test_missing_or_blank_is_401():
    client = _client()
    assert client.get('/who').status_code == 401
    assert client.get('/who', params={'user_id': '   '}).status_code == 401
    assert client.post('/who', json={'title': 't'}).status_code == 401


def test_too_long_is_422():
    assert _client().get('/who', params={'user_id': 'x' * 65}).status_code == 422
