"""
文芽 - 开发环境示例数据

用法：python seed_data.py
可重复执行：已存在的账号会跳过，已有评分作品的账号不会重复生成作品。

======================== 测试账号（仅限本地开发） ========================
所有示例账号的密码均为 SEED_PASSWORD（见下方常量）

  用户名           年级   说明
  test_student     8      主测试账号：5 篇已评分作文（成绩逐步提升）+ 1 篇草稿，
                          有 AI 记忆片段和一段 AI 对话记录
  demo_xiaoming    8      同年级同学（排行榜对比用）
  demo_lihua       8      同年级同学
  demo_wangfang    8      同年级同学，已退出排行榜（show_in_ranking=False）
  demo_xiaoyu      4      小学生
  demo_zhangwei    11     高中生
========================================================================

示例数据中的评分与评语均为手工构造，ai_comment 以【示例数据】开头，并非真实 AI 评分。
"""
import random
from datetime import datetime, timedelta, date, timezone

from app import create_app, db
from models.user import User, Guardian, UserProfile
from models.writing import Writing, WritingScore
from models.ai_memory import AIMemory, AIConversation
from models.community import CommunityWork, WorkLike, WorkComment
from utils.helpers import count_words

SEED_PASSWORD = 'Passw0rd123'

ACCOUNTS = [
    # username, nickname, grade, birth_date, guardian_name, guardian_phone, relationship, base_score, trend, show_in_ranking
    ('test_student', None, 8, '2012-05-01', '测试家长', '13800138000', 'parent', 72, 3.0, True),
    ('demo_xiaoming', '小明', 8, '2012-03-12', '王建国', '13800138001', '父子', 78, 1.0, True),
    ('demo_lihua', '李华', 8, '2012-09-30', '李秀英', '13800138002', '母女', 83, 0.5, True),
    ('demo_wangfang', '王芳', 8, '2012-07-08', '王强', '13800138003', '父女', 75, 2.0, False),
    ('demo_xiaoyu', '小雨', 4, '2016-04-18', '陈静', '13800138004', '母女', 80, 1.0, True),
    ('demo_zhangwei', '张伟', 11, '2009-11-02', '张志刚', '13800138005', '父子', 81, 1.5, True),
]

# 每个账号分到的作文（标题、写作要求、正文、文体）
MIDDLE_ESSAYS = [
    ('那一次，我读懂了坚持', '以"那一次，我读懂了____"为题，写一篇记叙文。',
     '去年冬天，我报名参加了学校的长跑队。第一次训练，跑到第三圈我就喘不上气，双腿像灌了铅一样。'
     '教练没有让我停下，只是在旁边陪我慢慢跑。他说："不要看终点，看脚下的下一步。"'
     '后来每天清晨，我都比别人早到二十分钟。一个月后的测试，我第一次跑完了全程。'
     '冲过终点线的那一刻，我终于明白，坚持不是咬牙硬撑，而是一次又一次地迈出下一步。', '记叙文'),
    ('我的书桌', '以身边的一件物品为对象，写一篇状物抒情的文章。',
     '我的书桌是爸爸亲手做的，桌面上有一道浅浅的划痕，那是我小学时用小刀刻下的"早"字。'
     '书桌左边堆着课本，右边放着一盏旧台灯。无数个夜晚，灯光把我和书桌圈在一个温暖的小世界里。'
     '有时作业写不出来，我就趴在桌上发呆，摸着那个"早"字，想起鲁迅先生的故事。'
     '书桌不会说话，却陪我度过了最安静也最用功的时光。', '状物散文'),
    ('网络让生活更美好吗', '围绕"网络与生活"谈谈你的看法，写一篇议论文。',
     '有人说网络让人变得孤独，也有人说网络拉近了人与人的距离。我认为，网络本身没有好坏，关键在于如何使用。'
     '疫情期间，网课让我们停课不停学；外婆通过视频电话，每天都能看到远方的孙子。这是网络带来的温暖。'
     '但沉迷短视频、熬夜刷手机，也让不少同学成绩下滑。'
     '因此，我们应当做网络的主人，而不是被网络牵着走。合理安排时间，网络才能真正让生活更美好。', '议论文'),
    ('秋天的校园', '描写一处你熟悉的景物，注意运用多种修辞手法。',
     '秋天的校园像一幅刚刚完成的油画。操场边的银杏树换上了金黄的衣裳，风一吹，叶子便像蝴蝶一样翩翩起舞。'
     '教学楼前的桂花开了，香气钻进教室，连读书声都变得甜丝丝的。'
     '放学时，夕阳把同学们的影子拉得很长很长。我踩着落叶走出校门，听见脚下沙沙作响，'
     '仿佛秋天在轻轻地和我说再见。', '写景散文'),
    ('给十年后的自己', '以书信的形式，给十年后的自己写一封信。',
     '十年后的我：你好！写这封信的时候，我正在为下周的期中考试复习，桌上摊满了试卷。'
     '不知道十年后的你，是否实现了当一名医生的梦想？是否还记得初二那年，为了一道几何题熬到深夜？'
     '我希望你依然保持好奇心，依然愿意为喜欢的事情努力。'
     '如果你遇到了困难，请回头看看现在的我——那个虽然普通、却从不轻言放弃的少年。此致，敬礼！', '书信'),
    ('我最敬佩的人', '写一位你敬佩的人，通过具体事例表现人物品质。',
     '我最敬佩的人是我们小区的保安刘叔叔。每天清晨六点，他就开始在小区里巡逻，风雨无阻。'
     '有一次下暴雨，地下车库进水，刘叔叔第一个冲下去，一边疏导车辆，一边用沙袋堵住入口。'
     '等雨停了，他浑身湿透，却笑着说："大家的车没事就好。"'
     '刘叔叔没有惊天动地的事迹，但他的责任心，让我懂得了平凡岗位上的伟大。', '记叙文'),
    ('读《西游记》有感', '选择一本你读过的名著，写一篇读后感。',
     '读完《西游记》，我最喜欢的不是神通广大的孙悟空，而是看似平凡的沙和尚。'
     '他没有七十二变，也不会腾云驾雾，却一路挑着担子，任劳任怨。'
     '师徒四人能取得真经，靠的不只是悟空的本领，还有沙僧这样默默付出的坚持。'
     '生活中，我们大多数人都是"沙和尚"，但只要踏实走好每一步，同样能到达自己的"西天"。', '读后感'),
    ('一次难忘的实验', '记叙一次课堂或课外的经历，写出自己的感受。',
     '物理课上，老师让我们分组做"自制简易电动机"的实验。我和同桌按照步骤绕线圈、装磁铁，'
     '可接通电池后，线圈一动不动。我们检查了好几遍，急得满头大汗。'
     '最后发现，是线圈两端的漆没有刮干净。重新处理后，线圈终于欢快地转了起来。'
     '那一刻我明白了，科学容不得半点马虎，细节往往决定成败。', '记叙文'),
    ('家乡的味道', '以"味道"为线索，写一篇表达情感的文章。',
     '每到过年，外婆都会包一大锅荠菜饺子。荠菜是她清早去田埂上挖的，洗净、焯水、剁碎，每一步都不马虎。'
     '饺子下锅，白白胖胖地浮起来，咬一口，满嘴都是春天的清香。'
     '后来我们搬进了城市，超市里也能买到速冻饺子，可我总觉得少了点什么。'
     '我想，那少了的，是外婆布满老茧的双手，是家乡泥土的芬芳。', '抒情散文'),
    ('学会倾听', '以"学会____"为题，写一篇文章。',
     '以前和妈妈说话，她刚开口，我就不耐烦地打断："知道了，知道了。"'
     '直到有一天，妈妈很晚才下班，坐在沙发上一句话也不说。我第一次安静地坐在她身边，听她讲工作上的烦恼。'
     '说完后，她长舒一口气，摸摸我的头说："谢谢你听我说这些。"'
     '原来，倾听也是一种关心。学会倾听，我们才能真正走进别人的心里。', '记叙文'),
    ('我眼中的"双减"', '结合自身经历，谈谈你对"双减"政策的看法。',
     '"双减"以后，我的作业少了，周末也不用再奔波于各个补习班。'
     '多出来的时间，我学会了做饭，还加入了学校的篮球社团。'
     '当然，也有同学因为没有人督促，学习反而松懈了。'
     '我认为，"双减"减去的是负担，而不是责任。自主安排时间、主动学习，才是我们应该交出的答卷。', '议论文'),
    ('雨中的温暖', '写一件发生在雨天的小事，表达真情实感。',
     '那天放学，天突然下起了大雨。我站在校门口，望着密密麻麻的雨帘发愁。'
     '这时，一把蓝色的伞撑到了我头顶，是隔壁班一个不太熟悉的女生。'
     '"我们顺路，一起走吧。"一路上，她把伞往我这边斜，自己的肩膀湿了一大片。'
     '到家后，我才想起还没问她的名字。雨早已停了，那份温暖却一直留在我心里。', '记叙文'),
    ('假如我是一棵树', '展开想象，写一篇想象作文。',
     '假如我是一棵树，我愿意长在学校的操场边。春天，我用嫩绿的新芽向同学们问好；'
     '夏天，我撑开浓密的枝叶，为跑步的同学遮挡烈日；秋天，我把金黄的叶子送给爱画画的孩子做书签；'
     '冬天，我静静地站着，听教室里传来的读书声。'
     '我不会说话，却能见证一届又一届学生的成长，这该是多么幸福的事啊！', '想象作文'),
]

ELEMENTARY_ESSAYS = [
    ('我的好朋友', '介绍你的一位好朋友。',
     '我的好朋友叫乐乐，她有一双大大的眼睛，笑起来像弯弯的月亮。'
     '有一次我忘带铅笔，乐乐马上把她最喜欢的小兔子铅笔借给我。'
     '下课了，我们一起跳绳、踢毽子，玩得可开心了。我喜欢我的好朋友乐乐！', '记叙文'),
    ('可爱的小狗', '写一种你喜欢的小动物。',
     '我家有一只小狗，叫豆豆。它全身毛茸茸的，像一个白色的小绒球。'
     '每天我放学回家，豆豆就摇着尾巴跑过来迎接我。'
     '它最爱吃骨头，吃饱了就趴在阳台上晒太阳。豆豆真是一只可爱的小狗！', '状物'),
    ('春天来了', '观察春天的景色，写一写。',
     '春天来了，小草从地里探出头来，柳树姐姐梳起了绿色的长辫子。'
     '桃花开了，粉红粉红的，像小姑娘的脸蛋。小燕子从南方飞回来了，在空中叽叽喳喳地唱歌。'
     '我爱春天！', '写景'),
]

HIGH_ESSAYS = [
    ('论慢的价值', '在快节奏的时代，谈谈"慢"的意义。',
     '在这个追求效率的时代，"快"似乎成了衡量一切的标准。然而，真正有价值的东西，往往需要慢下来才能获得。'
     '敦煌研究院的樊锦诗先生，在大漠中守护莫高窟半个多世纪；袁隆平院士在稻田里一干就是几十年。'
     '他们的"慢"，恰恰成就了非凡的事业。慢，不是懒惰与拖延，而是对事物规律的尊重，对内心节奏的坚守。'
     '当我们学会在喧嚣中慢下来，才能听见时代深处真正的回声。', '议论文'),
    ('故乡的老槐树', '以一个承载记忆的事物为线索，写一篇散文。',
     '村口的老槐树，据说已经有一百多岁了。树干粗得要三个人才能合抱，树皮皲裂，像老人手背上的纹路。'
     '小时候，夏夜里全村人都在树下乘凉，爷爷摇着蒲扇讲古，萤火虫在枝叶间明明灭灭。'
     '如今村里的年轻人大多外出打工，树下冷清了许多。可每次回乡，远远望见那团浓绿，我的心就安定下来。'
     '老槐树站成了故乡的模样，也站成了游子心中永远的坐标。', '散文'),
    ('人工智能时代的我们', '面对人工智能的发展，青年应当如何自处？',
     '当人工智能可以写诗、作画、编程，许多人开始担忧：人类的价值何在？'
     '我认为，技术越强大，人之为人的特质就越珍贵。机器能够模仿表达，却难以替代真实的情感与独立的思考。'
     '作为青年，我们既要善用工具，提升学习与创造的效率，更要守住批判性思维与人文关怀。'
     '唯有如此，人工智能才会成为我们的助手，而不是我们思考的替代品。', '议论文'),
]

ESSAY_PLAN = {
    'test_student': [MIDDLE_ESSAYS[i] for i in (0, 1, 2, 3, 4)],
    'demo_xiaoming': [MIDDLE_ESSAYS[i] for i in (5, 6, 7)],
    'demo_lihua': [MIDDLE_ESSAYS[i] for i in (8, 9, 10)],
    'demo_wangfang': [MIDDLE_ESSAYS[i] for i in (11, 12)],
    'demo_xiaoyu': ELEMENTARY_ESSAYS,
    'demo_zhangwei': HIGH_ESSAYS,
}

DIMENSIONS = ['task', 'theme', 'content', 'structure', 'language', 'genre', 'thinking']

STAGE_WEIGHTS = {
    'elementary': {"task": 0.15, "theme": 0.10, "content": 0.20, "structure": 0.15, "language": 0.25, "genre": 0.10, "thinking": 0.05},
    'middle': {"task": 0.10, "theme": 0.15, "content": 0.20, "structure": 0.15, "language": 0.20, "genre": 0.10, "thinking": 0.10},
    'high': {"task": 0.10, "theme": 0.20, "content": 0.20, "structure": 0.15, "language": 0.15, "genre": 0.10, "thinking": 0.10},
}

COMMENTS = {
    'high': ('【示例数据】文章结构完整，语言流畅，细节描写生动，较好地完成了写作任务。',
             ['可以在结尾进一步升华主题', '尝试运用更多样的句式', '适当增加环境描写烘托情感']),
    'mid': ('【示例数据】文章内容基本完整，中心较明确，但部分段落过渡略显生硬，细节还可以更丰富。',
            ['补充一两个具体事例支撑中心', '注意段落之间的衔接', '减少口语化表达']),
}


def stage_of(grade):
    return 'elementary' if grade <= 6 else 'middle' if grade <= 9 else 'high'


def get_or_create_user(app, spec):
    username, nickname, grade, birth, g_name, g_phone, relation, _, _, show = spec
    user = User.query.filter_by(username=username).first()
    if user:
        print(f'  · 账号已存在：{username}')
        return user, False

    guardian = Guardian.query.filter_by(phone=g_phone).first()
    if not guardian:
        guardian = Guardian(
            name=g_name, phone=g_phone, relationship=relation,
            is_verified=True, verified_at=datetime.now(timezone.utc), verification_method='sms',
            consent_given_at=datetime.now(timezone.utc),
            consent_expires_at=datetime.now(timezone.utc) + timedelta(days=365 * 3)
        )
        db.session.add(guardian)
        db.session.flush()

    user = User(
        username=username, nickname=nickname, grade=grade,
        birth_date=date.fromisoformat(birth),
        is_guardian_verified=True, guardian_id=guardian.id,
        show_in_ranking=show
    )
    user.set_password(SEED_PASSWORD)
    db.session.add(user)
    db.session.flush()
    db.session.add(UserProfile(user_id=user.id))
    db.session.add(AIMemory(user_id=user.id))
    db.session.flush()
    print(f'  + 创建账号：{username}（{grade} 年级）')
    return user, True


def seed_writings(user, spec):
    username, _, grade, _, _, _, _, base, trend, _ = spec
    if Writing.query.filter_by(user_id=user.id, is_scored=True).count() > 0:
        print(f'  · {username} 已有评分作文，跳过')
        return []

    rng = random.Random(username)  # 固定种子，结果可复现
    essays = ESSAY_PLAN[username]
    stage = stage_of(grade)
    weights = STAGE_WEIGHTS[stage]
    now = datetime.now(timezone.utc)
    created = []

    for i, (title, prompt, content, genre) in enumerate(essays):
        # 时间分布在最近 28 天内，越靠后越新
        submitted_at = now - timedelta(days=28 - i * (24 // max(1, len(essays) - 1)), hours=rng.randint(0, 8))
        level = base + trend * i

        dims = {d: max(50, min(98, round(level + rng.uniform(-6, 6)))) for d in DIMENSIONS}
        comment, suggestions = COMMENTS['high' if level >= 80 else 'mid']

        writing = Writing(
            user_id=user.id, title=title, prompt=prompt, content=content,
            word_count=count_words(content), status='submitted', is_scored=True,
            review_status='approved', reviewed_by='seed', reviewed_at=submitted_at,
            created_at=submitted_at - timedelta(hours=1), submitted_at=submitted_at
        )
        db.session.add(writing)
        db.session.flush()

        score = WritingScore(
            writing_id=writing.id,
            **{f'{d}_score': v for d, v in dims.items()},
            weights=weights, ai_comment=comment, ai_suggestions=suggestions,
            confidence=0.9, needs_human_review=False, created_at=submitted_at
        )
        db.session.add(score)
        writing.overall_score = score.calculate_overall()
        writing.scores = score
        created.append((writing, score, genre))

    # 更新用户画像
    profile = user.profile
    overall = [w.overall_score for w, _, _ in created]
    avg = lambda key: round(sum(getattr(s, f'{key}_score') for _, s, _ in created) / len(created))
    profile.total_writings = len(created)
    profile.average_score = round(sum(overall) / len(overall), 1)
    profile.best_score = max(overall)
    profile.consecutive_days = rng.randint(1, 6)
    profile.dimension_scores = {
        'theme': avg('theme'), 'content': avg('content'), 'structure': avg('structure'),
        'language': avg('language'), 'creativity': avg('thinking')
    }
    ranked_dims = sorted(['theme', 'content', 'structure', 'language', 'thinking'], key=avg, reverse=True)
    labels = {'theme': '立意', 'content': '内容', 'structure': '结构', 'language': '语言', 'thinking': '思维'}
    profile.strength_tags = [labels[d] for d in ranked_dims[:2]]
    profile.weakness_tags = [labels[d] for d in ranked_dims[-2:]]
    profile.preferred_genres = sorted({g for _, _, g in created})[:3]

    print(f'  + {username}：{len(created)} 篇评分作文，平均 {profile.average_score}')
    return created


def publish_best(user, created):
    """把最高分作文发布到社区"""
    if not created:
        return None
    writing, score, genre = max(created, key=lambda c: c[0].overall_score)
    writing.is_public = True
    writing.status = 'published'
    writing.published_at = writing.submitted_at + timedelta(hours=2)
    work = CommunityWork(
        writing_id=writing.id, user_id=user.id, title=writing.title, content=writing.content,
        word_count=writing.word_count, author_grade=user.grade,
        author_school_stage=user.get_school_stage(),
        overall_score=writing.overall_score,
        dimension_scores={d: getattr(score, f'{d}_score') for d in DIMENSIONS},
        review_status='approved', reviewed_by='seed', reviewed_at=writing.published_at,
        tags=[genre], genre=genre, is_featured=writing.overall_score >= 84.5,
        published_at=writing.published_at, view_count=random.Random(writing.title).randint(20, 120)
    )
    db.session.add(work)
    db.session.flush()
    return work


def seed_interactions(users, works):
    """同学之间的点赞与评论"""
    comments = ['写得真好，细节很打动人！', '结尾很有力量，学习了。', '这个比喻用得好妙！', '读完很有共鸣。']
    for work in works:
        for j, user in enumerate(u for u in users if u.id != work.user_id and u.grade >= 7):
            if WorkLike.query.filter_by(work_id=work.id, user_id=user.id).first():
                continue
            db.session.add(WorkLike(work_id=work.id, user_id=user.id))
            work.like_count = (work.like_count or 0) + 1
            if j % 2 == 0:
                db.session.add(WorkComment(work_id=work.id, user_id=user.id,
                                           content=comments[(work.id + j) % len(comments)]))
                work.comment_count = (work.comment_count or 0) + 1


def seed_memory(user, created):
    """为主测试账号写入 AI 记忆（画像 + 记忆片段 + 一段对话）"""
    from services.memory_service import MemoryService
    from models.ai_memory import MemoryFragment

    if MemoryFragment.query.filter_by(user_id=user.id).count() > 0:
        print(f'  · {user.username} 已有记忆片段，跳过')
        return

    ai_memory = AIMemory.query.filter_by(user_id=user.id).first()
    ai_memory.writing_profile = {
        'school_stage': 'middle', 'grade': user.grade,
        'strength_genres': ['记叙文', '写景散文'], 'weakness_genres': ['议论文'],
        'common_errors': ['段落过渡生硬', '论据不够具体'],
        'rhetoric_preferences': ['比喻', '拟人'], 'writing_style': ['细腻', '真诚'],
        'improvement_areas': ['议论文论证结构', '结尾升华']
    }
    ai_memory.knowledge_base = {
        'favorite_materials': ['长跑训练的经历', '外婆视频通话'],
        'learned_examples': [], 'revision_history': [],
        'accumulated_phrases': ['不要看终点，看脚下的下一步'],
        'topic_clusters': ['成长', '校园', '网络与生活']
    }

    memory = MemoryService()
    memory.update_memory_profile(user.id, {'grade': user.grade, 'strength': ['记叙文'], 'weakness': ['议论文']})
    for writing, _, genre in created:
        memory.add_fragment(
            user_id=user.id,
            content=f'作文《{writing.title}》（{genre}）得分 {writing.overall_score}',
            category='feedback', interaction_type='scoring',
            metadata={'writing_id': writing.id, 'overall_score': writing.overall_score}
        )
    memory.add_fragment(user.id, '用户提问：议论文的论据怎么写得更有说服力？', 'interaction', 'writing_guidance')
    memory.add_fragment(user.id, 'AI 回复：可以用"观点 + 具体事例 + 分析"的结构，事例尽量选自己的真实经历或公认的典型人物。',
                        'interaction', 'writing_guidance')

    # 一段 AI 对话（挂在议论文那篇上）
    essay = next((w for w, _, g in created if g == '议论文'), created[0][0])
    t = essay.submitted_at - timedelta(minutes=30)
    db.session.add(AIConversation(
        memory_id=ai_memory.id, user_id=user.id, writing_id=essay.id, session_type='writing_guidance',
        messages=[
            {'role': 'user', 'content': '议论文的论据怎么写得更有说服力？', 'timestamp': t.isoformat()},
            {'role': 'assistant', 'content': '可以用"观点 + 具体事例 + 分析"的结构。你想用哪件事来证明网络带来的好处呢？',
             'timestamp': (t + timedelta(seconds=5)).isoformat()},
        ],
        summary='writing_guidance - 议论文论据', key_points=['写作指导：议论文的论据怎么写得更有说服力']
    ))
    ai_memory.total_interactions = 1
    ai_memory.last_interaction_at = t
    print(f'  + {user.username}：AI 画像、{len(created) + 3} 条记忆片段、1 段对话')


def seed_draft(user):
    if Writing.query.filter_by(user_id=user.id, status='draft', is_deleted=False).count() > 0:
        return
    content = '我的妈妈是一位老师，她每天都很辛苦。'
    db.session.add(Writing(user_id=user.id, title='我的妈妈', content=content,
                           word_count=count_words(content), status='draft'))
    print(f'  + {user.username}：1 篇草稿')


def main():
    app = create_app()
    with app.app_context():
        db.create_all()
        print('== 账号')
        users, created_by_user = [], {}
        for spec in ACCOUNTS:
            user, _ = get_or_create_user(app, spec)
            users.append(user)

        print('== 作文与评分')
        for spec, user in zip(ACCOUNTS, users):
            created_by_user[user.username] = seed_writings(user, spec)

        print('== 社区')
        works = [w for w in (publish_best(u, created_by_user[u.username]) for u in users) if w]
        seed_interactions(users, works)
        print(f'  + 发布 {len(works)} 篇社区作品')

        print('== 主测试账号')
        main_user = users[0]
        if created_by_user[main_user.username]:
            seed_memory(main_user, created_by_user[main_user.username])
        seed_draft(main_user)

        db.session.commit()
        print(f'\n完成。测试账号见 seed_data.py 顶部说明（密码：SEED_PASSWORD 常量）。')


if __name__ == '__main__':
    main()
