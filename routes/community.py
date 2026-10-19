"""
文芽 - 社区路由
"""
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime

from app import db, limiter
from models.community import CommunityWork, WorkLike, WorkComment, WorkReport
from models.writing import Writing
from models.user import User
from models.compliance import ComplianceLog
from utils.response import success_response, error_response, paginated_response
from services.content_safe import content_safety_check

community_bp = Blueprint('community', __name__)


def _serialize_work(work, include_content=False):
    """
    序列化作品（隐私保护增强）
    - 不暴露 user_id
    - 小学作品模糊年级
    - 作者匿名化
    """
    result = work.to_dict(include_content=include_content)

    # 隐私保护：移除 user_id
    result.pop('user_id', None)
    result.pop('writing_id', None)

    # 小学作品模糊年级（保护未成年人隐私）
    if work.author_school_stage == 'elementary':
        # 小学生只显示"小学 X 年级"，不暴露具体年级
        grade_text = f"小学 {work.author_grade}年级" if work.author_grade else '小学'
        result['author_grade_text'] = grade_text
    else:
        result['author_grade_text'] = f"{work.author_grade}年级" if work.author_grade else None

    # 作者匿名化
    result['author'] = {
        'nickname': '匿名同学',
        'school_stage': work.author_school_stage,
        'grade_text': result['author_grade_text']
    }

    # 移除原始字段，只保留脱敏后的数据
    result.pop('author_grade', None)
    result.pop('author_school_stage', None)

    return result


@community_bp.route('/works', methods=['GET'])
def list_works():
    """
    获取社区作品列表
    支持按体裁/年级/维度多维筛选
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)

    grade = request.args.get('grade', type=int)
    school_stage = request.args.get('school_stage')
    genre = request.args.get('genre')
    tag = request.args.get('tag')
    keyword = (request.args.get('q') or '').strip()
    featured_only = request.args.get('featured', '').lower() in ('1', 'true')

    # 作者关闭"公开展示作品"后，其作品不再出现在社区
    query = CommunityWork.query.join(User, User.id == CommunityWork.user_id).filter(
        CommunityWork.is_deleted == False,
        CommunityWork.review_status == 'approved',
        User.show_works_publicly == True
    )

    if keyword:
        query = query.filter(CommunityWork.title.contains(keyword))
    if featured_only:
        query = query.filter(CommunityWork.is_featured == True)

    if grade:
        query = query.filter(CommunityWork.author_grade == grade)
    elif school_stage:
        if school_stage == 'elementary':
            query = query.filter(CommunityWork.author_grade.between(1, 6))
        elif school_stage == 'middle':
            query = query.filter(CommunityWork.author_grade.between(7, 9))
        elif school_stage == 'high':
            query = query.filter(CommunityWork.author_grade.between(10, 12))

    if genre:
        query = query.filter(CommunityWork.genre == genre)

    if tag:
        query = query.filter(CommunityWork.tags.contains([tag]))

    query = query.order_by(
        (CommunityWork.like_count + CommunityWork.comment_count * 2).desc(),
        CommunityWork.published_at.desc()
    )

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    works = []
    for w in pagination.items:
        item = _serialize_work(w, include_content=False)
        item['excerpt'] = (w.content or '')[:100]
        works.append(item)

    return paginated_response(works, pagination)


@community_bp.route('/works/<int:work_id>', methods=['GET'])
def get_work(work_id):
    """获取作品详情"""
    work = CommunityWork.query.filter_by(id=work_id, is_deleted=False).first_or_404()
    # 未通过审核的作品只有作者本人可见
    if work.review_status != 'approved' and not (current_user.is_authenticated and current_user.id == work.user_id):
        return error_response('作品不存在', status_code=404)

    work.view_count = (work.view_count or 0) + 1

    is_liked = False
    if current_user.is_authenticated:
        is_liked = WorkLike.query.filter_by(
            work_id=work_id,
            user_id=current_user.id
        ).first() is not None

    db.session.commit()

    result = _serialize_work(work, include_content=True)
    result['review_status'] = work.review_status
    result['is_mine'] = current_user.is_authenticated and current_user.id == work.user_id
    result['is_liked'] = is_liked
    return success_response({'work': result})


@community_bp.route('/works/<int:work_id>/like', methods=['POST'])
@login_required
def like_work(work_id):
    """点赞作品"""
    work = CommunityWork.query.filter_by(id=work_id, is_deleted=False).first_or_404()

    existing_like = WorkLike.query.filter_by(
        work_id=work_id,
        user_id=current_user.id
    ).first()

    if existing_like:
        db.session.delete(existing_like)
        work.like_count = max(0, work.like_count - 1)
        is_liked = False
    else:
        like = WorkLike(work_id=work_id, user_id=current_user.id)
        db.session.add(like)
        work.like_count += 1
        is_liked = True

    db.session.commit()

    return success_response({
        'like_count': work.like_count,
        'is_liked': is_liked
    }, message=f'已{"点赞" if is_liked else "取消点赞"}')


@community_bp.route('/works/<int:work_id>/comment', methods=['POST'])
@login_required
def comment_work(work_id):
    """评论作品"""
    work = CommunityWork.query.filter_by(id=work_id, is_deleted=False).first_or_404()

    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    parent_id = data.get('parent_id')
    if parent_id is not None:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            return error_response('无效的回复对象', status_code=400)
        if not WorkComment.query.filter_by(id=parent_id, work_id=work_id, is_deleted=False).first():
            return error_response('回复的评论不存在', status_code=404)

    if not content:
        return error_response('评论内容不能为空', status_code=400)

    if len(content) > 500:
        return error_response('评论内容不能超过 500 字', status_code=400)

    safety = content_safety_check(content)
    if not safety['is_safe']:
        return error_response('评论包含不当内容，请修改后重试', status_code=400)

    comment = WorkComment(
        work_id=work_id,
        user_id=current_user.id,
        content=content,
        parent_id=parent_id,
        is_approved=True
    )
    db.session.add(comment)

    work.comment_count += 1

    compliance_log = ComplianceLog(
        log_type='user_action',
        user_id=current_user.id,
        related_id=work_id,
        related_type='community_work',
        action='comment_created',
        ip_address=request.remote_addr
    )
    db.session.add(compliance_log)

    db.session.commit()

    return success_response({'comment': _comment_dict(comment)}, message='评论成功', status_code=201)


@community_bp.route('/works/<int:work_id>/comments', methods=['GET'])
def get_comments(work_id):
    """获取作品评论列表"""
    comments = WorkComment.query.filter_by(
        work_id=work_id,
        is_approved=True,
        is_deleted=False
    ).order_by(WorkComment.created_at.asc()).all()

    return success_response({'comments': [_comment_dict(c) for c in comments]})


def _comment_dict(comment):
    """评论 + 作者昵称（不暴露其他个人信息）"""
    result = comment.to_dict()
    author = db.session.get(User, comment.user_id)
    result['author_name'] = (author.nickname or author.username) if author else '已注销用户'
    result['is_mine'] = current_user.is_authenticated and current_user.id == comment.user_id
    # 隐私保护：不暴露用户 ID
    result.pop('user_id', None)
    return result


@community_bp.route('/works/<int:work_id>/comments/<int:comment_id>', methods=['DELETE'])
@login_required
def delete_comment(work_id, comment_id):
    """删除自己的评论"""
    comment = WorkComment.query.filter_by(
        id=comment_id,
        work_id=work_id,
        is_deleted=False
    ).first_or_404()

    if comment.user_id != current_user.id:
        return error_response('无权删除该评论', status_code=403)

    comment.is_deleted = True
    comment.deleted_at = datetime.utcnow()

    work = CommunityWork.query.filter_by(id=work_id).first()
    if work:
        work.comment_count = max(0, work.comment_count - 1)

    db.session.commit()

    return success_response(message='评论已删除')


@community_bp.route('/works/<int:work_id>/report', methods=['POST'])
@login_required
@limiter.limit("5 per hour")
def report_work(work_id):
    """
    举报作品
    每个用户对同一作品只能举报一次
    """
    work = CommunityWork.query.filter_by(id=work_id, is_deleted=False).first_or_404()

    # 不能举报自己的作品
    if work.user_id == current_user.id:
        return error_response('不能举报自己的作品', status_code=400)

    data = request.get_json()
    if not data:
        return error_response('Invalid request', status_code=400)

    reason = (data.get('reason') or '').strip()
    description = (data.get('description') or '').strip()

    # 验证举报原因
    if not reason:
        return error_response('请选择举报原因', status_code=400)

    valid_reasons = list(WorkReport.REASONS.keys())
    if reason not in valid_reasons:
        return error_response(f'无效的举报原因，可选：{", ".join(valid_reasons)}', status_code=400)

    # 检查是否已举报过
    existing_report = WorkReport.query.filter_by(
        work_id=work_id,
        user_id=current_user.id
    ).first()

    if existing_report:
        return error_response('你已举报过该作品，请勿重复举报', status_code=409)

    # 创建举报记录
    report = WorkReport(
        work_id=work_id,
        user_id=current_user.id,
        reason=reason,
        description=description[:500] if description else None
    )
    db.session.add(report)

    compliance_log = ComplianceLog(
        log_type='content_review',
        user_id=current_user.id,
        related_id=work_id,
        related_type='community_work',
        action='work_reported',
        details={'reason': reason, 'report_id': report.id},
        ip_address=request.remote_addr
    )
    db.session.add(compliance_log)
    db.session.commit()

    return success_response({
        'report_id': report.id,
        'reason': reason,
        'reason_label': WorkReport.get_reason_label(reason)
    }, message='举报已提交，我们会尽快处理', status_code=201)


@community_bp.route('/works/<int:work_id>/report', methods=['GET'])
@login_required
def get_my_report(work_id):
    """获取我对该作品的举报状态"""
    report = WorkReport.query.filter_by(
        work_id=work_id,
        user_id=current_user.id
    ).first()

    if not report:
        return success_response({'report': None})

    return success_response({
        'report': report.to_dict()
    })


@community_bp.route('/publish/<int:writing_id>', methods=['POST'])
@login_required
def publish_work(writing_id):
    """
    将作文发布到社区
    需要审核通过后才公开
    """
    writing = Writing.query.filter_by(
        id=writing_id,
        user_id=current_user.id,
        is_deleted=False
    ).first_or_404()

    if not writing.is_scored:
        return error_response('作文需先完成评分才能发布', status_code=400)

    existing_work = CommunityWork.query.filter_by(writing_id=writing_id).first()
    if existing_work:
        return error_response('该作文已发布过', status_code=409)

    data = request.get_json() or {}
    tags = data.get('tags', [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip() for t in tags if str(t).strip()][:5]
    genre = (data.get('genre') or '').strip()[:64] or None

    safety = content_safety_check(writing.title + '\n' + writing.content)
    if not safety['is_safe']:
        return error_response('作品包含不当内容，无法发布', status_code=400)

    # 自动审核：内容安全检查已通过时直接公开（COMMUNITY_AUTO_APPROVE，默认关闭，需人工审核）
    auto_approve = current_app.config.get('COMMUNITY_AUTO_APPROVE', False)
    now = datetime.utcnow()

    work = CommunityWork(
        writing_id=writing_id,
        user_id=current_user.id,
        title=writing.title,
        content=writing.content,
        word_count=writing.word_count,
        author_grade=current_user.grade,
        author_school_stage=current_user.get_school_stage(),
        overall_score=writing.overall_score,
        dimension_scores=writing.scores.to_dict() if writing.scores else None,
        tags=tags,
        genre=genre,
        review_status='approved' if auto_approve else 'pending',
        reviewed_at=now if auto_approve else None,
        reviewed_by='auto' if auto_approve else None,
        published_at=now
    )
    db.session.add(work)

    writing.is_public = True
    writing.published_at = now
    if auto_approve:
        writing.status = 'published'

    compliance_log = ComplianceLog(
        log_type='content_review',
        user_id=current_user.id,
        related_id=writing_id,
        related_type='writing',
        action='work_submitted_for_review',
        ip_address=request.remote_addr
    )
    db.session.add(compliance_log)

    db.session.commit()

    db.session.refresh(work)
    result = _serialize_work(work, include_content=False)
    result['review_status'] = work.review_status
    return success_response(
        {'work': result},
        message='作品已发布到社区' if auto_approve else '作品已提交审核，审核通过后将公开',
        status_code=201
    )


@community_bp.route('/featured', methods=['GET'])
def get_featured_works():
    """获取精选作品"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 6, type=int)

    pagination = CommunityWork.query.filter(
        CommunityWork.is_featured == True,
        CommunityWork.is_deleted == False,
        CommunityWork.review_status == 'approved'
    ).order_by(CommunityWork.published_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    works = [_serialize_work(w, include_content=False) for w in pagination.items]

    return paginated_response(works, pagination)
