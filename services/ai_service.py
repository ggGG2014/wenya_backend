"""
文芽 - AI 服务模块
负责与大模型交互，实现写作评分和对话功能
"""
import json
import logging
import time
from typing import Dict, List, Optional
from datetime import datetime

from .api_client import APIClient, APIClientError
from .memory_service import MemoryService

logger = logging.getLogger(__name__)


class AIServiceError(Exception):
    """AI 服务不可用或返回结果无效"""


class AIService:
    """
    AI 写作教练服务（增强版）
    功能：
    1. 多模型支持（OpenAI/Claude/通义千问/DeepSeek/月之暗面）
    2. 增强的记忆能力（向量检索、记忆聚合）
    3. 缓存和降级策略
    """

    def __init__(self, api_base=None, api_key=None, model=None, provider=None,
                 enable_memory: bool = None, enable_cache: bool = None):
        from flask import current_app

        if enable_memory is None:
            enable_memory = current_app.config.get('AI_ENABLE_MEMORY', True)
        if enable_cache is None:
            enable_cache = current_app.config.get('AI_ENABLE_CACHE', True)
        # 模拟模式：仅开发测试用，AI 不可用时返回明确标记的模拟结果
        self.mock_mode = current_app.config.get('AI_MOCK_MODE', False)

        # API 配置
        self.provider = provider or current_app.config.get('AI_PROVIDER', 'openai')
        # AI_API_BASE / AI_MODEL 留空时由 APIClient 使用该提供商的默认值
        self.api_base = api_base or current_app.config.get('AI_API_BASE') or None
        self.api_key = api_key or current_app.config.get('AI_API_KEY')
        self.model = model or current_app.config.get('AI_MODEL') or None
        self.max_tokens = current_app.config.get('AI_MAX_TOKENS', 2000)
        self.temperature = current_app.config.get('AI_TEMPERATURE', 0.7)
        self.extra_body = {}
        if self.provider == 'aliyun' and not current_app.config.get('AI_ENABLE_THINKING', False):
            # 通义千问默认可能开启思考模式；关闭可显著降低时延
            self.extra_body['enable_thinking'] = False
        
        # 初始化 API 客户端（支持多模型）
        self.api_client = APIClient(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.api_base,
            model=self.model,
            cache_enabled=enable_cache,
            cache_ttl=3600  # 1 小时缓存
        )
        self.api_base = self.api_client.base_url
        self.model = self.api_client.model
        
        # 初始化记忆服务
        self.enable_memory = enable_memory
        self.memory_service = MemoryService() if enable_memory else None
    
    def _get_headers(self):
        """获取请求头"""
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
    
    def _build_system_prompt(self, session_type='writing_guidance'):
        """
        构建系统级 Prompt
        设定 AI 的"人格"边界：写作教练/引导者
        """
        base_prompt = """你是一位专业的 AI 写作教练，专门为 6-18 岁未成年人提供写作指导。

【角色定位】
- 你是一位温和专业的写作教练，不是聊天伙伴
- 你的职责是引导学生提高写作能力，而不是提供情感陪伴
- 你专注于写作技巧、结构、表达等方面的指导

【交互原则】
1. 使用鼓励性但专业的语言，避免过度情感化表达
2. 聚焦写作本身，温和拒绝与写作无关的闲聊
3. 采用启发式提问，引导学生自己思考，而非直接给出答案
4. 根据学生的年级调整语言难度和指导深度
5. 明确指出自己是 AI 写作教练，不伪装成人类

【安全边界】
- 不讨论敏感政治、宗教、暴力、色情等内容
- 不提供可能误导学生的价值观建议
- 如遇不当内容，温和地引导回写作主题

请始终保持专业、温和、聚焦写作的教练风格。"""
        
        return base_prompt
    
    def score_writing(self, writing) -> Dict:
        """兼容旧调用：评分逻辑已移至 services/scoring_service.py"""
        from .scoring_service import ScoringService
        return ScoringService().score(writing)

    def chat(self, message: str, writing_context=None, user_profile=None,
             memory=None, history: List = None, session_type: str = 'writing_guidance',
             user_id: Optional[int] = None) -> Dict:
        """
        AI 对话辅导
        支持审题、素材启发、逐段引导等场景

        记忆片段只加入 db.session，由调用方 commit。

        Raises:
            AIServiceError: 模型不可用（非模拟模式下）
        """
        if user_id is None and user_profile and user_profile.user:
            user_id = user_profile.user.id
        use_memory = bool(self.enable_memory and self.memory_service and user_id)

        # 构建对话上下文
        messages = [
            {"role": "system", "content": self._build_system_prompt(session_type)}
        ]

        # 添加用户画像信息
        if user_profile:
            profile_info = f"学生信息：{user_profile.user.grade if user_profile.user else '未知'}年级，"
            if user_profile.strength_tags:
                profile_info += f"优势：{', '.join(user_profile.strength_tags)}，"
            if user_profile.weakness_tags:
                profile_info += f"需改进：{', '.join(user_profile.weakness_tags)}"
            messages.append({"role": "system", "content": profile_info})

        # 添加写作上下文
        if writing_context:
            context_info = f"""当前写作任务：
题目：{writing_context.title}
要求：{writing_context.prompt or '无特定要求'}
已写内容：{(writing_context.content or '')[:500]}...
"""
            messages.append({"role": "system", "content": context_info})

        # 添加历史对话
        if history:
            for msg in history[-10:]:  # 最多 10 条历史
                messages.append({"role": msg['role'], "content": msg['content']})

        # 使用增强记忆检索上下文（如果启用）
        if use_memory:
            context = self.memory_service.get_context_for_interaction(
                user_id=user_id,
                current_query=message,
                writing_context={
                    'title': writing_context.title,
                    'content': (writing_context.content or '')[:500]
                } if writing_context else None
            )

            # 注入相关记忆到上下文
            if context.get('relevant_memories'):
                memory_context = "\n【相关记忆】\n"
                for mem in context['relevant_memories'][:3]:
                    memory_context += f"- {mem['content']}\n"
                messages.append({"role": "system", "content": memory_context})

        # 添加当前消息
        messages.append({"role": "user", "content": message})

        # 调用大模型
        is_mock = False
        cached = False
        try:
            if not self.api_key:
                raise AIServiceError('AI 教练服务未配置（AI_API_KEY 为空）')
            result = self.api_client.chat(
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                extra_body=self.extra_body
            )
            response = result['content']
            cached = result.get('cached', False)
        except (APIClientError, AIServiceError) as e:
            logger.error(f"AI 对话调用失败：{getattr(e, 'message', e)}")
            if not self.mock_mode:
                raise AIServiceError('AI 教练暂时不可用') from e
            response = self._mock_chat_reply()
            is_mock = True

        # 只记录真实的对话到长期记忆，模拟回复不写入
        if use_memory and not is_mock:
            writing_id = writing_context.id if writing_context else None
            self.memory_service.add_fragment(
                user_id=user_id,
                content=f"用户提问：{message[:200]}",
                category='interaction',
                interaction_type=session_type,
                metadata={'session_type': session_type, 'writing_id': writing_id}
            )
            self.memory_service.add_fragment(
                user_id=user_id,
                content=f"AI 回复：{response[:200]}",
                category='interaction',
                interaction_type=session_type,
                metadata={'session_type': session_type, 'writing_id': writing_id,
                          'model': self.model, 'provider': self.provider}
            )

        # 提取关键点（用于记忆更新）
        key_points = self._extract_key_points(message, response, session_type)

        return {
            'content': response,
            'session_type': session_type,
            'key_points': key_points,
            'summary': f"{session_type} - {message[:50]}...",
            'is_filtered': False,
            'is_mock': is_mock,
            'model_info': {
                'provider': self.provider,
                'model': self.model,
                'cached': cached
            }
        }

    def _mock_chat_reply(self) -> str:
        """模拟对话回复（仅 AI_MOCK_MODE 开启时使用，开发测试用）"""
        return "【模拟回复，仅供开发测试】这是一个很好的写作问题。让我们一步步思考：首先，明确你要表达的核心观点是什么？其次，考虑如何用具体的例子来支撑这个观点。最后，注意段落之间的过渡要自然。你有什么具体的写作困难吗？"

    def _extract_key_points(self, user_msg: str, ai_response: str, session_type: str) -> List[str]:
        """提取对话关键点（用于记忆更新）"""
        # 简化实现，实际可用 NLP 提取
        key_points = []
        
        if session_type == 'writing_guidance':
            key_points.append(f"写作指导：{user_msg[:30]}")
        elif session_type == 'brainstorming':
            key_points.append(f"头脑风暴：{user_msg[:30]}")
        elif session_type == 'revision':
            key_points.append(f"修改建议：{user_msg[:30]}")
        
        return key_points
