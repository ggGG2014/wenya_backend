"""
pytest 公共夹具（真实 AI 版本）

说明：
- 每个测试使用独立的 TestingConfig + 内存 SQLite。
- 需要真实 AI 的测试请使用 real_ai_settings 夹具。
"""
import os
import sys
from datetime import datetime, timezone

import pytest
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db  # noqa: E402

PASSWORD = 'TestPass123'
ESSAY = (
    '去年冬天，我报名参加了学校的长跑队。第一次训练，跑到第三圈我就喘不上气，双腿像灌了铅一样。'
    '教练没有让我停下，只是在旁边陪我慢慢跑。他说：不要看终点，看脚下的下一步。'
    '后来每天清晨，我都比别人早到二十分钟。一个月后的测试，我第一次跑完了全程。'
)

AI_TEST_CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'test_ai.env')
REQUIRED_AI_ENV_VARS = ['TEST_REAL_AI_API_KEY']
OPTIONAL_AI_ENV_VARS = ['TEST_REAL_AI_PROVIDER', 'TEST_REAL_AI_API_BASE', 'TEST_REAL_AI_MODEL',
                        'TEST_REAL_AI_ENABLE_THINKING']
SKIPPED_AI_ENDPOINTS = [
    'POST /api/writing/{writing_id}/submit',
    'POST /api/writing/{writing_id}/ai-chat',
    'GET /api/ranking/overall',
    'GET /api/ranking/progress',
    'GET /api/ranking/dimension/{dimension}',
    'GET /api/ranking/my-growth-curve',
    'POST /api/community/publish/{writing_id}',
    'POST /api/community/works/{work_id}/report',
    'GET /api/community/works/{work_id}/report',
    'GET /api/memory/fragments',
    'GET /api/memory/context',
    'GET /api/memory/aggregate',
    'GET /api/memory/stats'
]
_REAL_AI_SKIP_REASON = None


def _resolve_ai_test_config():
    """读取真实 AI 测试配置，优先级：tests/test_ai.env > 系统环境变量。"""
    file_values = {}
    if os.path.exists(AI_TEST_CONFIG_FILE):
        file_values = {
            k: (v.strip() if isinstance(v, str) else v)
            for k, v in dotenv_values(AI_TEST_CONFIG_FILE).items()
            if v is not None
        }

    def pick(key, default=''):
        if key in file_values and str(file_values[key]).strip():
            return str(file_values[key]).strip()
        return (os.environ.get(key, default) or default).strip()

    return {
        'api_key': pick('TEST_REAL_AI_API_KEY'),
        'provider': pick('TEST_REAL_AI_PROVIDER', 'openai') or 'openai',
        'api_base': pick('TEST_REAL_AI_API_BASE'),
        'model': pick('TEST_REAL_AI_MODEL'),
        'enable_thinking': pick('TEST_REAL_AI_ENABLE_THINKING', 'false').lower() in ('1', 'true', 'yes', 'on')
    }


def pytest_configure(config):
    """在测试启动时预判真实 AI 配置缺失，并统一 skip 说明。"""
    global _REAL_AI_SKIP_REASON
    cfg = _resolve_ai_test_config()
    if not cfg['api_key']:
        required = ', '.join(REQUIRED_AI_ENV_VARS)
        optional = ', '.join(OPTIONAL_AI_ENV_VARS)
        endpoints = '; '.join(SKIPPED_AI_ENDPOINTS)
        _REAL_AI_SKIP_REASON = (
            '缺少真实 AI 配置，AI 集成测试已跳过。'
            f' 必填环境变量: {required}。'
            f' 可选环境变量: {optional}。'
            f' 若配置在 {AI_TEST_CONFIG_FILE} 中将优先使用。'
            f' 被跳过的 API 覆盖: {endpoints}'
        )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """在 pytest 结束时显式输出 AI 测试跳过说明。"""
    if not _REAL_AI_SKIP_REASON:
        return
    skipped_reports = [r for r in terminalreporter.stats.get('skipped', []) if hasattr(r, 'nodeid')]
    skipped_nodeids = sorted({r.nodeid for r in skipped_reports})

    terminalreporter.section('AI integration tests skipped', sep='=')
    terminalreporter.write_line('原因: 缺少 TEST_REAL_AI_API_KEY（或 tests/test_ai.env 未配置该值）')
    terminalreporter.write_line('必填环境变量: TEST_REAL_AI_API_KEY')
    terminalreporter.write_line(
        '可选环境变量: TEST_REAL_AI_PROVIDER, TEST_REAL_AI_API_BASE, TEST_REAL_AI_MODEL, TEST_REAL_AI_ENABLE_THINKING'
    )
    terminalreporter.write_line(f'配置文件优先级: {AI_TEST_CONFIG_FILE} > 系统环境变量')
    terminalreporter.write_line(f'被跳过的测试函数数: {len(skipped_nodeids)}')
    if skipped_nodeids:
        terminalreporter.write_line('被跳过的测试函数:')
        for nodeid in skipped_nodeids:
            terminalreporter.write_line(f'  - {nodeid}')
    terminalreporter.write_line(f'被跳过的 API 覆盖数(去重): {len(SKIPPED_AI_ENDPOINTS)}')
    terminalreporter.write_line('被跳过的 API 覆盖:')
    for endpoint in SKIPPED_AI_ENDPOINTS:
        terminalreporter.write_line(f'  - {endpoint}')


@pytest.fixture
def app():
    app = create_app('testing')
    app.config['AI_MOCK_MODE'] = False
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user():
    """直接在数据库中创建已通过监护人验证的用户。"""
    from models.ai_memory import AIMemory
    from models.user import Guardian, User, UserProfile

    counter = {'n': 0}

    def _make(username='student', grade=8, password=PASSWORD, **fields):
        counter['n'] += 1
        guardian = Guardian(
            name='家长',
            phone=f'1390000{counter["n"]:04d}',
            relationship='parent',
            is_verified=True,
            consent_given_at=datetime.now(timezone.utc)
        )
        db.session.add(guardian)
        db.session.flush()

        user = User(
            username=username,
            grade=grade,
            guardian_id=guardian.id,
            is_guardian_verified=True,
            **fields
        )
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
def real_ai_settings(app):
    """配置真实 AI 服务（优先 tests/test_ai.env）。"""
    cfg = _resolve_ai_test_config()
    if not cfg['api_key']:
        pytest.skip(_REAL_AI_SKIP_REASON or '缺少真实 AI 配置，跳过 AI 集成测试')

    app.config.update(
        AI_PROVIDER=cfg['provider'],
        AI_API_KEY=cfg['api_key'],
        AI_API_BASE=cfg['api_base'],
        AI_MODEL=cfg['model'],
        AI_ENABLE_THINKING=cfg['enable_thinking'],
        SCORING_PROVIDER=cfg['provider'],
        SCORING_API_KEY=cfg['api_key'],
        SCORING_API_BASE=cfg['api_base'],
        SCORING_MODEL=cfg['model'],
        SCORING_ENABLE_THINKING=cfg['enable_thinking'],
        AI_MOCK_MODE=False
    )
    return {'provider': cfg['provider'], 'api_base': cfg['api_base'], 'model': cfg['model']}


@pytest.fixture
def scored_writing_real(client, real_ai_settings):
    """创建并使用真实 AI 完成评分，返回 writing dict。"""

    def _make(title='那一次，我读懂了坚持', prompt='请写一篇记叙文', content=ESSAY):
        res = client.post('/api/writing', json={'title': title, 'prompt': prompt, 'content': content})
        assert res.status_code == 201, res.get_json()
        wid = res.get_json()['data']['writing']['id']
        res = client.post(f'/api/writing/{wid}/submit')
        assert res.status_code == 200, res.get_json()
        data = res.get_json()['data']
        assert data['is_mock'] is False
        return data['writing']

    return _make
