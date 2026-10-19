"""写作：创建、保存草稿、提交评分、AI 对话、删除"""
from models.writing import Writing, WritingScore, WritingDraft
from tests.conftest import ESSAY, SCORE_JSON


def _create(client, title='测试作文', content=ESSAY):
    res = client.post('/api/writing', json={'title': title, 'content': content})
    assert res.status_code == 201, res.get_json()
    return res.get_json()['data']['writing']['id']


def test_create_and_get(client, make_user, login):
    make_user('alice')
    login('alice')
    wid = _create(client, content='短短的开头')
    writing = client.get(f'/api/writing/{wid}').get_json()['data']['writing']
    assert writing['status'] == 'draft'
    assert writing['content'] == '短短的开头'


def test_save_draft_updates_title_prompt_and_versions(client, make_user, login):
    make_user('alice')
    login('alice')
    wid = _create(client, content='第一版')

    res = client.post(f'/api/writing/{wid}/draft',
                      json={'title': '新标题', 'prompt': '写一件难忘的事', 'content': '第二版内容'})
    assert res.status_code == 200, res.get_json()
    assert res.get_json()['data']['version'] == 2

    # 内容不变只改标题：不新增版本
    res = client.post(f'/api/writing/{wid}/draft', json={'title': '再改标题', 'content': '第二版内容'})
    assert res.get_json()['data']['version'] == 2

    writing = client.get(f'/api/writing/{wid}').get_json()['data']['writing']
    assert writing['title'] == '再改标题'
    assert writing['prompt'] == '写一件难忘的事'
    assert writing['content'] == '第二版内容'
    assert len(client.get(f'/api/writing/{wid}/drafts').get_json()['data']['drafts']) == 2


def test_save_draft_validation(client, make_user, login):
    make_user('alice')
    login('alice')
    wid = _create(client)
    assert client.post(f'/api/writing/{wid}/draft', json={'content': '   '}).status_code == 400
    assert client.post(f'/api/writing/{wid}/draft', json={'title': '', 'content': '有内容'}).status_code == 400
    # 敏感内容被拦截
    assert client.post(f'/api/writing/{wid}/draft', json={'content': '这里有赌博内容'}).status_code == 403


def test_cannot_edit_other_users_writing(client, make_user, login):
    make_user('alice')
    make_user('bob')
    login('alice')
    wid = _create(client)
    client.post('/api/auth/logout')
    login('bob')
    assert client.get(f'/api/writing/{wid}').status_code == 404
    assert client.post(f'/api/writing/{wid}/draft', json={'content': '篡改'}).status_code == 404


def test_submit_requires_min_words(client, make_user, login, ai_reply):
    make_user('alice')
    login('alice')
    ai_reply(SCORE_JSON)
    wid = _create(client, content='太短了')
    res = client.post(f'/api/writing/{wid}/submit')
    assert res.status_code == 400
    assert '100' in res.get_json()['error']


def test_submit_success_saves_scores(app, client, make_user, login, ai_reply):
    make_user('alice')
    login('alice')
    calls = ai_reply(SCORE_JSON)
    wid = _create(client)

    res = client.post(f'/api/writing/{wid}/submit')
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    writing = body['data']['writing']
    assert body['data']['is_mock'] is False
    assert writing['status'] == 'submitted'
    assert writing['scores']['language_score'] == 88
    assert writing['overall_score'] > 0
    assert len(calls) == 1  # 实际调用了模型

    # 不能重复提交，也不能再修改
    assert client.post(f'/api/writing/{wid}/submit').status_code == 400
    assert client.post(f'/api/writing/{wid}/draft', json={'content': '改一下'}).status_code == 400


def test_submit_ai_failure_keeps_draft_and_saves_nothing(app, client, make_user, login, ai_reply):
    make_user('alice')
    login('alice')
    ai_reply(error=True)
    wid = _create(client)

    res = client.post(f'/api/writing/{wid}/submit')
    assert res.status_code == 503
    writing = Writing.query.get(wid)
    assert writing.status == 'draft'
    assert writing.is_scored is False
    assert WritingScore.query.count() == 0


def test_submit_invalid_ai_json_is_rejected(client, make_user, login, ai_reply):
    make_user('alice')
    login('alice')
    ai_reply('{"task_score": 80}')  # 缺少维度
    wid = _create(client)
    assert client.post(f'/api/writing/{wid}/submit').status_code == 503
    assert WritingScore.query.count() == 0


def test_ai_chat_and_history(client, make_user, login, ai_reply):
    make_user('alice')
    login('alice')
    calls = ai_reply('先想一想你最想表达的感受是什么？')
    wid = _create(client)

    res = client.post(f'/api/writing/{wid}/ai-chat', json={'message': '怎么开头', 'session_type': 'brainstorming'})
    assert res.status_code == 200, res.get_json()
    assert res.get_json()['data']['response'] == '先想一想你最想表达的感受是什么？'
    # 发给模型的历史消息只包含 role/content
    assert all(set(m.keys()) == {'role', 'content'} for m in calls[0])

    history = client.get(f'/api/writing/{wid}/ai-chat').get_json()['data']['messages']
    assert [m['role'] for m in history] == ['user', 'assistant']
    assert history[0]['content'] == '怎么开头'


def test_ai_chat_failure_returns_503(client, make_user, login, ai_reply):
    make_user('alice')
    login('alice')
    ai_reply(error=True)
    wid = _create(client)
    assert client.post(f'/api/writing/{wid}/ai-chat', json={'message': '你好'}).status_code == 503
    assert client.get(f'/api/writing/{wid}/ai-chat').get_json()['data']['messages'] == []


def test_delete_writing(client, make_user, login):
    make_user('alice')
    login('alice')
    wid = _create(client)
    assert client.delete(f'/api/writing/{wid}').status_code == 200
    assert client.get(f'/api/writing/{wid}').status_code == 404
    assert client.get('/api/writing').get_json()['data'] == []


def test_list_filters_by_status(client, make_user, login, scored_writing):
    make_user('alice')
    login('alice')
    scored_writing()
    _create(client, title='草稿一篇')
    drafts = client.get('/api/writing?status=draft').get_json()['data']
    assert [w['title'] for w in drafts] == ['草稿一篇']
    assert len(client.get('/api/writing').get_json()['data']) == 2
