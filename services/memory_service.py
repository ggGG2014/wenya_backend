"""
文芽 - 增强记忆服务
支持向量检索、记忆聚合、长期记忆持久化

记忆片段持久化在 memory_fragments 表（models.ai_memory.MemoryFragment）。
本服务只向 db.session 添加/修改对象，不负责 commit —— 由调用方（路由）统一提交，
这样记忆写入与同一请求中的其他数据库操作保持原子性。
"""
import re
import json
import hashlib
import logging
import uuid
from collections import Counter
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from models.ai_memory import MemoryFragment

logger = logging.getLogger(__name__)

_EN_WORD_RE = re.compile(r'[a-zA-Z0-9]+')
_CJK_RE = re.compile(r'[一-鿿]+')


def _tokenize(text: str) -> set:
    """
    简单分词：英文按单词，中文按字的二元组（bigram）
    中文没有空格，按空格切分会导致中文内容永远匹配不上
    """
    text = (text or '').lower()
    tokens = set(_EN_WORD_RE.findall(text))
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


class MemoryService:
    """
    增强记忆服务
    功能：
    1. 记忆片段化存储（数据库持久化）
    2. 重要性评分与衰减
    3. 相似记忆检索（支持向量检索）
    4. 记忆聚合与摘要
    """

    max_fragments_per_user = 1000  # 每用户最大记忆片段数

    def __init__(self, db_session=None, vector_store_enabled: bool = False):
        """
        初始化记忆服务

        Args:
            db_session: 数据库会话（默认使用 Flask-SQLAlchemy 的 db.session）
            vector_store_enabled: 是否启用向量检索（需要额外依赖）
        """
        if db_session is None:
            from app import db
            db_session = db.session
        self.db_session = db_session
        self.vector_store_enabled = vector_store_enabled

        # 向量编码器（可选）
        self.encoder = None
        if vector_store_enabled:
            self._init_vector_encoder()

    def _init_vector_encoder(self):
        """初始化向量编码器"""
        try:
            # 尝试使用 sentence-transformers
            from sentence_transformers import SentenceTransformer
            self.encoder = SentenceTransformer('paraphrase-MiniLM-L6-v2')
            logger.info("向量编码器初始化成功")
        except ImportError:
            logger.warning("sentence-transformers 未安装，向量检索功能不可用")
            self.vector_store_enabled = False
        except Exception as e:
            logger.warning(f"向量编码器初始化失败：{e}")
            self.vector_store_enabled = False

    def _generate_fragment_id(self, user_id: int, content: str) -> str:
        """生成记忆片段 ID"""
        key = f"{user_id}:{content}:{uuid.uuid4().hex}"
        return hashlib.md5(key.encode()).hexdigest()

    def _calculate_importance(self, content: str, interaction_type: str,
                              user_feedback: float = None) -> float:
        """
        计算记忆重要性

        因素：
        - 内容长度和复杂度
        - 交互类型（评分>指导>闲聊）
        - 用户反馈（如果有）
        """
        # 基础重要性（基于内容长度）
        length_score = min(1.0, len(content) / 500) * 0.3

        # 交互类型权重（同时兼容 AIConversation.session_type 的取值）
        type_weights = {
            'scoring': 1.0,           # 评分最重要
            'revision': 0.8,          # 修改建议
            'guidance': 0.6,          # 写作指导
            'writing_guidance': 0.6,
            'brainstorming': 0.5,     # 头脑风暴
            'chat': 0.3               # 普通对话
        }
        type_score = type_weights.get(interaction_type, 0.3) * 0.4

        # 用户反馈（如果有）
        feedback_score = user_feedback if user_feedback is not None else 0.5
        feedback_score *= 0.3

        importance = length_score + type_score + feedback_score
        return min(1.0, max(0.0, importance))

    def _user_query(self, user_id: int, category: str = None):
        query = MemoryFragment.query.filter_by(user_id=user_id)
        if category:
            query = query.filter_by(category=category)
        return query

    def add_fragment(self, user_id: int, content: str, category: str,
                     interaction_type: str = 'chat', user_feedback: float = None,
                     metadata: Dict = None) -> MemoryFragment:
        """
        添加记忆片段（加入会话，由调用方 commit）

        Args:
            user_id: 用户 ID
            content: 记忆内容
            category: 类别
            interaction_type: 交互类型
            user_feedback: 用户反馈（0-1）
            metadata: 额外元数据

        Returns:
            MemoryFragment: 创建的记忆片段
        """
        importance = self._calculate_importance(content, interaction_type, user_feedback)

        fragment = MemoryFragment(
            id=self._generate_fragment_id(user_id, content),
            user_id=user_id,
            content=content,
            category=category,
            importance=importance,
            meta=metadata or {},
            access_count=0,
            created_at=datetime.utcnow(),
            accessed_at=datetime.utcnow()
        )

        # 生成向量表示（如果启用）
        if self.vector_store_enabled and self.encoder:
            try:
                fragment.embedding = self.encoder.encode(content).tolist()
            except Exception as e:
                logger.warning(f"生成向量表示失败：{e}")

        self.db_session.add(fragment)
        self.db_session.flush()

        # 清理低重要性记忆（保持最大数量）
        self._prune_fragments(user_id)

        logger.info(f"添加记忆片段：user_id={user_id}, category={category}, importance={importance:.2f}")
        return fragment

    def _prune_fragments(self, user_id: int):
        """超出上限时删除衰减后重要性最低的记忆"""
        count = self._user_query(user_id).count()
        if count <= self.max_fragments_per_user:
            return

        now = datetime.utcnow()
        fragments = self._user_query(user_id).all()
        fragments.sort(key=lambda f: (f.effective_importance(now), f.created_at), reverse=True)
        removed = fragments[self.max_fragments_per_user:]
        for fragment in removed:
            self.db_session.delete(fragment)
        self.db_session.flush()
        logger.info(f"清理 {len(removed)} 个低重要性记忆片段")

    def retrieve(self, user_id: int, query: str = '', top_k: int = 5,
                 category: str = None, min_importance: float = 0.3) -> List[MemoryFragment]:
        """
        检索相关记忆

        query 为空时按时间倒序返回最近的记忆；
        query 非空时只返回与查询相关的记忆，按相关度排序。

        Args:
            user_id: 用户 ID
            query: 查询文本
            top_k: 返回数量
            category: 类别过滤
            min_importance: 最低（衰减后）重要性阈值

        Returns:
            List[MemoryFragment]: 相关记忆片段
        """
        now = datetime.utcnow()
        candidates = [
            f for f in self._user_query(user_id, category)
                          .order_by(MemoryFragment.created_at.desc())
                          .limit(self.max_fragments_per_user).all()
            if f.effective_importance(now) >= min_importance
        ]

        if query and query.strip():
            scored = self._rank_by_relevance(candidates, query)
            results = [f for score, f in scored if score > 0][:top_k]
        else:
            results = candidates[:top_k]

        # 更新访问统计
        for fragment in results:
            fragment.accessed_at = now
            fragment.access_count = (fragment.access_count or 0) + 1

        return results

    def _rank_by_relevance(self, fragments: List[MemoryFragment], query: str) -> List[tuple]:
        """返回 [(相关度, 片段)]，按相关度、重要性、时间降序"""
        now = datetime.utcnow()
        scores = None

        if self.vector_store_enabled and self.encoder:
            try:
                query_embedding = self.encoder.encode(query).tolist()
                scores = [
                    self._cosine_similarity(query_embedding, f.embedding) if f.embedding else 0.0
                    for f in fragments
                ]
            except Exception as e:
                logger.warning(f"向量检索失败，回退到关键词匹配：{e}")

        if scores is None:
            query_tokens = _tokenize(query)
            scores = [
                len(query_tokens & _tokenize(f.content)) / (len(query_tokens) + 1)
                for f in fragments
            ]

        ranked = list(zip(scores, fragments))
        ranked.sort(key=lambda pair: (pair[0], pair[1].effective_importance(now), pair[1].created_at),
                    reverse=True)
        return ranked

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def delete_fragment(self, user_id: int, fragment_id: str) -> bool:
        """删除指定记忆片段（仅限本人）"""
        fragment = self._user_query(user_id).filter_by(id=fragment_id).first()
        if not fragment:
            return False
        self.db_session.delete(fragment)
        return True

    def clear_fragments(self, user_id: int, category: str = None) -> int:
        """清空用户记忆片段，返回删除数量"""
        return self._user_query(user_id, category).delete(synchronize_session=False)

    def aggregate_memories(self, user_id: int, category: str = None,
                           time_range_days: int = 30) -> Dict:
        """
        聚合记忆生成摘要

        Args:
            user_id: 用户 ID
            category: 类别
            time_range_days: 时间范围（天）

        Returns:
            Dict: 聚合摘要
        """
        cutoff_date = datetime.utcnow() - timedelta(days=time_range_days)
        fragments = self._user_query(user_id, category)\
            .filter(MemoryFragment.created_at >= cutoff_date).all()

        if not fragments:
            return {}

        # 按类别分组
        by_category = {}
        for fragment in fragments:
            by_category.setdefault(fragment.category, []).append(fragment)

        # 生成摘要
        summary = {
            'total_fragments': len(fragments),
            'time_range_days': time_range_days,
            'categories': {}
        }

        for cat, frags in by_category.items():
            # 提取高频词
            word_freq = self._extract_frequent_words([f.content for f in frags])

            summary['categories'][cat] = {
                'count': len(frags),
                'avg_importance': sum(f.effective_importance() for f in frags) / len(frags),
                'top_keywords': word_freq[:10],
                'recent_content': [f.content[:100] for f in sorted(frags, key=lambda x: x.created_at, reverse=True)[:3]]
            }

        return summary

    def _extract_frequent_words(self, texts: List[str], top_n: int = 20) -> List[str]:
        """提取高频词"""
        # 中文分词（简单实现）
        words = []
        for text in texts:
            # 提取中文词汇（简单按字符分割）
            chinese_chars = _CJK_RE.findall(text)
            words.extend(''.join(chinese_chars))

            # 提取英文单词
            english_words = re.findall(r'\b[a-zA-Z]+\b', text)
            words.extend(english_words)

        # 统计词频
        word_counts = Counter(words)
        return [word for word, count in word_counts.most_common(top_n)]

    def update_memory_profile(self, user_id: int, new_profile: Dict) -> Dict:
        """
        更新用户记忆画像

        Args:
            user_id: 用户 ID
            new_profile: 新画像数据

        Returns:
            Dict: 更新后的画像
        """
        # 获取最新画像
        existing = self.retrieve(user_id, category='writing_profile', top_k=1, min_importance=0.0)

        if existing:
            # 合并画像
            merged = {**(existing[0].meta or {}), **new_profile}
            self.add_fragment(
                user_id=user_id,
                content=f"写作画像更新：{json.dumps(new_profile, ensure_ascii=False)}",
                category='writing_profile',
                interaction_type='guidance',
                metadata=merged
            )
            return merged
        else:
            # 新建画像
            self.add_fragment(
                user_id=user_id,
                content=f"初始写作画像：{json.dumps(new_profile, ensure_ascii=False)}",
                category='writing_profile',
                interaction_type='guidance',
                metadata=new_profile
            )
            return new_profile

    def get_context_for_interaction(self, user_id: int, current_query: str,
                                    writing_context: Dict = None) -> Dict:
        """
        为当前交互生成上下文

        Args:
            user_id: 用户 ID
            current_query: 当前查询
            writing_context: 写作上下文

        Returns:
            Dict: 上下文信息
        """
        context = {
            'user_profile': None,
            'relevant_memories': [],
            'writing_history': [],
            'feedback_history': []
        }

        # 获取最新用户画像
        profile_memories = self.retrieve(user_id, category='writing_profile', top_k=1, min_importance=0.0)
        if profile_memories:
            context['user_profile'] = profile_memories[0].meta

        # 获取相关记忆
        # 阈值 0.2：一条普通写作指导记忆（约 0.4）大约两周后衰减到阈值以下
        relevant = self.retrieve(user_id, current_query, top_k=5, min_importance=0.2)
        context['relevant_memories'] = [
            {'content': f.content, 'category': f.category, 'importance': f.effective_importance()}
            for f in relevant
        ]

        # 获取写作历史
        writing_history = self.retrieve(user_id, category='knowledge', top_k=3)
        context['writing_history'] = [
            {'content': f.content[:200], 'metadata': f.meta}
            for f in writing_history
        ]

        # 获取反馈历史
        feedback = self.retrieve(user_id, category='feedback', top_k=3)
        context['feedback_history'] = [
            {'content': f.content, 'importance': f.effective_importance()}
            for f in feedback
        ]

        return context

    def get_stats(self, user_id: Optional[int] = None) -> Dict:
        """获取统计信息（传入 user_id 时只统计该用户）"""
        from sqlalchemy import func

        query = self.db_session.query(MemoryFragment)
        if user_id is not None:
            query = query.filter(MemoryFragment.user_id == user_id)

        total_fragments = query.count()
        total_users = query.with_entities(func.count(func.distinct(MemoryFragment.user_id))).scalar() or 0

        return {
            'total_users': total_users,
            'total_fragments': total_fragments,
            'vector_store_enabled': self.vector_store_enabled,
            'avg_fragments_per_user': total_fragments / max(1, total_users)
        }
