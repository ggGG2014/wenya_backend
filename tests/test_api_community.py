"""社区类 API：每条 API 一个独立测试。"""

from app import db
from models.community import CommunityWork


def _prepare_published_work(client, app, make_user, login, scored_writing_real):
    app.config['COMMUNITY_AUTO_APPROVE'] = True
    make_user('alice', grade=8, nickname='小A')
    login('alice')
    writing = scored_writing_real(title='社区发布作文')
    publish = client.post(f'/api/community/publish/{writing["id"]}', json={'genre': '记叙文', 'tags': ['成长']})
    assert publish.status_code == 201, publish.get_json()
    return publish.get_json()['data']['work']['id']


def test_community_works(client):
    res = client.get('/api/community/works')
    assert res.status_code == 200
    assert isinstance(res.get_json()['data'], list)


def test_community_work_detail(client, app, make_user, login, scored_writing_real):
    work_id = _prepare_published_work(client, app, make_user, login, scored_writing_real)
    res = client.get(f'/api/community/works/{work_id}')
    assert res.status_code == 200
    assert res.get_json()['data']['work']['id'] == work_id


def test_community_like(client, app, make_user, login, scored_writing_real):
    work_id = _prepare_published_work(client, app, make_user, login, scored_writing_real)
    client.post('/api/auth/logout')
    make_user('bob', grade=8, nickname='小B')
    login('bob')
    res = client.post(f'/api/community/works/{work_id}/like')
    assert res.status_code == 200
    assert res.get_json()['data']['is_liked'] is True


def test_community_comment(client, app, make_user, login, scored_writing_real):
    work_id = _prepare_published_work(client, app, make_user, login, scored_writing_real)
    client.post('/api/auth/logout')
    make_user('bob', grade=8, nickname='小B')
    login('bob')
    res = client.post(f'/api/community/works/{work_id}/comment', json={'content': '写得很好，结构清楚。'})
    assert res.status_code == 201


def test_community_comments(client, app, make_user, login, scored_writing_real):
    work_id = _prepare_published_work(client, app, make_user, login, scored_writing_real)
    res = client.get(f'/api/community/works/{work_id}/comments')
    assert res.status_code == 200
    assert isinstance(res.get_json()['data']['comments'], list)


def test_community_delete_comment(client, app, make_user, login, scored_writing_real):
    work_id = _prepare_published_work(client, app, make_user, login, scored_writing_real)
    client.post('/api/auth/logout')
    make_user('bob', grade=8, nickname='小B')
    login('bob')
    comment = client.post(f'/api/community/works/{work_id}/comment', json={'content': '写得很好，结构清楚。'})
    cid = comment.get_json()['data']['comment']['id']
    res = client.delete(f'/api/community/works/{work_id}/comments/{cid}')
    assert res.status_code == 200


def test_community_report_post(client, app, make_user, login, scored_writing_real):
    work_id = _prepare_published_work(client, app, make_user, login, scored_writing_real)
    client.post('/api/auth/logout')
    make_user('bob', grade=8, nickname='小B')
    login('bob')
    res = client.post(
        f'/api/community/works/{work_id}/report',
        json={'reason': 'spam', 'description': '疑似垃圾信息'}
    )
    assert res.status_code == 201, res.get_json()


def test_community_report_get(client, app, make_user, login, scored_writing_real):
    work_id = _prepare_published_work(client, app, make_user, login, scored_writing_real)
    client.post('/api/auth/logout')
    make_user('bob', grade=8, nickname='小B')
    login('bob')
    client.post(f'/api/community/works/{work_id}/report', json={'reason': 'spam'})
    res = client.get(f'/api/community/works/{work_id}/report')
    assert res.status_code == 200
    assert res.get_json()['data']['report'] is not None


def test_community_publish(client, app, make_user, login, scored_writing_real):
    app.config['COMMUNITY_AUTO_APPROVE'] = True
    make_user('alice', grade=8, nickname='小A')
    login('alice')
    writing = scored_writing_real(title='发布测试作文')
    res = client.post(f'/api/community/publish/{writing["id"]}', json={'genre': '记叙文'})
    assert res.status_code == 201, res.get_json()


def test_community_featured(client, app, make_user, login, scored_writing_real):
    work_id = _prepare_published_work(client, app, make_user, login, scored_writing_real)
    with app.app_context():
        cw = CommunityWork.query.get(work_id)
        cw.is_featured = True
        db.session.commit()
    res = client.get('/api/community/featured')
    assert res.status_code == 200
    assert 'pagination' in res.get_json()
