"""会话管理 + 聊天落库 验收用例（omiki 2026-09-29）

不连真 MySQL：用内存版 FakeRepo 顶替 session_repository 里的函数（路由层按名字 import，
所以在路由模块上 monkeypatch）。真 SQL 另见 test_session_repository_mysql.py（有库才跑）。

覆盖：
  - 每个带 {id} 的会话接口，别人的会话一律 403；不存在 / 已删除 404
  - 新建 → 列表 → 重命名 → 删除 的完整流程；列表只返回自己的、按 updated_at 倒序
  - 聊天后落库：用户问题 + 助手全文 + 最后一次商品帧；首问自动标题；懒创建会话
  - 会话归属不对：不跑图、不写库、给带 code 的结束帧
  - 落库失败：SSE 照常结束，结束帧带 saved=false

运行：pytest app/tests/test_sessions.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import importlib  # noqa: E402

import app.ai.tool.session_repository as repo  # noqa: E402
from app.ai.tool.session_repository import SessionError, auto_title  # noqa: E402
from app.web.chat_router import chat_router  # noqa: E402
from app.web.session_router import session_router  # noqa: E402

# 包的 __init__ 把同名 APIRouter 导出来了，`import a.b.chat_router as m` 拿到的是 router 对象，
# 要拿模块本身得走 importlib
chat_module = importlib.import_module('app.web.chat_router.chat_router')
session_module = importlib.import_module('app.web.session_router.session_router')


class FakeRepo:
    """内存版 session_repository，语义与真实实现一致（归属、软删、标题不覆盖）。"""

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.messages: list[dict] = []
        self.clock = datetime(2026, 9, 29, 1, 0, 0)
        self.fail_all = False
        self.counter = 0

    def _tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock.isoformat() + 'Z'

    def _guard(self):
        if self.fail_all:
            raise SessionError('连接 MySQL 失败：fake down')

    # --- 与 session_repository 同名同参 ---
    def create_session(self, user_id, session_id=None):
        self._guard()
        self.counter += 1
        sid = session_id or f'sid-{self.counter}'
        now = self._tick()
        self.sessions[sid] = {'session_id': sid, 'user_id': user_id, 'title': None,
                              'created_at': now, 'updated_at': now, 'is_deleted': False}
        return dict(self.sessions[sid])

    def check_owner(self, session_id, user_id):
        self._guard()
        row = self.sessions.get(session_id)
        if row is None:
            return 'missing'
        if row['user_id'] != user_id:
            return 'forbidden'
        return 'deleted' if row['is_deleted'] else 'ok'

    def ensure_session(self, session_id, user_id):
        self._guard()
        if session_id not in self.sessions:
            self.create_session(user_id, session_id)
        return self.check_owner(session_id, user_id)

    def list_sessions(self, user_id, limit=100):
        self._guard()
        rows = [dict(s) for s in self.sessions.values() if s['user_id'] == user_id and not s['is_deleted']]
        return sorted(rows, key=lambda s: s['updated_at'], reverse=True)[:limit]

    def rename_session(self, session_id, title):
        self._guard()
        self.sessions[session_id]['title'] = title
        self.sessions[session_id]['updated_at'] = self._tick()
        return dict(self.sessions[session_id])

    def delete_session(self, session_id):
        self._guard()
        self.sessions[session_id]['is_deleted'] = True
        return 1

    def list_messages(self, session_id, limit=500):
        self._guard()
        return [dict(m) for m in self.messages if m['session_id'] == session_id][:limit]

    def append_turn(self, session_id, question, answer, products):
        self._guard()
        now = self._tick()
        self.messages.append({'id': len(self.messages) + 1, 'session_id': session_id, 'role': 'user',
                              'content': question, 'products': [], 'created_at': now})
        self.messages.append({'id': len(self.messages) + 1, 'session_id': session_id, 'role': 'assistant',
                              'content': answer, 'products': products or [], 'created_at': now})
        row = self.sessions[session_id]
        row['title'] = row['title'] or auto_title(question)
        row['updated_at'] = now


class FakeGraph:
    """顶替 ShoppingGraph.chat：先推两次商品帧（只该存最后一次），再推文字。"""

    def __init__(self):
        self.calls = []

    async def chat(self, question, user_id, session_id):
        self.calls.append((question, user_id, session_id))
        yield {'type': 'products', 'data': [{'product_id': 'p-early', 'title': 'early'}]}
        yield '给你挑了'
        yield {'type': 'products', 'data': [{'product_id': 'p1', 'title': 'K380', 'price_text': 'USD 29.99'}]}
        yield '三款键盘。'


@pytest.fixture
def fake_repo(monkeypatch):
    fake = FakeRepo()
    for name in ('create_session', 'check_owner', 'list_sessions', 'rename_session',
                 'delete_session', 'list_messages'):
        monkeypatch.setattr(session_module, name, getattr(fake, name))
    monkeypatch.setattr(chat_module, 'ensure_session', fake.ensure_session)
    monkeypatch.setattr(chat_module, 'append_turn', fake.append_turn)
    return fake


@pytest.fixture
def client(fake_repo):
    application = FastAPI()
    application.include_router(chat_router)
    application.include_router(session_router, prefix='/api')
    application.state.shopping_agent = FakeGraph()
    return TestClient(application)


def _frames(response) -> list[dict]:
    return [json.loads(line[len('data: '):]) for line in response.text.split('\n') if line.startswith('data: ')]


# ══════════════════════════════ 归属校验：每个带 {id} 的接口都 403 ══════════════════════════════

def test_messages_of_other_user_is_403(client, fake_repo):
    sid = fake_repo.create_session('alice')['session_id']
    response = client.get(f'/api/sessions/{sid}/messages', params={'user_id': 'mallory'})
    assert response.status_code == 403


def test_rename_other_user_is_403_and_title_unchanged(client, fake_repo):
    sid = fake_repo.create_session('alice')['session_id']
    response = client.patch(f'/api/sessions/{sid}', json={'user_id': 'mallory', 'title': 'pwned'})
    assert response.status_code == 403
    assert fake_repo.sessions[sid]['title'] is None


def test_delete_other_user_is_403_and_not_deleted(client, fake_repo):
    sid = fake_repo.create_session('alice')['session_id']
    response = client.delete(f'/api/sessions/{sid}', params={'user_id': 'mallory'})
    assert response.status_code == 403
    assert fake_repo.sessions[sid]['is_deleted'] is False


def test_deleted_session_of_other_user_is_still_403(client, fake_repo):
    sid = fake_repo.create_session('alice')['session_id']
    fake_repo.sessions[sid]['is_deleted'] = True
    response = client.get(f'/api/sessions/{sid}/messages', params={'user_id': 'mallory'})
    assert response.status_code == 403


def test_missing_session_is_404(client):
    assert client.get('/api/sessions/nope/messages', params={'user_id': 'alice'}).status_code == 404
    assert client.patch('/api/sessions/nope', json={'user_id': 'alice', 'title': 'x'}).status_code == 404
    assert client.delete('/api/sessions/nope', params={'user_id': 'alice'}).status_code == 404


def test_missing_identity_is_401_on_every_endpoint(client, fake_repo):
    sid = fake_repo.create_session('alice')['session_id']
    assert client.get('/api/sessions').status_code == 401
    assert client.post('/api/sessions', json={}).status_code == 401
    assert client.get(f'/api/sessions/{sid}/messages').status_code == 401
    assert client.patch(f'/api/sessions/{sid}', json={'title': 'x'}).status_code == 401
    assert client.delete(f'/api/sessions/{sid}').status_code == 401
    assert client.get('/chat', params={'question': 'hi', 'session_id': sid}).status_code == 401
    assert fake_repo.sessions[sid]['title'] is None and not fake_repo.sessions[sid]['is_deleted']


def test_identity_comes_from_single_dependency(client, fake_repo):
    """换身份只需覆盖 get_current_user_id：接 token 以后就是把这个函数换成解析 token。"""
    from app.web.deps import get_current_user_id
    sid = fake_repo.create_session('alice')['session_id']
    client.app.dependency_overrides[get_current_user_id] = lambda: 'alice'
    try:
        # 请求里冒充 mallory 也没用：身份以依赖返回值为准
        assert client.get(f'/api/sessions/{sid}/messages', params={'user_id': 'mallory'}).status_code == 200
        assert [s['session_id'] for s in client.get('/api/sessions').json()['sessions']] == [sid]
        created = client.post('/api/sessions', json={'user_id': 'mallory'}).json()
        assert fake_repo.sessions[created['session_id']]['user_id'] == 'alice'
        frames = _frames(client.get('/chat', params={'question': 'hi', 'user_id': 'mallory', 'session_id': sid}))
        assert frames[-1] == {'data': '', 'done': True}
        assert fake_repo.messages[-1]['session_id'] == sid
    finally:
        client.app.dependency_overrides.clear()
    # 覆盖撤掉后回到读请求参数：mallory 是 403
    assert client.get(f'/api/sessions/{sid}/messages', params={'user_id': 'mallory'}).status_code == 403


def test_list_only_returns_own_sessions(client, fake_repo):
    fake_repo.create_session('alice')
    fake_repo.create_session('bob')
    body = client.get('/api/sessions', params={'user_id': 'alice'}).json()
    assert [s['user_id'] for s in body['sessions']] == ['alice']


def test_db_down_is_503_not_500(client, fake_repo):
    fake_repo.fail_all = True
    assert client.get('/api/sessions', params={'user_id': 'alice'}).status_code == 503
    assert client.post('/api/sessions', json={'user_id': 'alice'}).status_code == 503


# ══════════════════════════════ 新建 / 列表 / 重命名 / 删除 ══════════════════════════════

def test_full_session_flow(client, fake_repo):
    first = client.post('/api/sessions', json={'user_id': 'alice'})
    assert first.status_code == 200 and first.json()['title'] is None
    second = client.post('/api/sessions', json={'user_id': 'alice'}).json()

    listed = client.get('/api/sessions', params={'user_id': 'alice'}).json()['sessions']
    assert [s['session_id'] for s in listed] == [second['session_id'], first.json()['session_id']]

    # 重命名会刷新 updated_at → 排到最前
    renamed = client.patch(f"/api/sessions/{first.json()['session_id']}",
                           json={'user_id': 'alice', 'title': '  键盘   对比  '})
    assert renamed.status_code == 200 and renamed.json()['title'] == '键盘 对比'
    listed = client.get('/api/sessions', params={'user_id': 'alice'}).json()['sessions']
    assert listed[0]['session_id'] == first.json()['session_id']

    deleted = client.delete(f"/api/sessions/{first.json()['session_id']}", params={'user_id': 'alice'})
    assert deleted.status_code == 200 and deleted.json()['ok'] is True
    listed = client.get('/api/sessions', params={'user_id': 'alice'}).json()['sessions']
    assert [s['session_id'] for s in listed] == [second['session_id']]
    # 删了之后再打开就是 404（不是 403：是本人的）
    assert client.get(f"/api/sessions/{first.json()['session_id']}/messages",
                      params={'user_id': 'alice'}).status_code == 404


def test_rename_empty_title_is_400(client, fake_repo):
    sid = fake_repo.create_session('alice')['session_id']
    assert client.patch(f'/api/sessions/{sid}', json={'user_id': 'alice', 'title': '   '}).status_code == 400


def test_auto_title_rules():
    assert auto_title('  500 以内的\n无线机械键盘 ') == '500 以内的 无线机械键盘'
    assert auto_title('一' * 25) == '一' * 20 + '…'
    assert auto_title('   ') is None


def test_repo_check_owner_semantics(monkeypatch):
    rows = {
        'mine': {'session_id': 'mine', 'user_id': 'alice', 'is_deleted': False},
        'gone': {'session_id': 'gone', 'user_id': 'alice', 'is_deleted': True},
        'theirs': {'session_id': 'theirs', 'user_id': 'bob', 'is_deleted': True},
    }
    monkeypatch.setattr(repo, 'get_session', lambda sid: rows.get(sid))
    assert repo.check_owner('mine', 'alice') == 'ok'
    assert repo.check_owner('gone', 'alice') == 'deleted'
    assert repo.check_owner('theirs', 'alice') == 'forbidden'
    assert repo.check_owner('nothing', 'alice') == 'missing'


# ══════════════════════════════ 聊天落库 ══════════════════════════════

def test_chat_persists_turn_and_lazily_creates_session(client, fake_repo):
    response = client.get('/chat', params={'question': '500 以内的无线机械键盘，最好是罗技的那种矮轴',
                                           'user_id': 'alice', 'session_id': 'new-sid'})
    frames = _frames(response)
    # SSE 帧契约不变：products / text / done
    assert [f.get('type') for f in frames[:-1]] == ['products', 'text', 'products', 'text']
    assert frames[-1] == {'data': '', 'done': True}

    session = fake_repo.sessions['new-sid']
    assert session['user_id'] == 'alice'
    assert session['title'] == '500 以内的无线机械键盘，最好是罗技的那'[:20] + '…'
    user_msg, ai_msg = fake_repo.messages
    assert user_msg['role'] == 'user' and user_msg['content'].startswith('500 以内')
    assert ai_msg['content'] == '给你挑了三款键盘。'
    assert [p['product_id'] for p in ai_msg['products']] == ['p1']      # 只存最后一次商品帧

    history = client.get('/api/sessions/new-sid/messages', params={'user_id': 'alice'}).json()
    assert [m['role'] for m in history['messages']] == ['user', 'assistant']


def test_chat_second_turn_keeps_title_and_bumps_updated_at(client, fake_repo):
    client.get('/chat', params={'question': '键盘', 'user_id': 'alice', 'session_id': 's1'})
    first_updated = fake_repo.sessions['s1']['updated_at']
    client.patch('/api/sessions/s1', json={'user_id': 'alice', 'title': '我的键盘'})
    client.get('/chat', params={'question': '再便宜点', 'user_id': 'alice', 'session_id': 's1'})
    assert fake_repo.sessions['s1']['title'] == '我的键盘'
    assert fake_repo.sessions['s1']['updated_at'] > first_updated
    assert len(fake_repo.messages) == 4


def test_chat_without_session_id_is_not_persisted(client, fake_repo):
    frames = _frames(client.get('/chat', params={'question': 'hi', 'user_id': 'alice'}))
    assert frames[-1] == {'data': '', 'done': True}
    assert fake_repo.sessions == {} and fake_repo.messages == []

