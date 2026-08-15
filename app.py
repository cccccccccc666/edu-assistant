import streamlit as st
from openai import OpenAI
import os
from dotenv import load_dotenv
from pypdf import PdfReader
import io
import pymysql
import bcrypt
import datetime

# ---------- 加载环境变量 ----------
load_dotenv()

# ---------- 数据库连接函数 ----------
def get_db_connection():
    return pymysql.connect(
        host=os.st.secrets["DB_HOST"],
        port=int(os.st.secrets["DB_PORT", 3306]),
        user=os.st.secrets["DB_USER"],
        password=os.st.secrets["DB_PASSWORD"],
        database=os.st.secrets["DB_NAME"],
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

# ---------- 初始化OpenAI客户端 ----------
client = OpenAI(
    api_key=os.st.secrets["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com"
)

# ---------- 公共的AI调用函数（提前定义，放在最前面） ----------
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
st.set_page_config(page_title="数智伴学 · 教育助教", page_icon="🧑‍🏫")

# ---------- 自定义CSS ----------
st.markdown("""
<style>
    .stApp { background: linear-gradient(145deg, #f6f9fc 0%, #e6f0f5 100%); }
    .main-title {
        text-align: center;
        padding: 0.8rem 1rem;
        background: rgba(255,255,255,0.7);
        backdrop-filter: blur(6px);
        border-radius: 30px;
        margin-bottom: 1.5rem;
        box-shadow: 0 6px 20px rgba(0,0,0,0.05);
        border: 1px solid rgba(255,255,255,0.6);
    }
    .main-title h1 { color: #1e3c5c; font-weight: 700; }
    .main-title p { color: #3a6a8a; font-size: 0.95rem; }
    .custom-card {
        background: rgba(255,255,255,0.85);
        backdrop-filter: blur(10px);
        border-radius: 28px;
        padding: 1.8rem;
        box-shadow: 0 12px 40px rgba(0,0,0,0.08);
        border: 1px solid rgba(255,255,255,0.4);
        margin-bottom: 1.5rem;
    }
    .stButton>button {
        border-radius: 40px !important;
        background: linear-gradient(135deg, #4f8bc9 0%, #2b5b8c 100%) !important;
        color: white !important;
        font-weight: 600 !important;
        border: none !important;
        padding: 0.6rem 2rem !important;
        box-shadow: 0 4px 14px rgba(47, 128, 237, 0.3) !important;
        transition: 0.3s !important;
    }
    .stButton>button:hover { transform: scale(1.02) !important; }
    .user-bubble {
        background: #4f8bc9;
        color: white;
        border-radius: 22px 22px 6px 22px;
        padding: 12px 20px;
        margin: 8px 0;
        display: inline-block;
        max-width: 80%;
        box-shadow: 0 2px 6px rgba(0,0,0,0.1);
    }
    .assistant-bubble {
        background: white;
        color: #1e293b;
        border-radius: 22px 22px 22px 6px;
        padding: 12px 20px;
        margin: 8px 0;
        display: inline-block;
        max-width: 80%;
        box-shadow: 0 2px 10px rgba(0,0,0,0.04);
    }
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

# ---------- 辅助函数：保存聊天记录 ----------
def save_chat_message(user_id, role, content):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_history (user_id, role, content) VALUES (%s, %s, %s)",
                (user_id, role, content)
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
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO courseware (teacher_id, file_name, file_type, file_data) VALUES (%s, %s, %s, %s)",
                (teacher_id, file_name, file_type, file_data)
            )
            conn.commit()
            return True
    except Exception as e:
        st.error(f"上传课件失败：{e}")
        return False
    finally:
        conn.close()

# ---------- 辅助函数：获取所有课件（学生预览） ----------
def get_all_courseware():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, file_name, file_type, file_data, upload_time FROM courseware ORDER BY upload_time DESC")
            return cur.fetchall()
    except Exception as e:
        st.error(f"读取课件失败：{e}")
        return []
    finally:
        conn.close()

# ---------- 主界面 ----------
if not st.session_state.logged_in:
    # ---------- 登录/注册界面 ----------
    st.markdown('<div class="main-title"><h1>🧑‍🏫 数智伴学 · 教育助教</h1><p>请登录或注册</p></div>', unsafe_allow_html=True)
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
    # 右上角退出按钮
    col1, col2, col3 = st.columns([5, 1, 1])
    with col1:
        st.markdown(f'<div style="font-size:1.2rem; font-weight:600;">👋 欢迎，{st.session_state.username} ({ {"student":"学生", "parent":"家长", "teacher":"教师"}[st.session_state.role] })</div>', unsafe_allow_html=True)
    with col3:
        if st.button("🚪 退出登录"):
            st.session_state.logged_in = False
            st.session_state.user_id = None
            st.session_state.username = None
            st.session_state.role = None
            st.rerun()

    # 标题
    st.markdown('<div class="main-title"><h1>🧑‍🏫 数智伴学 · 教育助教</h1><p style="font-size:0.8rem; color:#5a7a8a;">✨ </p></div>', unsafe_allow_html=True)

    # ---------- 根据角色显示功能模块 ----------
    if st.session_state.role == 'student':
        # 学生：只显示答疑助手 + 课件预览（无上传）
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)
        st.subheader("📚 个性化学习辅导")
        st.caption("🤖 我是你的学习助手，可以帮你解答课程疑问、提供学习建议。")
        # 显示最近3条聊天记录
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

        # 学生预览课件（只读）
        st.markdown("---")
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)
        st.subheader("📁 课件预览")
        coursewares = get_all_courseware()
        if coursewares:
            for cw in coursewares:
                st.write(f"📄 {cw['file_name']} (上传时间: {cw['upload_time']})")
                if cw['file_type'] == 'text/plain':
                    content = cw['file_data'].decode('utf-8')
                    with st.expander("预览内容"):
                        st.text(content)
                elif cw['file_type'] == 'application/pdf':
                    st.download_button(
                        label="下载PDF",
                        data=cw['file_data'],
                        file_name=cw['file_name'],
                        mime='application/pdf'
                    )
        else:
            st.info("暂无课件")
        st.markdown('</div>', unsafe_allow_html=True)

    elif st.session_state.role == 'parent':
        # 家长：只显示心理疏导（无课件）
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
        # 教师：显示教研辅助 + 课件上传
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

        # 课件上传（教师专属）
        st.markdown("---")
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)
        st.subheader("📤 上传课件（供学生预览）")
        uploaded_file = st.file_uploader("选择文件（支持 TXT / PDF）", type=["txt", "pdf"])
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
                else:
                    st.error("上传失败")
        st.markdown('</div>', unsafe_allow_html=True)