"""
文芽 - pytest 公共夹具

每个测试使用独立的内存 SQLite 数据库（TestingConfig），AI 调用通过 monkeypatch 模拟，
不会访问外部网络。运行：python -m pytest
"""
import json
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db  # noqa: E402

PASSWORD = 'TestPass123'

ESSAY = (
    '去年冬天，我报名参加了学校的长跑队。第一次训练，跑到第三圈我就喘不上气，双腿像灌了铅一样。'
    '教练没有让我停下，只是在旁边陪我慢慢跑。他说：不要看终点，看脚下的下一步。'
    '后来每天清晨，我都比别人早到二十分钟。一个月后的测试，我第一次跑完了全程。'
)

SCORE_JSON = json.dumps({
    'task_score': 85, 'theme_score': 80, 'content_score': 82, 'structure_score': 78,
    'language_score': 88, 'genre_score': 80, 'thinking_score': 75,
    'ai_comment': '结构清晰，语言流畅。', 'ai_suggestions': ['补充细节'],
    'confidence': 0.9, 'decision_factors': ['语言流畅']
}, ensure_ascii=False)


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user(app):
    """直接在数据库中创建已通过监护人验证的用户"""
    from models.user import User, Guardian, UserProfile
    from models.ai_memory import AIMemory

    counter = {'n': 0}

    def _make(username='student', grade=8, password=PASSWORD, **fields):
        counter['n'] += 1
        guardian = Guardian(name='家长', phone=f'1390000{counter["n"]:04d}', relationship='parent',
                            is_verified=True, consent_given_at=datetime.utcnow())
        db.session.add(guardian)
        db.session.flush()
        user = User(username=username, grade=grade, guardian_id=guardian.id,
                    is_guardian_verified=True, **fields)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        db.session.add(UserProfile(user_id=user.id))
        db.session.add(AIMemory(user_id=user.id))
        db.session.commit()
        return user

    return _make


@pytest.fixture
def login(client):
    def _login(username, password=PASSWORD):
        res = client.post('/api/auth/login', json={'username': username, 'password': password})
        assert res.status_code == 200, res.get_json()
        return res
    return _login


@pytest.fixture
def ai_reply(app, monkeypatch):
    """
    模拟大模型：ai_reply(content) 让后续调用返回 content；ai_reply(error=True) 让调用失败。
    返回调用记录列表，便于断言发送给模型的消息。
    （配置测试用 key，否则评分/对话会被视为"未配置"而不调用模型）
    """
    from services.api_client import APIClient, APIClientError

    app.config['AI_API_KEY'] = 'test-ai-key'
    app.config['SCORING_API_KEY'] = 'test-scoring-key'
    calls = []
    state = {'content': None, 'error': False}

    def fake_chat(self, messages, **kwargs):
        calls.append(messages)
        if state['error']:
            raise APIClientError('模拟的连接失败')
        return {'content': state['content'], 'usage': {}, 'model': self.model,
                'provider': self.provider, 'cached': False}

    monkeypatch.setattr(APIClient, 'chat', fake_chat)

    def _set(content=None, error=False):
        state['content'] = content
        state['error'] = error
        return calls

    return _set


@pytest.fixture
def scored_writing(client, ai_reply):
    """创建并成功评分一篇作文，返回作文 dict"""
    def _make(title='那一次，我读懂了坚持'):
        ai_reply(SCORE_JSON)
        res = client.post('/api/writing', json={'title': title, 'content': ESSAY})
        assert res.status_code == 201, res.get_json()
        wid = res.get_json()['data']['writing']['id']
        res = client.post(f'/api/writing/{wid}/submit')
        assert res.status_code == 200, res.get_json()
        return res.get_json()['data']['writing']
    return _make
