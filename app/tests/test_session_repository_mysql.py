"""session_repository 真库集成用例（omiki 2026-09-29）

默认跳过；要跑时设置 PRICEPILOT_TEST_MYSQL=1 和 MYSQL_HOST / MYSQL_PORT / MYSQL_USER /
MYSQL_PASSWORD / MYSQL_DATABASE / MYSQL_CHARSET（和 .env 同名，建议指向一个测试库）。
会从 db/schema_mysql.sql 里取 chat_session / chat_message 两段 DDL 建表（IF NOT EXISTS），
用例结束删掉本次写入的行。

    PRICEPILOT_TEST_MYSQL=1 MYSQL_DATABASE=pricepilot_test ... pytest app/tests/test_session_repository_mysql.py
"""
from __future__ import annotations

import os
import re
import sys
import uuid

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest  # noqa: E402

pytestmark = pytest.mark.skipif(os.getenv('PRICEPILOT_TEST_MYSQL') != '1',
                                reason='未设置 PRICEPILOT_TEST_MYSQL=1，跳过真库用例')

from app.ai.tool import session_repository as repo  # noqa: E402
from app.ai.tool.mysql_tool import MySQL  # noqa: E402


def _ddl(table: str) -> str:
    with open(os.path.join(_REPO_ROOT, 'db', 'schema_mysql.sql'), encoding='utf-8') as handle:
        sql = handle.read()
    match = re.search(r'CREATE TABLE IF NOT EXISTS ' + table + r' \(.*?\)[^;]*;', sql, re.S)
    assert match, table
    return match.group(0)


@pytest.fixture
def users():
    conn = MySQL.get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(_ddl('chat_session'))
            cursor.execute(_ddl('chat_message'))
        conn.commit()
    finally:
        conn.close()
    tag = uuid.uuid4().hex[:8]
    alice, bob = f'it-alice-{tag}', f'it-bob-{tag}'
    yield alice, bob
    conn = MySQL.get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE m FROM chat_message m JOIN chat_session s ON s.session_id = m.session_id "
                           "WHERE s.user_id IN (%s, %s)", (alice, bob))
            cursor.execute("DELETE FROM chat_session WHERE user_id IN (%s, %s)", (alice, bob))
        conn.commit()
    finally:
        conn.close()


def test_roundtrip_on_real_mysql(users):
    alice, bob = users
    created = repo.create_session(alice)
    sid = created['session_id']
    assert created['title'] is None
    assert repo.check_owner(sid, alice) == 'ok'
    assert repo.check_owner(sid, bob) == 'forbidden'

    products = [{'product_id': 'p1', 'title': 'K380 键盘', 'price_text': 'USD 29.99 / 人民币 ≈ ¥212.93'}]
    repo.append_turn(sid, '  适合通勤的降噪耳机，预算 1000，最好轻一点  ', '推荐三款', products)
    session = repo.get_session(sid)
    assert session['title'] == '适合通勤的降噪耳机，预算 1000，最好…'
    assert len(session['title']) == 21
    messages = repo.list_messages(sid)
    assert [m['role'] for m in messages] == ['user', 'assistant']
    assert messages[1]['products'] == products          # JSON 列原样读回（含中文）
    assert messages[0]['products'] == []

    repo.rename_session(sid, '耳机')
    repo.append_turn(sid, '再便宜点', '好的', None)
    assert repo.get_session(sid)['title'] == '耳机'      # 已重命名的标题不被自动标题覆盖

    other = repo.create_session(alice)
    assert [s['session_id'] for s in repo.list_sessions(alice)] == [other['session_id'], sid]
    repo.append_turn(sid, '还在吗', '在', None)            # 新一轮把旧会话顶到最前
    assert [s['session_id'] for s in repo.list_sessions(alice)] == [sid, other['session_id']]
    assert repo.list_sessions(bob) == []

    assert repo.delete_session(sid) == 1
    assert repo.check_owner(sid, alice) == 'deleted'
    assert sid not in [s['session_id'] for s in repo.list_sessions(alice)]
    assert len(repo.list_messages(sid)) == 6             # 软删除：消息行还在


def test_ensure_session_lazily_creates_and_blocks_other_owner(users):
    alice, bob = users
    sid = uuid.uuid4().hex
    assert repo.ensure_session(sid, alice) == 'ok'
    assert repo.get_session(sid)['user_id'] == alice
    assert repo.ensure_session(sid, bob) == 'forbidden'   # INSERT IGNORE 不会改归属
    assert repo.get_session(sid)['user_id'] == alice
