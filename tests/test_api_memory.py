"""记忆类 API：每条 API 一个独立测试。"""

from models.ai_memory import MemoryFragment

from tests.conftest import ESSAY


def _seed_memory(client, make_user, login, real_ai_settings):
    make_user('alice')
    login('alice')
    create = client.post('/api/writing', json={'title': '记忆测试作文', 'content': ESSAY})
    assert create.status_code == 201
    wid = create.get_json()['data']['writing']['id']
    chat = client.post(f'/api/writing/{wid}/ai-chat', json={'message': '请帮我优化第一段'})
    assert chat.status_code == 200


def test_memory_profile_get(client, make_user, login):
    make_user('alice')
    login('alice')
    res = client.get('/api/memory/profile')
    assert res.status_code == 200
    assert 'profile' in res.get_json()['data']


def test_memory_profile_put(client, make_user, login):
    make_user('alice')
    login('alice')
    res = client.put('/api/memory/profile', json={'writing_profile': {'style': 'narrative'}, 'knowledge_base': {'topic': 'rain'}})
    assert res.status_code == 200
    data = res.get_json()['data']
    assert 'profile' in data and 'knowledge_base' in data


def test_memory_fragments_get(client, make_user, login, real_ai_settings):
    _seed_memory(client, make_user, login, real_ai_settings)
    res = client.get('/api/memory/fragments')
    assert res.status_code == 200
    assert isinstance(res.get_json()['data']['fragments'], list)


def test_memory_fragment_delete(client, make_user, login, real_ai_settings):
    _seed_memory(client, make_user, login, real_ai_settings)
    fr = client.get('/api/memory/fragments').get_json()['data']['fragments']
    res = client.delete(f"/api/memory/fragments/{fr[0]['id']}")
    assert res.status_code == 200


def test_memory_aggregate(client, make_user, login, real_ai_settings):
    _seed_memory(client, make_user, login, real_ai_settings)
    res = client.get('/api/memory/aggregate?days=30')
    assert res.status_code == 200
    assert 'summary' in res.get_json()['data']


def test_memory_context(client, make_user, login, real_ai_settings):
    _seed_memory(client, make_user, login, real_ai_settings)
    res = client.get('/api/memory/context?q=第一段')
    assert res.status_code == 200
    assert 'context' in res.get_json()['data']


def test_memory_stats(client, make_user, login, real_ai_settings):
    _seed_memory(client, make_user, login, real_ai_settings)
    res = client.get('/api/memory/stats')
    assert res.status_code == 200
    data = res.get_json()['data']
    assert 'system_stats' in data and 'user_stats' in data


def test_memory_clear(client, make_user, login, real_ai_settings):
    _seed_memory(client, make_user, login, real_ai_settings)
    clear_profile = client.post('/api/memory/clear', json={'type': 'profile'})
    assert clear_profile.status_code == 200
    clear_fragments = client.post('/api/memory/clear', json={'type': 'fragments'})
    assert clear_fragments.status_code == 200
    assert MemoryFragment.query.count() == 0
