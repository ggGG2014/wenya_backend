"""写作类 API：每条 API 一个独立测试。"""

from tests.conftest import ESSAY


def _create_writing(client, title='测试作文', content=ESSAY, prompt='测试题目'):
    res = client.post('/api/writing', json={'title': title, 'content': content, 'prompt': prompt})
    assert res.status_code == 201, res.get_json()
    return res.get_json()['data']['writing']['id']


def test_writing_create(client, make_user, login):
    make_user('alice')
    login('alice')
    wid = _create_writing(client)
    assert isinstance(wid, int)


def test_writing_get_detail(client, make_user, login):
    make_user('alice')
    login('alice')
    wid = _create_writing(client)
    res = client.get(f'/api/writing/{wid}')
    assert res.status_code == 200
    assert res.get_json()['data']['writing']['id'] == wid


def test_writing_update(client, make_user, login):
    make_user('alice')
    login('alice')
    wid = _create_writing(client, content='第一版')
    res = client.put(f'/api/writing/{wid}', json={'title': '新标题', 'content': '第二版'})
    assert res.status_code == 200
    assert res.get_json()['data']['writing']['title'] == '新标题'


def test_writing_delete(client, make_user, login):
    make_user('alice')
    login('alice')
    wid = _create_writing(client)
    res = client.delete(f'/api/writing/{wid}')
    assert res.status_code == 200
    assert client.get(f'/api/writing/{wid}').status_code == 404


def test_writing_submit(client, make_user, login, real_ai_settings):
    make_user('alice')
    login('alice')
    wid = _create_writing(client)
    res = client.post(f'/api/writing/{wid}/submit')
    assert res.status_code == 200, res.get_json()
    data = res.get_json()['data']
    assert data['is_mock'] is False
    assert data['writing']['is_scored'] is True


def test_writing_save_draft(client, make_user, login):
    make_user('alice')
    login('alice')
    wid = _create_writing(client, content='第一版')
    res = client.post(f'/api/writing/{wid}/draft', json={'content': '第二版', 'title': '草稿标题'})
    assert res.status_code == 200
    assert res.get_json()['data']['version'] >= 2


def test_writing_list_drafts(client, make_user, login):
    make_user('alice')
    login('alice')
    wid = _create_writing(client, content='第一版')
    client.post(f'/api/writing/{wid}/draft', json={'content': '第二版'})
    res = client.get(f'/api/writing/{wid}/drafts')
    assert res.status_code == 200
    assert len(res.get_json()['data']['drafts']) >= 1


def test_writing_ai_chat_history(client, make_user, login, real_ai_settings):
    make_user('alice')
    login('alice')
    wid = _create_writing(client)
    res = client.get(f'/api/writing/{wid}/ai-chat')
    assert res.status_code == 200
    assert isinstance(res.get_json()['data']['messages'], list)


def test_writing_ai_chat(client, make_user, login, real_ai_settings):
    make_user('alice')
    login('alice')
    wid = _create_writing(client)
    res = client.post(f'/api/writing/{wid}/ai-chat', json={'message': '请给出一个写作建议'})
    assert res.status_code == 200, res.get_json()
    data = res.get_json()['data']
    assert data['is_mock'] is False
    assert isinstance(data['response'], str) and data['response'].strip()


def test_writing_list(client, make_user, login):
    make_user('alice')
    login('alice')
    _create_writing(client, title='A')
    _create_writing(client, title='B')
    res = client.get('/api/writing')
    assert res.status_code == 200
    assert len(res.get_json()['data']) >= 2
