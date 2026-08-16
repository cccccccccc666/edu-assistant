import streamlit as st
from openai import OpenAI
import pymysql
import bcrypt
from pypdf import PdfReader
import io
import random
import os
import pandas as pd
import re
from collections import Counter

# ---------- 数据库连接函数（使用扁平 st.secrets） ----------
def get_db_connection():
    return pymysql.connect(
        host=st.secrets["DB_HOST"],
        port=int(st.secrets["DB_PORT"]),
        user=st.secrets["DB_USER"],
        password=st.secrets["DB_PASSWORD"],
        database=st.secrets["DB_NAME"],
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

# ---------- 初始化OpenAI客户端 ----------
client = OpenAI(
    api_key=st.secrets["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com"
)

# ---------- 公共的AI调用函数 ----------
def call_ai(system_prompt, user_message):
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"AI 服务出错：{e}")
        return "暂时无法回答，请稍后重试。"

# ---------- 页面配置 ----------
st.set_page_config(page_title="数智伴学 · 碎碎念小助教", page_icon="🧸")

# ---------- 自定义CSS ----------
st.markdown("""
<style>
    .stApp { background: linear-gradient(145deg, #f6f9fc 0%, #e6f0f5 100%); }
    .main-title { text-align: center; padding: 0.8rem 1rem; background: rgba(255,255,255,0.7); backdrop-filter: blur(6px); border-radius: 30px; margin-bottom: 1.5rem; box-shadow: 0 6px 20px rgba(0,0,0,0.05); border: 1px solid rgba(255,255,255,0.6); }
    .main-title h1 { color: #1e3c5c; font-weight: 700; }
    .main-title p { color: #3a6a8a; font-size: 0.95rem; }
    .custom-card { background: rgba(255,255,255,0.85); backdrop-filter: blur(10px); border-radius: 28px; padding: 1.8rem; box-shadow: 0 12px 40px rgba(0,0,0,0.08); border: 1px solid rgba(255,255,255,0.4); margin-bottom: 1.5rem; }
    .stButton>button { border-radius: 40px !important; background: linear-gradient(135deg, #4f8bc9 0%, #2b5b8c 100%) !important; color: white !important; font-weight: 600 !important; border: none !important; padding: 0.6rem 2rem !important; box-shadow: 0 4px 14px rgba(47, 128, 237, 0.3) !important; transition: 0.3s !important; }
    .stButton>button:hover { transform: scale(1.02) !important; }
    .user-bubble { background: #4f8bc9; color: white; border-radius: 22px 22px 6px 22px; padding: 12px 20px; margin: 8px 0; display: inline-block; max-width: 80%; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }
    .assistant-bubble { background: white; color: #1e293b; border-radius: 22px 22px 22px 6px; padding: 12px 20px; margin: 8px 0; display: inline-block; max-width: 80%; box-shadow: 0 2px 10px rgba(0,0,0,0.04); }
    .stFileUploader { border: 2px dashed #4f8bc9 !important; border-radius: 28px !important; background: rgba(255,255,255,0.5) !important; }
</style>
""", unsafe_allow_html=True)

# ---------- 会话状态初始化 ----------
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'username' not in st.session_state:
    st.session_state.username = None
if 'role' not in st.session_state:
    st.session_state.role = None

# ---------- 从 URL 参数恢复登录状态（刷新保持登录） ----------
def restore_login_from_params():
    params = st.query_params
    if params.get("logged_in") == "true" and params.get("user_id"):
        st.session_state.logged_in = True
        st.session_state.user_id = int(params["user_id"])
        st.session_state.username = params["username"]
        st.session_state.role = params["role"]
        return True
    return False

if not st.session_state.logged_in:
    if not restore_login_from_params():
        pass
    else:
        st.rerun()

# ---------- 辅助函数：用户注册 ----------
def register_user(username, password, role):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                return False, "用户名已存在"
            hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (username, hashed.decode('utf-8'), role)
            )
            conn.commit()
            return True, "注册成功，请登录"
    except Exception as e:
        return False, f"注册失败：{str(e)}"
    finally:
        conn.close()

# ---------- 辅助函数：用户登录 ----------
def login_user(username, password):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, password_hash, role FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
            if not user:
                return False, "用户不存在"
            if bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                return True, user
            else:
                return False, "密码错误"
    except Exception as e:
        return False, f"登录失败：{str(e)}"
    finally:
        conn.close()

# ---------- 辅助函数：保存聊天记录（只保留最近3条） ----------
def save_chat_message(user_id, role, content):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_history (user_id, role, content) VALUES (%s, %s, %s)",
                (user_id, role, content)
            )
            conn.commit()
            cur.execute(
                """
                DELETE FROM chat_history 
                WHERE user_id = %s 
                AND id NOT IN (
                    SELECT id FROM (
                        SELECT id FROM chat_history 
                        WHERE user_id = %s 
                        ORDER BY created_at DESC 
                        LIMIT 3
                    ) AS tmp
                )
                """,
                (user_id, user_id)
            )
            conn.commit()
    except Exception as e:
        st.error(f"保存聊天记录失败：{e}")
    finally:
        conn.close()

# ---------- 辅助函数：获取最近3条聊天记录 ----------
def get_recent_chat(user_id, limit=3):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, content FROM chat_history WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
                (user_id, limit)
            )
            rows = cur.fetchall()
            return list(reversed(rows))
    except Exception as e:
        st.error(f"读取聊天记录失败：{e}")
        return []
    finally:
        conn.close()

# ---------- 辅助函数：课件上传（仅教师） ----------
def upload_courseware(teacher_id, file_name, file_type, file_data):
    ext = file_name.split('.')[-1].lower()
    if ext == file_name:
        ext = 'bin'
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO courseware (teacher_id, file_name, file_type, file_data) VALUES (%s, %s, %s, %s)",
                (teacher_id, file_name, ext, file_data)
            )
            conn.commit()
            return True
    except Exception as e:
        st.error(f"上传课件失败：{e}")
        return False
    finally:
        conn.close()

# ---------- 辅助函数：获取指定教师的所有课件 ----------
def get_teacher_courseware(teacher_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, file_name, upload_time FROM courseware WHERE teacher_id = %s ORDER BY upload_time DESC",
                (teacher_id,)
            )
            return cur.fetchall()
    except Exception as e:
        st.error(f"读取教师课件失败：{e}")
        return []
    finally:
        conn.close()

# ---------- 辅助函数：删除课件（仅限本人） ----------
def delete_courseware(courseware_id, teacher_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM courseware WHERE id = %s AND teacher_id = %s",
                (courseware_id, teacher_id)
            )
            if not cur.fetchone():
                return False, "课件不存在或无权删除"
            cur.execute("DELETE FROM courseware WHERE id = %s", (courseware_id,))
            conn.commit()
            return True, "删除成功"
    except Exception as e:
        return False, f"删除失败：{str(e)}"
    finally:
        conn.close()

# ---------- 辅助函数：获取所有课件（学生预览）含教师名 ----------
def get_all_courseware():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.id, c.file_name, c.file_type, c.file_data, c.upload_time, u.username as teacher_name
                FROM courseware c
                JOIN users u ON c.teacher_id = u.id
                ORDER BY c.upload_time DESC
            """)
            return cur.fetchall()
    except Exception as e:
        st.error(f"读取课件失败：{e}")
        return []
    finally:
        conn.close()

# ---------- 辅助函数：获取学情统计数据（教师看板） ----------
def get_dashboard_stats():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as count FROM chat_history WHERE DATE(created_at)=CURDATE()")
            today_chat = cur.fetchone()['count']
            cur.execute("SELECT COUNT(*) as count FROM courseware")
            total_ppt = cur.fetchone()['count']
            cur.execute("SELECT COUNT(*) as count FROM users")
            total_users = cur.fetchone()['count']
            cur.execute("""
                SELECT DATE(created_at) as date, COUNT(*) as count 
                FROM chat_history 
                WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                GROUP BY DATE(created_at)
                ORDER BY date ASC
            """)
            trend_data = cur.fetchall()
            return today_chat, total_ppt, total_users, trend_data
    except Exception as e:
        st.error(f"读取统计数据失败：{e}")
        return 0, 0, 0, []
    finally:
        conn.close()

# ---------- 获取学生热门提问词（智能合并相似词，拆分长词） ----------
def get_student_hot_keywords(top_n=10):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.content
                FROM chat_history c
                JOIN users u ON c.user_id = u.id
                WHERE u.role = 'student' AND c.role = 'user'
            """)
            rows = cur.fetchall()
            if not rows:
                return []

            # 合并所有提问
            full_text = " ".join([row['content'] for row in rows if row['content']])

            # 去除常见前缀/后缀
            clean_text = re.sub(r'(解释一下|解释|请问|什么是|什么叫|如何|怎么|怎样|能不能|说一下|讲讲|告诉|告诉我|给我|帮忙|帮我|我想问|我问|问一下|请教|请|求|关于|有关|对于|关于)', '', full_text)

            # 将停用词替换为空格（拆分长词）
            stopwords_replace = ['的', '了', '是', '我', '你', '他', '她', '它', '们', '就', '在', '有', '和', '与', '或',
                                  '但', '而', '所', '也', '还', '等', '里', '中', '上', '下', '不', '这', '那', '一', '个',
                                  '去', '来', '到', '对', '从', '会', '可', '能', '以', '之', '被', '把', '给', '让', '用',
                                  '因', '为', '如', '果', '时', '后', '前', '左', '右', '大', '小', '多', '少', '更', '最',
                                  '很', '太', '真', '好', '坏', '新', '旧', '开', '关', '正', '反', '方', '法', '做', '出',
                                  '入', '处', '理', '程', '序', '员', '人', '物', '件', '事', '些', '种', '样', '点', '道',
                                  '么', '下子', '一下', '那个', '这个', '那个', '哪个', '哪些', '什么', '怎么', '如何',
                                  '为什么', '哪个', '哪些', '怎样', '能否', '是不是', '有没有', '可不可以', '可不', '可以']
            for sw in stopwords_replace:
                clean_text = clean_text.replace(sw, ' ')

            # 按空格拆分，得到单词列表
            words = clean_text.split()
            # 过滤掉单字符和残留停用词
            stopwords_set = set(stopwords_replace)
            filtered = [w.lower() for w in words if len(w) > 1 and w.lower() not in stopwords_set]

            # 同义词合并映射
            synonym_map = {
                '深拷贝': ['deepcopy', 'deep copy', '深度拷贝', '深复制'],
                '浅拷贝': ['shallowcopy', 'shallow copy', '浅度拷贝', '浅复制'],
                '列表推导': ['list comprehension', '列表解析', '列表生成式'],
                '机器学习': ['machine learning', 'ml', '学习机器'],
                '深度学习': ['deep learning', 'dl'],
                '人工智能': ['artificial intelligence', 'ai'],
                '神经网络': ['neural network', 'nn', '神经网络模型'],
                '卷积网络': ['cnn', '卷积神经网络'],
                '循环网络': ['rnn', '循环神经网络'],
                '生成对抗': ['gan', '生成对抗网络'],
                '过拟合': ['overfitting', '过拟合现象'],
                '欠拟合': ['underfitting', '欠拟合现象'],
                '梯度下降': ['gradient descent', '梯度下降法'],
                '损失函数': ['loss function', '代价函数'],
                '激活函数': ['activation function', '激励函数'],
                '正则化': ['regularization', '正规化'],
                '归一化': ['normalization', '规范化'],
                'dropout': ['dropout层', '丢弃法'],
                '反向传播': ['backpropagation', 'bp', '反向传播算法'],
                '前向传播': ['forward propagation', '前馈传播'],
                'batch size': ['batch', '批大小', '批次大小'],
                '学习率': ['learning rate', 'lr'],
                'epoch': ['训练轮次', '迭代周期'],
                'numpy': ['numpy库', 'np'],
                'pandas': ['pandas库', 'pd'],
                'scikit learn': ['sklearn', 'scikit', 'sk-learn'],
                'tensorflow': ['tf', 'tensorflow库'],
                'pytorch': ['torch', 'pytorch库'],
                'python': ['python语言', 'py', 'python程序', 'python编程'],
                '编程': ['编程语言', '编程基础', '编程入门'],
                '矩阵': ['矩阵运算', '矩阵乘法', '矩阵乘法运算'],
                '向量': ['向量运算', '向量计算'],
                '张量': ['tensor', '张量运算'],
                '分类': ['分类问题', '分类器', '分类模型'],
                '回归': ['回归分析', '回归模型', '回归问题'],
                '聚类': ['聚类算法', '聚类分析', '聚类问题'],
                '数据清洗': ['数据预处理', '数据清理', '数据整理'],
                '特征工程': ['特征选择', '特征抽取', '特征提取'],
                '模型评估': ['模型评价', '模型验证', '模型测试'],
            }
            reverse_map = {}
            for standard, synonyms in synonym_map.items():
                reverse_map[standard] = standard
                for syn in synonyms:
                    reverse_map[syn] = standard

            mapped_words = []
            for w in filtered:
                if w in reverse_map:
                    mapped_words.append(reverse_map[w])
                else:
                    mapped_words.append(w)

            counter = Counter(mapped_words)
            result = [(word, count) for word, count in counter.most_common(top_n) if count > 1]

            # 如果结果不足，补上其他高频词
            if len(result) < top_n:
                all_words = [w for w in filtered if len(w) > 1]
                all_counter = Counter(all_words)
                for word, count in all_counter.most_common(top_n):
                    if not any(word == r[0] for r in result):
                        result.append((word, count))
                        if len(result) >= top_n:
                            break
            return result[:top_n]
    except Exception as e:
        st.error(f"获取学生热门词失败：{e}")
        return []
    finally:
        conn.close()

# ---------- 主界面 ----------
if not st.session_state.logged_in:
    st.markdown('<div class="main-title"><h1>🧸 数智伴学 · 碎碎念小助教</h1><p>请登录或注册</p></div>', unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["登录", "注册"])
    with tab1:
        with st.form("login_form"):
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            submit = st.form_submit_button("登录")
            if submit:
                success, result = login_user(username, password)
                if success:
                    st.session_state.logged_in = True
                    st.session_state.user_id = result['id']
                    st.session_state.username = result['username']
                    st.session_state.role = result['role']
                    st.query_params.logged_in = "true"
                    st.query_params.user_id = str(result['id'])
                    st.query_params.username = result['username']
                    st.query_params.role = result['role']
                    st.rerun()
                else:
                    st.error(result)
    with tab2:
        with st.form("register_form"):
            new_username = st.text_input("用户名")
            new_password = st.text_input("密码", type="password")
            confirm_password = st.text_input("确认密码", type="password")
            role = st.selectbox("选择角色", ["student", "parent", "teacher"], format_func=lambda x: {"student":"学生", "parent":"家长", "teacher":"教师"}[x])
            submit_reg = st.form_submit_button("注册")
            if submit_reg:
                if new_password != confirm_password:
                    st.error("两次密码输入不一致")
                elif len(new_password) < 6:
                    st.error("密码长度至少6位")
                else:
                    ok, msg = register_user(new_username, new_password, role)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
else:
    # ---------- 已登录主界面 ----------
    col1, col2, col3 = st.columns([5, 1, 1])
    with col1:
        st.markdown(f'<div style="font-size:1.2rem; font-weight:600;">👋 欢迎，{st.session_state.username} ({ {"student":"学生", "parent":"家长", "teacher":"教师"}[st.session_state.role] })</div>', unsafe_allow_html=True)
    with col3:
        if st.button("🚪 退出登录"):
            st.session_state.logged_in = False
            st.session_state.user_id = None
            st.session_state.username = None
            st.session_state.role = None
            st.query_params.clear()
            st.rerun()

    st.markdown('<div class="main-title"><h1>🧸 数智伴学 · 碎碎念小助教</h1><p style="font-size:0.8rem; color:#5a7a8a;"> </p></div>', unsafe_allow_html=True)

    if st.session_state.role == 'student':
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)
        st.subheader("📚 个性化学习辅导")
        st.caption("🤖 我是你的学习助手，可以帮你解答课程疑问、提供学习建议。")
        recent = get_recent_chat(st.session_state.user_id, 3)
        for msg in recent:
            if msg['role'] == 'user':
                st.markdown(f'<div style="text-align: right;"><span class="user-bubble">{msg["content"]}</span></div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="text-align: left;"><span class="assistant-bubble">{msg["content"]}</span></div>', unsafe_allow_html=True)
        if user_input := st.chat_input("请输入你的学习问题..."):
            st.markdown(f'<div style="text-align: right;"><span class="user-bubble">{user_input}</span></div>', unsafe_allow_html=True)
            save_chat_message(st.session_state.user_id, 'user', user_input)
            with st.spinner("思考中..."):
                system_prompt = "你是一位耐心的大学专业课辅导老师，擅长用通俗易懂的方式解释复杂概念。请根据学生的问题给出清晰、有条理、鼓励性的回答。"
                reply = call_ai(system_prompt, user_input)
            st.markdown(f'<div style="text-align: left;"><span class="assistant-bubble">{reply}</span></div>', unsafe_allow_html=True)
            save_chat_message(st.session_state.user_id, 'assistant', reply)
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("---")
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)
        st.subheader("📁 课件预览")
        coursewares = get_all_courseware()
        if coursewares:
            for cw in coursewares:
                st.write(f"📄 **{cw['file_name']}**  — 由 **{cw['teacher_name']}** 上传于 {cw['upload_time']}")
                ext = cw['file_type']
                if ext in ['pdf', 'txt']:
                    if ext == 'txt':
                        try:
                            content = cw['file_data'].decode('utf-8')
                            with st.expander("预览内容"):
                                st.text(content)
                        except:
                            st.warning("无法预览该文本文件")
                    elif ext == 'pdf':
                        st.download_button(
                            label="下载PDF",
                            data=cw['file_data'],
                            file_name=cw['file_name'],
                            mime='application/pdf',
                            key=f"dl_pdf_{cw['id']}"
                        )
                else:
                    st.download_button(
                        label=f"下载 {cw['file_name']}",
                        data=cw['file_data'],
                        file_name=cw['file_name'],
                        mime='application/octet-stream',
                        key=f"dl_{cw['id']}"
                    )
                st.write("---")
        else:
            st.info("暂无课件")
        st.markdown('</div>', unsafe_allow_html=True)

    elif st.session_state.role == 'parent':
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)
        st.subheader("❤️ 心理疏导与亲子沟通")
        st.caption("🤖 我是家庭教育助手，可以帮你分析孩子心理状态，提供沟通建议。")
        recent = get_recent_chat(st.session_state.user_id, 3)
        for msg in recent:
            if msg['role'] == 'user':
                st.markdown(f'<div style="text-align: right;"><span class="user-bubble">{msg["content"]}</span></div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="text-align: left;"><span class="assistant-bubble">{msg["content"]}</span></div>', unsafe_allow_html=True)
        if user_input := st.chat_input("描述孩子的情况或你的困惑..."):
            st.markdown(f'<div style="text-align: right;"><span class="user-bubble">{user_input}</span></div>', unsafe_allow_html=True)
            save_chat_message(st.session_state.user_id, 'user', user_input)
            with st.spinner("思考中..."):
                system_prompt = "你是一位经验丰富的青少年心理咨询师和家庭教育专家，以温暖、专业、实用的风格提供心理疏导和亲子沟通建议。"
                reply = call_ai(system_prompt, user_input)
            st.markdown(f'<div style="text-align: left;"><span class="assistant-bubble">{reply}</span></div>', unsafe_allow_html=True)
            save_chat_message(st.session_state.user_id, 'assistant', reply)
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    else:  # teacher
        teacher_mode = st.radio(
            "选择功能",
            ["📝 教研辅助", "📊 学情看板"],
            horizontal=True,
            key="teacher_mode"
        )

        if teacher_mode == "📝 教研辅助":
            st.markdown('<div class="custom-card">', unsafe_allow_html=True)
            st.subheader("📝 AI 教研辅助")
            st.caption("🤖 我是教学助手，可以帮助你生成教案、设计习题、提供教学建议。")
            task = st.selectbox("选择教研任务", ["生成教案", "设计课堂习题", "教学建议与策略"])
            user_input = st.text_area("请输入主题或具体要求", placeholder="例如：面向大一学生的《人工智能导论》第3章教案")
            if st.button("🚀 生成内容", use_container_width=True):
                if user_input.strip():
                    with st.spinner("生成中..."):
                        if task == "生成教案":
                            system_prompt = "你是一位资深高校教师，请根据主题生成一份结构清晰、包含教学目标、重难点、教学过程、课后作业的教案。"
                        elif task == "设计课堂习题":
                            system_prompt = "你是一位资深高校教师，请根据主题设计5-8道课堂习题，包括选择题、简答题和讨论题，并附参考答案。"
                        else:
                            system_prompt = "你是一位资深高校教师，请针对该主题提供教学策略、课堂活动建议和常见学生误区分析。"
                        reply = call_ai(system_prompt, user_input)
                        st.success("✅ 生成完成")
                        st.markdown(reply)
                else:
                    st.warning("请输入主题或具体要求")
            st.markdown('</div>', unsafe_allow_html=True)

            st.markdown("---")
            st.markdown('<div class="custom-card">', unsafe_allow_html=True)
            st.subheader("📤 上传课件（供学生预览）")
            if 'upload_key' not in st.session_state:
                st.session_state.upload_key = str(random.randint(0, 1000000))
            uploaded_file = st.file_uploader(
                "选择文件（支持 PDF, TXT, PPT, PPTX, DOC, DOCX）",
                type=["pdf", "txt", "ppt", "pptx", "doc", "docx"],
                key=st.session_state.upload_key
            )
            if uploaded_file is not None:
                file_data = uploaded_file.read()
                if st.button("确认上传"):
                    success = upload_courseware(
                        st.session_state.user_id,
                        uploaded_file.name,
                        uploaded_file.type,
                        file_data
                    )
                    if success:
                        st.success("课件上传成功！")
                        st.session_state.upload_key = str(random.randint(0, 1000000))
                        st.rerun()
                    else:
                        st.error("上传失败")
            st.markdown('</div>', unsafe_allow_html=True)

            st.markdown('<div class="custom-card">', unsafe_allow_html=True)
            st.subheader("📋 我上传的课件")
            teacher_cw = get_teacher_courseware(st.session_state.user_id)
            if teacher_cw:
                for cw in teacher_cw:
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.write(f"📄 {cw['file_name']} (上传于 {cw['upload_time']})")
                    with col2:
                        if st.button("❌ 删除", key=f"del_{cw['id']}"):
                            ok, msg = delete_courseware(cw['id'], st.session_state.user_id)
                            if ok:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
            else:
                st.info("您还没有上传任何课件。")
            st.markdown('</div>', unsafe_allow_html=True)

        else:  # 学情看板
            st.markdown('<div class="custom-card">', unsafe_allow_html=True)
            st.subheader("📊 碎碎念 · 学情看板")
            st.caption("📌 数据实时更新，展示智能体的使用情况")

            today_chat, total_ppt, total_users, trend_data = get_dashboard_stats()

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(label="👥 注册总人数", value=total_users)
            with col2:
                st.metric(label="📚 累计课件数", value=total_ppt)
            with col3:
                st.metric(label="💬 今日提问数", value=today_chat)

            st.divider()
            st.subheader("📈 近7天提问趋势")
            if trend_data and len(trend_data) > 0:
                df = pd.DataFrame(trend_data)
                df['date'] = pd.to_datetime(df['date']).dt.date
                all_dates = pd.date_range(end=pd.Timestamp.today(), periods=7).date
                df_full = pd.DataFrame({'date': all_dates})
                df = df_full.merge(df, on='date', how='left').fillna(0)
                df['count'] = df['count'].astype(int)
                st.bar_chart(df.set_index('date'), height=250)
            else:
                st.info("暂无提问数据，快去提问吧！")

            st.divider()
            st.subheader("🔥 学生热门提问词")
            hot_words = get_student_hot_keywords(10)
            if hot_words:
                cols = st.columns(min(len(hot_words), 5))
                for idx, (word, count) in enumerate(hot_words):
                    with cols[idx % 5]:
                        st.markdown(
                            f"<span style='background:#e6f0f5; padding:4px 12px; border-radius:20px; display:inline-block; margin:2px;'>{word} <small>({count})</small></span>",
                            unsafe_allow_html=True
                        )
            else:
                st.info("暂无学生提问数据，无法生成热门词。")

            st.divider()
            st.caption("💡 小提示：数据每5分钟自动更新，真实反映教学互动情况。")
            st.markdown('</div>', unsafe_allow_html=True)
