"""当前记忆实现的离线回归测试。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.ai.agent.memory.manager import session_manager
from app.ai.agent.memory.save import redis_client, window_memory
from app.ai.agent.memory.save.long_memory import LongMemory


def test_session_reuses_memory_objects(monkeypatch):
    builder = SimpleNamespace(
        window_memory=SimpleNamespace(save=AsyncMock()),
        summary_memory=object(),
        long_memory=object(),
        profile_memory=object(),
        builder_prompt=AsyncMock(return_value='已保存的需求'),
    )
    factory = Mock(return_value=builder)
    monkeypatch.setattr(session_manager, 'PromptBuilder', factory)

    session = session_manager.SessionManager('s1', 'u1')
    factory.assert_called_once_with('s1', 'u1')
    for name in ('window_memory', 'summary_memory', 'long_memory', 'profile_memory'):
        assert getattr(session, name) is getattr(builder, name)

    asyncio.run(session.save('user', '900 元以内'))
    builder.window_memory.save.assert_awaited_once_with('user', '900 元以内')
    assert asyncio.run(session.build_prompt('u1', '手办')) == {
        'role': 'system', 'content': '已保存的需求',
    }


def test_redis_options_keep_environment_and_overrides(monkeypatch):
    for key, value in {
        'REDIS_HOST': 'localhost', 'REDIS_PORT': '6380',
        'REDIS_DB': '2', 'REDIS_PASSWORD': 'test-password',
    }.items():
        monkeypatch.setenv(key, value)
    factory = Mock()
    monkeypatch.setattr(redis_client.redis, 'StrictRedis', factory)

    redis_client.create_redis_client(host='memory.test', port=None, db=0)
    factory.assert_called_once_with(
        host='memory.test', port=6380, db=0, password='test-password',
        socket_timeout=3, decode_responses=True,
    )


@pytest.mark.parametrize('rows, expected', [
    ([], []),
    (['{"role": "user", "content": "手办"}'], [{'role': 'user', 'content': '手办'}]),
])
def test_window_reads_missing_or_saved_messages(monkeypatch, rows, expected):
    client = SimpleNamespace(lrange=AsyncMock(return_value=rows))
    monkeypatch.setattr(window_memory, 'create_redis_client', Mock(return_value=client))
    memory = window_memory.WindowMemory('s1')

    assert asyncio.run(memory.query()) == expected
    client.lrange.assert_awaited_once_with('window_memory:s1', 0, -1)


def test_long_memory_preserves_user_filter_and_arguments():
    memory = LongMemory.__new__(LongMemory)
    memory.collection = Mock()
    memory.collection.query.return_value = {'documents': [['喜欢耳机']]}
    memory.collection.get.return_value = {'ids': ['m1']}
    memory.collection.count.return_value = 8

    asyncio.run(memory.save(7, '喜欢耳机'))
    saved = memory.collection.add.call_args.kwargs
    assert saved['documents'] == ['喜欢耳机']
    assert saved['metadatas'] == [{'user_id': '7'}]
    assert len(saved['ids']) == 1

    assert asyncio.run(memory.query(7, '偏好')) == ['喜欢耳机']
    memory.collection.query.assert_called_once_with(
        query_texts=['偏好'], n_results=3, where={'user_id': '7'},
    )
    assert asyncio.run(memory.count(7)) == 1
    assert asyncio.run(memory.count()) == 8
    asyncio.run(memory.clear(7))
    memory.collection.get.assert_called_with(where={'user_id': '7'})
    memory.collection.delete.assert_called_once_with(ids=['m1'])


def test_long_memory_reports_dimension_error():
    memory = LongMemory.__new__(LongMemory)
    memory.collection = Mock()
    memory.collection.name = 'test-memory'
    memory.collection.add.side_effect = ValueError('Embedding dimension mismatch')

    with pytest.raises(RuntimeError, match='向量维度与已有集合不匹配'):
        asyncio.run(memory.save('u1', '偏好'))
