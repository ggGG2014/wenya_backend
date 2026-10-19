"""
文芽 - 配置模块
所有配置均可通过环境变量或项目根目录下的 .env 文件覆盖（参考 .env.example）
"""
import os
from datetime import timedelta

from dotenv import load_dotenv

# 读取项目根目录的 .env；已存在的系统环境变量优先，不会被覆盖
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

DEFAULT_SECRET_KEY = 'wenya-dev-secret-key-change-in-prod'


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == '':
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, '').strip()
    return int(value) if value else default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name, '').strip()
    return float(value) if value else default


class Config:
    """基础配置"""
    # 安全
    SECRET_KEY = os.environ.get('SECRET_KEY') or DEFAULT_SECRET_KEY

    # 数据库（默认 SQLite，相对路径位于 Flask instance/ 目录下，即 instance/wenya.db）
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///wenya.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = _env_bool('SQLALCHEMY_ECHO', False)

    # 会话
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # 上传
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

    # AI
    AI_PROVIDER = os.environ.get('AI_PROVIDER') or 'openai'  # openai/claude/aliyun/deepseek/moonshot
    # 留空时使用所选提供商的默认地址和默认模型（见 services/api_client.py）
    AI_API_BASE = os.environ.get('AI_API_BASE', '')
    AI_API_KEY = os.environ.get('AI_API_KEY', '')
    AI_MODEL = os.environ.get('AI_MODEL', '')
    AI_MAX_TOKENS = _env_int('AI_MAX_TOKENS', 2000)
    AI_TEMPERATURE = _env_float('AI_TEMPERATURE', 0.7)
    # 通义千问 Qwen3 思考模式（默认关闭以提升速度）
    AI_ENABLE_THINKING = _env_bool('AI_ENABLE_THINKING', False)
    AI_ENABLE_MEMORY = _env_bool('AI_ENABLE_MEMORY', True)
    AI_ENABLE_CACHE = _env_bool('AI_ENABLE_CACHE', True)
    # 模拟模式（仅开发测试）：AI 不可用时返回带【模拟】标记的结果，而不是报错
    AI_MOCK_MODE = _env_bool('AI_MOCK_MODE', False)

    # 作文评分 API（填写 SCORING_API_KEY 后生效，其余留空的项回退到 AI_* / 提供商默认值；
    # SCORING_API_KEY 为空时评分使用 AI_* 配置；两者都为空则评分服务未配置）
    SCORING_PROVIDER = os.environ.get('SCORING_PROVIDER', '')  # openai/claude/aliyun/deepseek/moonshot
    SCORING_API_BASE = os.environ.get('SCORING_API_BASE', '')
    SCORING_API_KEY = os.environ.get('SCORING_API_KEY', '')
    SCORING_MODEL = os.environ.get('SCORING_MODEL', '')
    SCORING_TEMPERATURE = _env_float('SCORING_TEMPERATURE', 0.2)
    SCORING_MAX_TOKENS = _env_int('SCORING_MAX_TOKENS', 1500)
    SCORING_TIMEOUT = _env_int('SCORING_TIMEOUT', 90)  # 单次请求超时（秒）
    SCORING_JSON_MODE = _env_bool('SCORING_JSON_MODE', False)  # OpenAI 兼容接口的 response_format=json_object
    SCORING_ENABLE_THINKING = _env_bool('SCORING_ENABLE_THINKING', False)  # 通义千问 Qwen3 思考模式

    # 社区：作品通过内容安全检查后是否自动公开（关闭时需人工审核）
    COMMUNITY_AUTO_APPROVE = _env_bool('COMMUNITY_AUTO_APPROVE', False)

    # 内容安全
    CONTENT_SAFE_API_KEY = os.environ.get('CONTENT_SAFE_API_KEY', '')
    CONTENT_SAFE_ENABLED = _env_bool('CONTENT_SAFE_ENABLED', False)

    # 限流（Flask-Limiter 3.x 读取 RATELIMIT_STORAGE_URI）
    RATELIMIT_DEFAULT = "100 per hour"
    RATELIMIT_STORAGE_URI = os.environ.get('REDIS_URL') or 'memory://'

    # 跨域（逗号分隔；开发时前端走 Vite 代理，同源访问不受影响）
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS') or '*'

    # 日志
    LOG_LEVEL = os.environ.get('LOG_LEVEL') or 'INFO'

    # 合规
    ICP_NUMBER = os.environ.get('ICP_NUMBER', '')  # ICP 备案号
    ALGORITHM_NUMBER = os.environ.get('ALGORITHM_NUMBER', '')  # 算法备案号


class DevelopmentConfig(Config):
    """开发环境配置"""
    DEBUG = True


class ProductionConfig(Config):
    """生产环境配置"""
    DEBUG = False
    SQLALCHEMY_ECHO = False
    AI_MOCK_MODE = False  # 生产环境禁止模拟评分


class TestingConfig(Config):
    """测试环境配置"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_ECHO = False
    RATELIMIT_ENABLED = False
    AI_MOCK_MODE = False
    COMMUNITY_AUTO_APPROVE = False
    # 测试绝不使用 .env 中的真实密钥
    AI_API_KEY = ''
    AI_API_BASE = ''
    AI_MODEL = ''
    AI_PROVIDER = 'openai'
    SCORING_API_KEY = ''
    SCORING_API_BASE = ''
    SCORING_MODEL = ''
    SCORING_PROVIDER = ''
    SCORING_JSON_MODE = False
    CONTENT_SAFE_ENABLED = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
