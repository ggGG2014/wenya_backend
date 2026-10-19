"""排行榜类 API：每条 API 一个独立测试。"""


def _prepare_rank_data(make_user, login, scored_writing_real):
    make_user('alice', grade=8)
    login('alice')
    scored_writing_real(title='第一次写作')
    scored_writing_real(title='第二次写作')


def test_ranking_overall(client, make_user, login, scored_writing_real):
    _prepare_rank_data(make_user, login, scored_writing_real)
    res = client.get('/api/ranking/overall')
    assert res.status_code == 200
    data = res.get_json()['data']
    assert data['rank_type'] == 'overall'


def test_ranking_progress(client, make_user, login, scored_writing_real):
    _prepare_rank_data(make_user, login, scored_writing_real)
    res = client.get('/api/ranking/progress?days=30')
    assert res.status_code == 200
    data = res.get_json()['data']
    assert data['rank_type'] == 'progress'


def test_ranking_dimension(client, make_user, login, scored_writing_real):
    _prepare_rank_data(make_user, login, scored_writing_real)
    res = client.get('/api/ranking/dimension/language')
    assert res.status_code == 200
    data = res.get_json()['data']
    assert data['dimension'] == 'language'


def test_ranking_growth_curve(client, make_user, login, scored_writing_real):
    _prepare_rank_data(make_user, login, scored_writing_real)
    res = client.get('/api/ranking/my-growth-curve?days=90')
    assert res.status_code == 200
    assert res.get_json()['data']['is_private'] is True


def test_ranking_toggle_visibility(client, make_user, login):
    make_user('alice', grade=8)
    login('alice')
    res = client.post('/api/ranking/toggle-visibility', json={'show': False})
    assert res.status_code == 200
    assert res.get_json()['data']['show_in_ranking'] is False
