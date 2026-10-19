"""社区：发布、列表、评论、点赞"""


def _publish(client, writing_id, **payload):
    return client.post(f'/api/community/publish/{writing_id}', json=payload)


def test_publish_requires_scored_writing(client, make_user, login):
    make_user('alice')
    login('alice')
    wid = client.post('/api/writing', json={'title': '草稿', 'content': '还没写完'}).get_json()['data']['writing']['id']
    assert _publish(client, wid).status_code == 400


def test_publish_pending_without_auto_approve(app, client, make_user, login, scored_writing):
    make_user('alice')
    login('alice')
    writing = scored_writing()
    res = _publish(client, writing['id'], genre='记叙文')
    assert res.status_code == 201
    assert res.get_json()['data']['work']['review_status'] == 'pending'
    assert client.get('/api/community/works').get_json()['data'] == []
    assert _publish(client, writing['id']).status_code == 409  # 不能重复发布


def test_publish_auto_approve_lists_with_excerpt_and_search(app, client, make_user, login, scored_writing):
    app.config['COMMUNITY_AUTO_APPROVE'] = True
    make_user('alice')
    login('alice')
    writing = scored_writing('长跑的冬天')
    res = _publish(client, writing['id'], genre='记叙文')
    assert res.get_json()['data']['work']['review_status'] == 'approved'

    works = client.get('/api/community/works').get_json()['data']
    assert len(works) == 1
    assert works[0]['excerpt'].startswith('去年冬天')
    assert works[0]['genre'] == '记叙文'
    assert len(client.get('/api/community/works?q=长跑').get_json()['data']) == 1
    assert client.get('/api/community/works?q=不存在').get_json()['data'] == []

    detail = client.get(f'/api/writing/{writing["id"]}').get_json()['data']['writing']
    assert detail['status'] == 'published'
    assert detail['community_work']['review_status'] == 'approved'


def test_hidden_when_author_disables_public_works(app, client, make_user, login, scored_writing):
    app.config['COMMUNITY_AUTO_APPROVE'] = True
    make_user('alice')
    login('alice')
    _publish(client, scored_writing()['id'])
    assert len(client.get('/api/community/works').get_json()['data']) == 1
    client.put('/api/auth/profile', json={'show_works_publicly': False})
    assert client.get('/api/community/works').get_json()['data'] == []


def test_short_comment_reply_and_delete(app, client, make_user, login, scored_writing):
    app.config['COMMUNITY_AUTO_APPROVE'] = True
    make_user('alice', nickname='小A')
    make_user('bob', nickname='小B')
    login('alice')
    work_id = _publish(client, scored_writing()['id']).get_json()['data']['work']['id']
    client.post('/api/auth/logout')

    login('bob')
    # 回归：短评论曾被内容安全检查判为"内容过短"；parent_id 解析曾导致 500
    res = client.post(f'/api/community/works/{work_id}/comment', json={'content': '写得好！'})
    assert res.status_code == 201, res.get_json()
    comment = res.get_json()['data']['comment']
    assert comment['author_name'] == '小B'
    assert comment['is_mine'] is True

    reply = client.post(f'/api/community/works/{work_id}/comment',
                        json={'content': '同意', 'parent_id': comment['id']})
    assert reply.status_code == 201
    assert client.post(f'/api/community/works/{work_id}/comment',
                       json={'content': '无效回复', 'parent_id': 9999}).status_code == 404
    assert client.post(f'/api/community/works/{work_id}/comment', json={'content': '赌博'}).status_code == 400
    client.post('/api/auth/logout')

    login('alice')
    comments = client.get(f'/api/community/works/{work_id}/comments').get_json()['data']['comments']
    assert len(comments) == 2
    assert client.delete(f'/api/community/works/{work_id}/comments/{comment["id"]}').status_code == 403
    client.post('/api/auth/logout')

    login('bob')
    assert client.delete(f'/api/community/works/{work_id}/comments/{comment["id"]}').status_code == 200
    detail = client.get(f'/api/community/works/{work_id}').get_json()['data']['work']
    assert detail['comment_count'] == 1


def test_like_toggle_and_detail(app, client, make_user, login, scored_writing):
    app.config['COMMUNITY_AUTO_APPROVE'] = True
    make_user('alice')
    make_user('bob')
    login('alice')
    work_id = _publish(client, scored_writing()['id']).get_json()['data']['work']['id']
    client.post('/api/auth/logout')

    login('bob')
    res = client.post(f'/api/community/works/{work_id}/like').get_json()['data']
    assert res == {'like_count': 1, 'is_liked': True}
    data = client.get(f'/api/community/works/{work_id}').get_json()['data']
    assert data['is_liked'] is True and data['work']['is_mine'] is False
    res = client.post(f'/api/community/works/{work_id}/like').get_json()['data']
    assert res == {'like_count': 0, 'is_liked': False}


def test_pending_work_only_visible_to_author(client, make_user, login, scored_writing):
    make_user('alice')
    make_user('bob')
    login('alice')
    work_id = _publish(client, scored_writing()['id']).get_json()['data']['work']['id']
    assert client.get(f'/api/community/works/{work_id}').status_code == 200
    client.post('/api/auth/logout')
    login('bob')
    assert client.get(f'/api/community/works/{work_id}').status_code == 404
