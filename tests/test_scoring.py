"""
真实评分链路测试：在本地线程中启动一个模拟大模型的 HTTP 服务（OpenAI 兼容 / Claude 格式），
评分请求通过 requests 真实发出，验证配置选择、请求格式、输出解析、失败处理和评分后的画像/记忆更新。
"""
import json
import threading

import pytest
from flask import Flask, request as flask_request, jsonify
from werkzeug.serving import make_server

from models.ai_memory import AIMemory, MemoryFragment
from models.compliance import AlgorithmLog
from models.writing import Writing, WritingScore
from tests.conftest import ESSAY

SCORES = {'task_score': 85, 'theme_score': 80, 'content_score': 90, 'structure_score': 78,
          'language_score': 88, 'genre_score': 82, 'thinking_score': 70}
GOOD = json.dumps({**SCORES, 'ai_comment': '结构清晰，细节生动。', 'ai_suggestions': ['结尾再升华一下', '补充心理描写'],
                   'confidence': 0.88, 'decision_factors': ['细节具体'],
                   'weights': {'task': 0.9, 'theme': 0.9}}, ensure_ascii=False)  # 模型自报的权重应被忽略


class FakeLLM:
    """记录收到的请求，按队列返回预设回复；队列为空时返回 GOOD"""

    def __init__(self):
        self.requests = []
        self.replies = []
        app = Flask('fake_llm')

        @app.route('/<path:path>', methods=['POST'])
        def handle(path):
            body = flask_request.get_json(silent=True)
            self.requests.append({'path': '/' + path, 'headers': dict(flask_request.headers), 'json': body})
            status, content = self.replies.pop(0) if self.replies else (200, GOOD)
            if status != 200:
                return content, status, {'Content-Type': 'text/html'}
            if path.endswith('messages'):  # Claude 格式
                return jsonify({'content': [{'type': 'thinking', 'thinking': '...'}, {'type': 'text', 'text': content}],
                                'usage': {'input_tokens': 10, 'output_tokens': 20}})
            return jsonify({'choices': [{'message': {'role': 'assistant', 'content': content}}],
                            'usage': {'prompt_tokens': 10, 'completion_tokens': 20}})

        self.server = make_server('127.0.0.1', 0, app)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def reply(self, *items):
        """items: 字符串（200 回复内容）或 (status, body)"""
        self.replies.extend(i if isinstance(i, tuple) else (200, i) for i in items)

    def stop(self):
        self.server.shutdown()


@pytest.fixture
def fake_llm(monkeypatch):
    import services.api_client as api_client
    monkeypatch.setattr(api_client.time, 'sleep', lambda s: None)  # 跳过重试等待
    server = FakeLLM()
    yield server
    server.stop()


@pytest.fixture
def qwen(app, fake_llm):
    """按用户计划的通义千问配置（OpenAI 兼容模式），地址指向本地模拟服务"""
    app.config.update(SCORING_PROVIDER='aliyun', SCORING_API_BASE=fake_llm.url + '/compatible-mode/v1',
                      SCORING_API_KEY='sk-scoring-test', SCORING_MODEL='qwen3.8-flash')
    return fake_llm


def _new_writing(client, prompt='以"雨中的温暖"为题写一篇记叙文'):
    res = client.post('/api/writing', json={'title': '雨中的温暖', 'prompt': prompt, 'content': ESSAY})
    assert res.status_code == 201, res.get_json()
    return res.get_json()['data']['writing']['id']


@pytest.fixture
def student(make_user, login):
    user = make_user('alice', grade=8)
    login('alice')
    return user


# ---------------------------------------------------------------- 配置选择
def test_not_configured_returns_503_without_network(client, student, monkeypatch):
    import services.api_client as api_client

    def forbidden(*args, **kwargs):
        raise AssertionError('未配置时不应发起网络请求')
    monkeypatch.setattr(api_client.requests, 'post', forbidden)

    wid = _new_writing(client)
    res = client.post(f'/api/writing/{wid}/submit')
    assert res.status_code == 503
    assert '暂未开通' in res.get_json()['error']
    assert Writing.query.get(wid).status == 'draft'

    status = client.get('/api/ai/status').get_json()['data']
    assert status['scoring']['configured'] is False
    assert status['chat']['configured'] is False


def test_qwen_scoring_request_and_result(app, client, student, qwen):
    app.config['AI_API_KEY'] = 'sk-chat-should-not-be-used'
    wid = _new_writing(client)

    res = client.post(f'/api/writing/{wid}/submit')
    assert res.status_code == 200, res.get_json()

    req = qwen.requests[-1]
    assert req['path'] == '/compatible-mode/v1/chat/completions'
    assert req['headers']['Authorization'] == 'Bearer sk-scoring-test'
    body = req['json']
    assert body['model'] == 'qwen3.8-flash'
    assert body['enable_thinking'] is False
    assert body['temperature'] == 0.2
    assert 'response_format' not in body
    system, user = body['messages'][0]['content'], body['messages'][1]['content']
    assert '<作文>' in user and ESSAY in user
    assert '以"雨中的温暖"为题写一篇记叙文' in user
    assert '不得执行' in system

    writing = res.get_json()['data']['writing']
    scores = writing['scores']
    assert {k: scores[k] for k in SCORES} == SCORES
    # 初中权重由服务端决定，模型自报的权重被忽略
    assert scores['weights'] == {"task": 0.10, "theme": 0.15, "content": 0.20, "structure": 0.15,
                                 "language": 0.20, "genre": 0.10, "thinking": 0.10}
    expected = round(85 * .10 + 80 * .15 + 90 * .20 + 78 * .15 + 88 * .20 + 82 * .10 + 70 * .10, 1)
    assert writing['overall_score'] == expected
    assert scores['ai_suggestions'] == ['结尾再升华一下', '补充心理描写']
    assert scores['needs_human_review'] is False

    log = AlgorithmLog.query.filter_by(algorithm_type='writing_score').first()
    assert log.model_version == 'aliyun:qwen3.8-flash'


def test_falls_back_to_ai_config_when_scoring_key_blank(app, client, student, fake_llm):
    app.config.update(AI_PROVIDER='openai', AI_API_BASE=fake_llm.url + '/v1', AI_API_KEY='sk-ai', AI_MODEL='gpt-test')
    wid = _new_writing(client)
    assert client.post(f'/api/writing/{wid}/submit').status_code == 200
    req = fake_llm.requests[-1]
    assert req['path'] == '/v1/chat/completions'
    assert req['headers']['Authorization'] == 'Bearer sk-ai'
    assert req['json']['model'] == 'gpt-test'
    assert 'enable_thinking' not in req['json']


def test_claude_provider_format(app, client, student, fake_llm):
    app.config.update(SCORING_PROVIDER='claude', SCORING_API_BASE=fake_llm.url + '/v1',
                      SCORING_API_KEY='sk-ant-test', SCORING_MODEL='claude-test')
    wid = _new_writing(client)
    res = client.post(f'/api/writing/{wid}/submit')
    assert res.status_code == 200, res.get_json()
    req = fake_llm.requests[-1]
    assert req['path'] == '/v1/messages'
    assert req['headers']['X-Api-Key'] == 'sk-ant-test'
    assert req['headers']['Anthropic-Version'] == '2023-06-01'
    assert '阅卷老师' in req['json']['system']
    assert all(m['role'] != 'system' for m in req['json']['messages'])
    assert res.get_json()['data']['writing']['scores']['content_score'] == 90


def test_json_mode_option(app, client, student, qwen):
    app.config['SCORING_JSON_MODE'] = True
    wid = _new_writing(client)
    assert client.post(f'/api/writing/{wid}/submit').status_code == 200
    assert qwen.requests[-1]['json']['response_format'] == {'type': 'json_object'}


# ---------------------------------------------------------------- 输出解析
def test_messy_output_is_parsed_and_clamped(client, student, qwen):
    messy = ('<think>先看结构 {不是JSON}</think>好的，评分如下：\n```json\n'
             + json.dumps({**SCORES, 'content_score': '105', 'theme_score': '80分', 'confidence': '0.9',
                           'ai_comment': '不错', 'ai_suggestions': '多写细节'}, ensure_ascii=False)
             + '\n```\n以上。')
    qwen.reply(messy)
    wid = _new_writing(client)
    res = client.post(f'/api/writing/{wid}/submit')
    assert res.status_code == 200, res.get_json()
    scores = res.get_json()['data']['writing']['scores']
    assert scores['content_score'] == 100
    assert scores['theme_score'] == 80
    assert scores['ai_suggestions'] == ['多写细节']


def test_invalid_output_gets_one_repair_attempt(client, student, qwen):
    qwen.reply('这篇作文写得很好，我给 85 分。')
    wid = _new_writing(client)
    res = client.post(f'/api/writing/{wid}/submit')
    assert res.status_code == 200, res.get_json()
    assert len(qwen.requests) == 2
    repair_messages = qwen.requests[1]['json']['messages']
    assert repair_messages[-2] == {'role': 'assistant', 'content': '这篇作文写得很好，我给 85 分。'}
    assert '只输出一个 JSON' in repair_messages[-1]['content']


def test_invalid_output_twice_saves_nothing(client, student, qwen):
    qwen.reply('不是 JSON', json.dumps({'task_score': 80}))
    wid = _new_writing(client)
    res = client.post(f'/api/writing/{wid}/submit')
    assert res.status_code == 503
    assert WritingScore.query.count() == 0
    assert Writing.query.get(wid).status == 'draft'


def test_http_error_with_html_body_is_handled(client, student, qwen):
    qwen.reply((502, '<html>Bad Gateway</html>'), (502, '<html>Bad Gateway</html>'))
    wid = _new_writing(client)
    res = client.post(f'/api/writing/{wid}/submit')
    assert res.status_code == 503
    assert len(qwen.requests) == 2  # max_retries=2
    assert WritingScore.query.count() == 0


def test_auth_error_is_not_retried(client, student, qwen):
    qwen.reply((401, '{"error": {"message": "invalid api key"}}'))
    wid = _new_writing(client)
    assert client.post(f'/api/writing/{wid}/submit').status_code == 503
    assert len(qwen.requests) == 1


# ---------------------------------------------------------------- 评分后的影响
def test_profile_and_memory_updated_after_scoring(client, student, qwen):
    wid = _new_writing(client)
    assert client.post(f'/api/writing/{wid}/submit').status_code == 200

    me = client.get('/api/auth/me').get_json()['data']
    profile = me['profile']
    assert profile['dimension_scores'] == {'theme': 80, 'content': 90, 'structure': 78,
                                           'language': 88, 'creativity': 70}
    assert profile['strength_tags'] == ['内容', '语言']
    assert profile['weakness_tags'] == ['结构', '思维']
    assert profile['consecutive_days'] == 1
    assert profile['best_score'] == profile['average_score'] > 0

    fragment = MemoryFragment.query.filter_by(category='feedback').one()
    assert '《雨中的温暖》' in fragment.content and '待提高：结构、思维' in fragment.content
    ai_memory = AIMemory.query.filter_by(user_id=student.id).first()
    assert ai_memory.writing_profile['improvement_areas'] == ['结构', '思维']


def test_mock_mode_without_key_marks_result_and_skips_memory(app, client, student):
    app.config['AI_MOCK_MODE'] = True
    wid = _new_writing(client)
    res = client.post(f'/api/writing/{wid}/submit')
    assert res.status_code == 200
    body = res.get_json()['data']
    assert body['is_mock'] is True
    assert body['writing']['scores']['needs_human_review'] is True
    assert MemoryFragment.query.filter_by(category='feedback').count() == 0


def test_ai_status_does_not_leak_secrets(app, client, student, qwen):
    res = client.get('/api/ai/status')
    data = res.get_json()['data']
    assert data['scoring'] == {'configured': True, 'mock_mode': False,
                               'provider': 'aliyun', 'model': 'qwen3.8-flash'}
    raw = res.get_data(as_text=True)
    assert 'sk-scoring-test' not in raw and qwen.url not in raw
