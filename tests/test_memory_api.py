"""AI 记忆：对话写入记忆片段、查询、删除、清空"""
from models.ai_memory import MemoryFragment
from tests.conftest import ESSAY


def _chat(client, message):
    wid = client.post('/api/writing', json={'title': '记忆测试', 'content': ESSAY}).get_json()['data']['writing']['id']
    res = client.post(f'/api/writing/{wid}/ai-chat', json={'message': message})
    assert res.status_code == 200, res.get_json()
    return wid


def test_chat_persists_memory_and_recalls_it(client, make_user, login, ai_reply):
    make_user('alice')
    login('alice')
    calls = ai_reply('议论文要先亮明观点。')
    _chat(client, '议论文怎么写开头')

    fragments = client.get('/api/memory/fragments').get_json()['data']['fragments']
    assert {f['content'] for f in fragments} == {'用户提问：议论文怎么写开头', 'AI 回复：议论文要先亮明观点。'}

    # 下一次对话时，相关记忆被注入到发送给模型的上下文中
    _chat(client, '议论文的论据怎么选')
    memory_msgs = [m['content'] for m in calls[-1] if m['role'] == 'system' and '【相关记忆】' in m['content']]
    assert memory_msgs and '议论文怎么写开头' in memory_msgs[0]


def test_delete_and_clear_fragments(client, make_user, login, ai_reply):
    make_user('alice')
    make_user('bob')
    login('alice')
    ai_reply('好的')
    _chat(client, '帮我看看结构')

    fragments = client.get('/api/memory/fragments').get_json()['data']['fragments']
    assert client.delete(f'/api/memory/fragments/{fragments[0]["id"]}').status_code == 200
    assert client.delete('/api/memory/fragments/not-exist').status_code == 404
    assert len(client.get('/api/memory/fragments').get_json()['data']['fragments']) == 1

    # 其他用户不能删除
    client.post('/api/auth/logout')
    login('bob')
    assert client.delete(f'/api/memory/fragments/{fragments[1]["id"]}').status_code == 404
    client.post('/api/auth/logout')

    login('alice')
    assert client.post('/api/memory/clear', json={'type': 'fragments'}).status_code == 200
    assert MemoryFragment.query.count() == 0
    assert client.post('/api/memory/clear', json={'type': 'bogus'}).status_code == 400
