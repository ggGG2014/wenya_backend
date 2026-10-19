"""认证与账号设置接口"""
from tests.conftest import PASSWORD


def test_register_with_guardian_code_then_me(client):
    from routes.auth import verification_codes

    res = client.post('/api/auth/send-guardian-code', json={'phone': '13800138000'})
    assert res.status_code == 200
    code = verification_codes['guardian:13800138000']['code']

    payload = {'username': 'new_student', 'password': PASSWORD, 'grade': 8,
               'guardian_name': '家长', 'guardian_phone': '13800138000',
               'guardian_relationship': '母子', 'guardian_verification_code': '000000' if code != '000000' else '111111'}
    assert client.post('/api/auth/register', json=payload).status_code == 400  # 验证码错误

    payload['guardian_verification_code'] = code
    res = client.post('/api/auth/register', json=payload)
    assert res.status_code == 201
    assert res.get_json()['data']['user']['username'] == 'new_student'

    me = client.get('/api/auth/me').get_json()['data']
    assert me['user']['username'] == 'new_student'
    assert me['user']['show_works_publicly'] is True


def test_login_logout(client, make_user):
    make_user('alice')
    assert client.post('/api/auth/login', json={'username': 'alice', 'password': 'wrong123'}).status_code == 401
    assert client.post('/api/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 200
    assert client.get('/api/auth/me').status_code == 200
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/auth/me').status_code == 401


def test_profile_returns_masked_guardian(client, make_user, login):
    make_user('alice')
    login('alice')
    data = client.get('/api/auth/profile').get_json()['data']
    guardian = data['guardian']
    assert guardian['name'] == '家长'
    assert '****' in guardian['phone_masked']
    assert 'phone' not in guardian


def test_update_profile_nickname_and_privacy(client, make_user, login):
    make_user('alice')
    login('alice')
    res = client.put('/api/auth/profile', json={'nickname': '小A', 'show_works_publicly': False})
    assert res.status_code == 200
    user = res.get_json()['data']['user']
    assert user['nickname'] == '小A'
    assert user['show_works_publicly'] is False

    assert client.put('/api/auth/profile', json={'show_in_ranking': 'no'}).status_code == 400
    assert client.put('/api/auth/profile', json={'nickname': 'x' * 33}).status_code == 400


def test_change_password(client, make_user, login):
    make_user('alice')
    login('alice')
    assert client.post('/api/auth/change-password',
                       json={'old_password': 'bad', 'new_password': 'NewPass456'}).status_code == 400
    assert client.post('/api/auth/change-password',
                       json={'old_password': PASSWORD, 'new_password': 'NewPass456'}).status_code == 200
    client.post('/api/auth/logout')
    assert client.post('/api/auth/login', json={'username': 'alice', 'password': 'NewPass456'}).status_code == 200


def test_export_data(client, make_user, login, scored_writing):
    make_user('alice')
    login('alice')
    scored_writing()
    data = client.post('/api/auth/export-data').get_json()['data']
    assert data['user']['username'] == 'alice'
    assert len(data['writings']) == 1
    assert data['writings'][0]['scores']['task_score'] == 85
