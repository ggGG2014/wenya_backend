"""
文芽 - 测试社区举报功能和隐私保护

用法：python -m pytest tests/test_community_report.py -v
"""
import pytest
from models.community import CommunityWork, WorkReport
from models.user import User


class TestWorkReport:
    """测试作品举报功能"""

    def test_report_work_success(self, client, auth_client, test_user):
        """测试举报作品成功"""
        # 创建一个作品
        with client.application.app_context():
            work = CommunityWork(
                writing_id=1,
                user_id=test_user.id,
                title='测试作品',
                content='这是测试内容',
                word_count=10,
                author_grade=8,
                author_school_stage='middle',
                review_status='approved',
                published_at='2024-01-01'
            )
            from app import db
            db.session.add(work)
            db.session.commit()
            work_id = work.id

        # 举报作品
        response = client.post(
            f'/api/community/works/{work_id}/report',
            json={
                'reason': 'inappropriate_content',
                'description': '这篇作品包含不当内容'
            },
            cookies={'session': auth_client}
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data['data']['report_id'] is not None
        assert data['data']['reason'] == 'inappropriate_content'
        assert data['message'] == '举报已提交，我们会尽快处理'

    def test_report_own_work(self, client, auth_client, test_user):
        """测试举报自己的作品"""
        with client.application.app_context():
            work = CommunityWork(
                writing_id=1,
                user_id=test_user.id,
                title='测试作品',
                content='测试内容',
                word_count=10,
                author_grade=8,
                author_school_stage='middle',
                review_status='approved'
            )
            from app import db
            db.session.add(work)
            db.session.commit()
            work_id = work.id

        response = client.post(
            f'/api/community/works/{work_id}/report',
            json={'reason': 'spam'},
            cookies={'session': auth_client}
        )

        assert response.status_code == 400
        assert '不能举报自己的作品' in response.get_json()['error']

    def test_report_duplicate(self, client, auth_client, test_user):
        """测试重复举报"""
        with client.application.app_context():
            work = CommunityWork(
                writing_id=1,
                user_id=test_user.id + 1,  # 其他人的作品
                title='测试作品',
                content='测试内容',
                review_status='approved'
            )
            from app import db
            db.session.add(work)
            db.session.commit()
            work_id = work.id

        # 第一次举报
        client.post(
            f'/api/community/works/{work_id}/report',
            json={'reason': 'spam'},
            cookies={'session': auth_client}
        )

        # 第二次举报
        response = client.post(
            f'/api/community/works/{work_id}/report',
            json={'reason': 'spam'},
            cookies={'session': auth_client}
        )

        assert response.status_code == 409
        assert '已举报过' in response.get_json()['error']

    def test_report_invalid_reason(self, client, auth_client, test_user):
        """测试无效的举报原因"""
        with client.application.app_context():
            work = CommunityWork(
                writing_id=1,
                user_id=test_user.id + 1,
                title='测试作品',
                content='测试内容',
                review_status='approved'
            )
            from app import db
            db.session.add(work)
            db.session.commit()
            work_id = work.id

        response = client.post(
            f'/api/community/works/{work_id}/report',
            json={'reason': 'invalid_reason'},
            cookies={'session': auth_client}
        )

        assert response.status_code == 400
        assert '无效的举报原因' in response.get_json()['error']

    def test_get_my_report(self, client, auth_client, test_user):
        """测试获取自己的举报状态"""
        with client.application.app_context():
            work = CommunityWork(
                writing_id=1,
                user_id=test_user.id + 1,
                title='测试作品',
                content='测试内容',
                review_status='approved'
            )
            report = WorkReport(
                work_id=work.id,
                user_id=test_user.id,
                reason='spam',
                status='pending'
            )
            from app import db
            db.session.add_all([work, report])
            db.session.commit()
            work_id = work.id

        response = client.get(
            f'/api/community/works/{work_id}/report',
            cookies={'session': auth_client}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['data']['report'] is not None
        assert data['data']['report']['reason'] == 'spam'


class TestPrivacyProtection:
    """测试隐私保护功能"""

    def test_elementary_grade_obfuscation(self, client):
        """测试小学年级模糊处理"""
        with client.application.app_context():
            work = CommunityWork(
                writing_id=1,
                user_id=1,
                title='小学生作品',
                content='测试内容',
                word_count=100,
                author_grade=4,
                author_school_stage='elementary',
                review_status='approved'
            )
            from app import db
            db.session.add(work)
            db.session.commit()
            work_id = work.id

        response = client.get(f'/api/community/works/{work_id}')
        assert response.status_code == 200

        data = response.get_json()['data']['work']
        # 不应该有具体的 user_id
        assert 'user_id' not in data
        # 应该有模糊处理的年级
        assert data['author_grade_text'] == '小学 4 年级'
        assert data['author']['school_stage'] == 'elementary'

    def test_middle_school_grade_display(self, client):
        """测试中学年级正常显示"""
        with client.application.app_context():
            work = CommunityWork(
                writing_id=1,
                user_id=1,
                title='中学生作品',
                content='测试内容',
                author_grade=8,
                author_school_stage='middle',
                review_status='approved'
            )
            from app import db
            db.session.add(work)
            db.session.commit()
            work_id = work.id

        response = client.get(f'/api/community/works/{work_id}')
        assert response.status_code == 200

        data = response.get_json()['data']['work']
        assert data['author_grade_text'] == '8 年级'
        assert data['author']['school_stage'] == 'middle'

    def test_work_list_privacy(self, client):
        """测试作品列表的隐私保护"""
        with client.application.app_context():
            for i in range(3):
                work = CommunityWork(
                    writing_id=i + 1,
                    user_id=1,
                    title=f'作品{i}',
                    content='测试内容',
                    author_grade=4 if i == 0 else 8,
                    author_school_stage='elementary' if i == 0 else 'middle',
                    review_status='approved',
                    like_count=i * 10,
                    comment_count=i * 2
                )
                from app import db
                db.session.add(work)
            db.session.commit()

        response = client.get('/api/community/works')
        assert response.status_code == 200

        data = response.get_json()['data']['items']
        assert len(data) == 3

        for work in data:
            # 都不应该有 user_id
            assert 'user_id' not in work
            # 都应该有作者信息
            assert 'author' in work
            assert 'nickname' in work['author']

    def test_comment_author_privacy(self, client, auth_client):
        """测试评论作者隐私保护"""
        with client.application.app_context():
            work = CommunityWork(
                writing_id=1,
                user_id=1,
                title='测试作品',
                content='测试内容',
                review_status='approved'
            )
            from app import db
            db.session.add(work)
            db.session.commit()
            work_id = work.id

        response = client.get(f'/api/community/works/{work_id}/comments')
        assert response.status_code == 200

        # 评论数据不应该包含 user_id
        comments = response.get_json()['data']['comments']
        for comment in comments:
            assert 'user_id' not in comment
