"""
文芽 - 通用 API 客户端服务
支持多种 AI 模型接入，提供统一的调用接口
"""
import json
import time
import hashlib
import logging
import threading
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from functools import wraps

import requests

logger = logging.getLogger(__name__)

# 进程级共享缓存：路由每次请求都会新建 APIClient，缓存放在实例上会随请求丢失
# 缓存键已包含 provider/model/messages/参数，不同实例共享是安全的
_SHARED_CACHE: Dict[str, 'CacheEntry'] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX_ENTRIES = 1000


class APIClientError(Exception):
    """API 客户端异常"""
    def __init__(self, message: str, status_code: int = None, retry_after: int = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after


class CacheEntry:
    """缓存条目"""
    def __init__(self, key: str, value: Any, ttl: int):
        self.key = key
        self.value = value
        self.created_at = datetime.utcnow()
        self.ttl = ttl  # 秒

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.created_at + timedelta(seconds=self.ttl)


class APIClient:
    """
    通用 API 客户端
    支持：OpenAI, Claude, 通义千问，DeepSeek 等
    功能：缓存、重试、降级、限流
    """

    # 支持的模型提供商
    PROVIDERS = {
        'openai': {
            'base_url': 'https://api.openai.com/v1',
            'auth_header': 'Authorization',
            'auth_format': 'Bearer {api_key}',
            'chat_endpoint': '/chat/completions',
            'response_path': 'choices[0].message.content'
        },
        'claude': {
            'base_url': 'https://api.anthropic.com/v1',
            'auth_header': 'x-api-key',
            'auth_format': '{api_key}',
            'chat_endpoint': '/messages',
            'response_path': 'content[0].text',
            'extra_headers': {
                'anthropic-version': '2023-06-01'
            }
        },
        'aliyun': {
            # 使用 DashScope 的 OpenAI 兼容模式
            'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            'auth_header': 'Authorization',
            'auth_format': 'Bearer {api_key}',
            'chat_endpoint': '/chat/completions',
            'response_path': 'choices[0].message.content'
        },
        'deepseek': {
            'base_url': 'https://api.deepseek.com/v1',
            'auth_header': 'Authorization',
            'auth_format': 'Bearer {api_key}',
            'chat_endpoint': '/chat/completions',
            'response_path': 'choices[0].message.content'
        },
        'moonshot': {
            'base_url': 'https://api.moonshot.cn/v1',
            'auth_header': 'Authorization',
            'auth_format': 'Bearer {api_key}',
            'chat_endpoint': '/chat/completions',
            'response_path': 'choices[0].message.content'
        }
    }

    # 请求体与响应格式为 OpenAI Chat Completions 的提供商
    OPENAI_COMPATIBLE = ('openai', 'deepseek', 'moonshot', 'aliyun')

    def __init__(self, provider: str = 'openai', api_key: str = None,
                 base_url: str = None, model: str = None,
                 cache_enabled: bool = True, cache_ttl: int = 3600, timeout: int = 60):
        """
        初始化 API 客户端

        Args:
            provider: 模型提供商 (openai/claude/aliyun/deepseek/moonshot)
            api_key: API 密钥
            base_url: 自定义 API 地址（可选）
            model: 模型名称
            cache_enabled: 是否启用缓存
            cache_ttl: 缓存过期时间（秒）
        """
        if provider not in self.PROVIDERS:
            raise ValueError(f"不支持的模型提供商：{provider}")

        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url or self.PROVIDERS[provider]['base_url']
        self.model = model or self._get_default_model(provider)
        self.cache_enabled = cache_enabled
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.cache: Dict[str, CacheEntry] = _SHARED_CACHE

        # 统计信息
        self.stats = {
            'total_calls': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'errors': 0,
            'retries': 0
        }

    def _get_default_model(self, provider: str) -> str:
        """获取提供商的默认模型"""
        default_models = {
            'openai': 'gpt-4o',
            'claude': 'claude-sonnet-5-5',
            'aliyun': 'qwen-max',
            'deepseek': 'deepseek-chat',
            'moonshot': 'moonshot-v1-8k'
        }
        return default_models.get(provider, 'gpt-4')

    def _generate_cache_key(self, messages: List[Dict], **kwargs) -> str:
        """生成缓存键"""
        key_data = json.dumps({
            'provider': self.provider,
            'model': self.model,
            'messages': messages,
            'kwargs': kwargs
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(key_data.encode()).hexdigest()

    def _get_from_cache(self, key: str) -> Optional[Any]:
        """从缓存获取数据"""
        if not self.cache_enabled:
            return None

        with _CACHE_LOCK:
            entry = self.cache.get(key)
            if entry and not entry.is_expired():
                self.stats['cache_hits'] += 1
                return dict(entry.value)  # 返回副本，避免调用方修改缓存内容

            if entry:
                del self.cache[key]  # 清理过期缓存

        self.stats['cache_misses'] += 1
        return None

    def _set_cache(self, key: str, value: Any):
        """设置缓存"""
        if not self.cache_enabled:
            return

        with _CACHE_LOCK:
            self.cache[key] = CacheEntry(key, dict(value), self.cache_ttl)

            # 超出容量时先清理过期条目，仍超出则淘汰最早写入的条目
            if len(self.cache) > _CACHE_MAX_ENTRIES:
                for k in [k for k, v in self.cache.items() if v.is_expired()]:
                    del self.cache[k]
                while len(self.cache) > _CACHE_MAX_ENTRIES:
                    del self.cache[next(iter(self.cache))]

    def chat(self, messages: List[Dict], **kwargs) -> Dict:
        """
        发送聊天请求

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            **kwargs: 额外参数 (temperature, max_tokens, etc.)

        Returns:
            Dict: {
                'content': str,
                'usage': Dict,
                'model': str,
                'provider': str,
                'cached': bool
            }
        """
        self.stats['total_calls'] += 1

        # 检查缓存
        cache_key = self._generate_cache_key(messages, **kwargs)
        cached_result = self._get_from_cache(cache_key)
        if cached_result:
            cached_result['cached'] = True
            return cached_result

        # 构建请求
        headers, payload = self._build_request(messages, **kwargs)

        # 发送请求（带重试）
        max_retries = kwargs.get('max_retries', 3)
        retry_delay = kwargs.get('retry_delay', 1.0)

        for attempt in range(max_retries):
            try:
                response = self._send_request(headers, payload)

                # 解析响应
                result = self._parse_response(response)

                # 缓存结果
                self._set_cache(cache_key, result)

                result['cached'] = False
                return result

            except APIClientError as e:
                self.stats['errors'] += 1

                # 判断是否可重试
                if e.status_code and e.status_code not in [400, 401, 403]:
                    if attempt < max_retries - 1:
                        self.stats['retries'] += 1
                        wait_time = retry_delay * (2 ** attempt)
                        if e.retry_after:
                            wait_time = max(wait_time, e.retry_after)
                        logger.warning(f"API 调用失败，{wait_time}s 后重试 (attempt {attempt + 1}/{max_retries}): {e.message}")
                        time.sleep(wait_time)
                        continue

                logger.error(f"API 调用失败：{e.message}")
                raise

        raise APIClientError("API 调用失败，已达最大重试次数")

    def _build_request(self, messages: List[Dict], **kwargs) -> tuple:
        """构建请求头和负载"""
        provider_config = self.PROVIDERS[self.provider]

        # 构建请求头
        headers = {
            'Content-Type': 'application/json',
            provider_config['auth_header']: provider_config['auth_format'].format(api_key=self.api_key)
        }

        # 添加额外请求头
        if 'extra_headers' in provider_config:
            headers.update(provider_config['extra_headers'])

        # 构建请求体（不同提供商格式不同）
        if self.provider in self.OPENAI_COMPATIBLE:
            payload = {
                'model': self.model,
                'messages': messages,
                'temperature': kwargs.get('temperature', 0.7),
                'max_tokens': kwargs.get('max_tokens', 2000)
            }
            # 提供商特有参数，例如通义千问的 enable_thinking、JSON 模式的 response_format
            payload.update(kwargs.get('extra_body') or {})
        elif self.provider == 'claude':
            # Claude：system 作为顶层字段（合并所有 system 消息，避免画像/作文上下文丢失）
            system_text = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system')
            chat_messages = [{'role': m['role'], 'content': m['content']}
                             for m in messages if m['role'] != 'system']

            payload = {
                'model': self.model,
                'messages': chat_messages,
                'max_tokens': kwargs.get('max_tokens', 2000),
                'temperature': kwargs.get('temperature', 0.7)
            }
            if system_text:
                payload['system'] = system_text
        else:
            raise APIClientError(f"不支持的模型提供商：{self.provider}")

        return headers, payload

    @staticmethod
    def _error_message(response) -> str:
        """从错误响应中提取说明（兼容 OpenAI/Claude/DashScope 格式及非 JSON 响应）"""
        try:
            data = response.json()
        except ValueError:
            return (response.text or '').strip()[:200] or '未知错误'
        if isinstance(data, dict):
            err = data.get('error')
            if isinstance(err, dict) and err.get('message'):
                return str(err['message'])
            if isinstance(err, str):
                return err
            if data.get('message'):
                return str(data['message'])
        return '未知错误'

    def _send_request(self, headers: Dict, payload: Dict) -> Dict:
        """发送 HTTP 请求"""
        provider_config = self.PROVIDERS[self.provider]
        url = self.base_url.rstrip('/') + provider_config['chat_endpoint']

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        except requests.Timeout:
            raise APIClientError("API 请求超时")
        except requests.RequestException as e:
            raise APIClientError(f"API 连接失败：{e.__class__.__name__}")

        if response.status_code != 200:
            retry_after = None
            if response.status_code == 429:
                try:
                    retry_after = int(response.headers.get('Retry-After', 5))
                except ValueError:
                    retry_after = 5
            raise APIClientError(
                f"API 请求失败（HTTP {response.status_code}）：{self._error_message(response)}",
                status_code=response.status_code,
                retry_after=retry_after
            )

        try:
            return response.json()
        except ValueError:
            raise APIClientError("API 响应不是合法的 JSON", status_code=response.status_code)

    def _parse_response(self, response: Dict) -> Dict:
        """解析响应"""
        provider_config = self.PROVIDERS[self.provider]

        try:
            if self.provider in self.OPENAI_COMPATIBLE:
                content = response['choices'][0]['message']['content']
                usage = response.get('usage', {})
            elif self.provider == 'claude':
                # 可能包含多个内容块（如 thinking），只拼接文本块
                content = ''.join(block.get('text', '') for block in response['content']
                                  if block.get('type', 'text') == 'text')
                usage = {
                    'prompt_tokens': response.get('usage', {}).get('input_tokens', 0),
                    'completion_tokens': response.get('usage', {}).get('output_tokens', 0)
                }
            else:
                content = ''
                usage = {}
            if not isinstance(content, str) or not content.strip():
                raise APIClientError("API 返回内容为空")

            return {
                'content': content,
                'usage': usage,
                'model': self.model,
                'provider': self.provider
            }

        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"解析 API 响应失败：{e}, response={response}")
            raise APIClientError(f"API 响应格式异常：{str(e)}")

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            **self.stats,
            'cache_size': len(self.cache),  # 进程级共享缓存大小
            'provider': self.provider,
            'model': self.model
        }

    def clear_cache(self):
        """清空缓存（进程级共享）"""
        with _CACHE_LOCK:
            self.cache.clear()
        logger.info("API 缓存已清空")


# 装饰器：带降级的 API 调用
def fallback_on_error(fallback_value):
    """
    装饰器：API 调用失败时返回降级值

    Usage:
        @fallback_on_error({'content': '默认回复', 'fallback': True})
        def call_api(...):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except APIClientError as e:
                logger.warning(f"API 调用失败，使用降级值：{e.message}")
                return fallback_value
        return wrapper
    return decorator
