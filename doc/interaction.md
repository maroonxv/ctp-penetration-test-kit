# CTP 穿透式测试可视化交互方案 (Streamlit)

本方案旨在为 CTP 穿透式测试提供一个轻量级、非侵入式的可视化交互界面。通过 Streamlit 构建 Web UI，用户可以直观地监控测试进度、实时查看日志，并通过按钮触发断线、暂停交易等人工干预场景，而无需直接操作命令行或修改核心代码。

## 1. 方案架构

该方案采用 **"UI + Core"** 分离的设计模式：

1.  **控制中心 (Streamlit UI)**: 
    *   作为主控台，负责启动和管理底层的测试进程 (`src/main.py`)。
    *   读取 `.env` 配置文件并展示。
    *   通过读取磁盘上的日志文件实现运行状态的可视化反馈。

2.  **指令系统 (RPC Client)**: 
    *   Streamlit 应用充当 RPC 客户端。
    *   通过 TCP Socket 连接到测试引擎内置的 RPC 服务端 (默认端口 9999)。
    *   发送 `DISCONNECT`, `RECONNECT`, `PAUSE` 等指令，替代原有的 `scripts/control.py` 脚本。

3.  **核心引擎 (Test Engine)**:
    *   保持原有的业务逻辑不变，继续负责 CTP 接口交互和风控逻辑。

## 2. 实施步骤

### 2.1 安装依赖

在项目的虚拟环境 (`.venv`) 中安装 `streamlit`：

```bash
pip install streamlit
```

### 2.2 创建启动脚本

在项目根目录 (`C:\Users\Administrator\Lai\penetration_test\`) 下创建文件 `streamlit_app.py`，内容如下：

```python
import streamlit as st
import subprocess
import sys
import os
import time
import socket
import glob
from datetime import datetime

# --- 1. 基础配置与工具函数 ---

def load_env(env_path=".env"):
    """简易加载 .env 文件"""
    config = {}
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    config[key.strip()] = val.strip()
    return config

def send_rpc_command(cmd, port=9999):
    """发送 RPC 指令到测试引擎"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(('127.0.0.1', port))
            s.sendall(cmd.encode('utf-8'))
            response = s.recv(1024)
            return True, response.decode('utf-8')
    except Exception as e:
        return False, str(e)

def get_latest_log_file(ctp_name):
    """获取最新的日志文件路径"""
    log_dir = os.path.join("log", ctp_name)
    if not os.path.exists(log_dir):
        return None
    # 查找所有 .log 文件
    files = glob.glob(os.path.join(log_dir, "*.log"))
    if not files:
        return None
    # 按修改时间排序，最新的在最后
    latest_file = max(files, key=os.path.getmtime)
    return latest_file

def tail_log(file_path, lines=50):
    """读取日志文件末尾 N 行"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.readlines()
            return "".join(content[-lines:])
    except Exception:
        return "等待日志生成..."

# --- 2. 页面布局与逻辑 ---

st.set_page_config(
    page_title="CTP 穿透测试控制台",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# === Dark Glassmorphism CSS ===
st.markdown("""
<style>
    /* 全局背景：深色渐变 */
    .stApp {
        background-image: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
        background-attachment: fixed;
    }
    
    /* 侧边栏：磨砂玻璃 */
    [data-testid="stSidebar"] {
        background-color: rgba(0, 0, 0, 0.2);
        backdrop-filter: blur(15px);
        border-right: 1px solid rgba(255, 255, 255, 0.1);
    }
    
    /* 卡片/容器样式 */
    .stCard {
        background-color: rgba(255, 255, 255, 0.05);
        border-radius: 15px;
        padding: 20px;
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        margin-bottom: 20px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }

    /* 按钮：玻璃态 */
    .stButton > button {
        background: rgba(255, 255, 255, 0.1);
        border: 1px solid rgba(255, 255, 255, 0.2);
        color: white;
        border-radius: 10px;
        backdrop-filter: blur(5px);
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        background: rgba(255, 255, 255, 0.25);
        border-color: rgba(255, 255, 255, 0.5);
        transform: translateY(-2px);
        box-shadow: 0 0 15px rgba(255,255,255,0.2);
    }

    /* 文本框：深色磨砂 */
    .stTextArea textarea {
        background-color: rgba(0, 0, 0, 0.4) !important;
        color: #00ff00 !important; /* 极客绿文字 */
        border: 1px solid rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(5px);
        border-radius: 10px;
        font-family: 'Consolas', 'Courier New', monospace;
    }

    /* 文字颜色修正 */
    h1, h2, h3, p, label {
        color: #e0e0e0 !important;
        text-shadow: 0 2px 4px rgba(0,0,0,0.5);
    }
    
    /* 代码块背景 */
    code {
        background-color: rgba(0, 0, 0, 0.3) !important;
        color: #ffca28 !important;
    }
</style>
""", unsafe_allow_html=True)


# 初始化 Session State
if 'process' not in st.session_state:
    st.session_state.process = None
if 'test_running' not in st.session_state:
    st.session_state.test_running = False

# 加载配置
env_config = load_env()
ctp_name = env_config.get("CTP_NAME", "Unknown")

# === 侧边栏：配置与状态 ===
with st.sidebar:
    st.markdown("## 🛡️ 控制面板")
    
    st.markdown(f"""
    <div style='background:rgba(255,255,255,0.1);padding:10px;border-radius:10px;border:1px solid rgba(255,255,255,0.1)'>
        <strong>当前期货公司:</strong> <br>
        <span style='font-size:1.2em;color:#4fc3f7'>{ctp_name}</span>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("### 📋 环境配置 (.env)")
    st.code(f"""
User: {env_config.get('CTP_USERNAME', 'N/A')}
Broker: {env_config.get('CTP_BROKER_ID', 'N/A')}
Server: {env_config.get('CTP_TD_SERVER', 'N/A')}
    """, language="yaml")

    st.markdown("---")
    if st.session_state.test_running:
        st.markdown("### 系统状态: 🟢 <span style='color:#69f0ae'>正在运行</span>", unsafe_allow_html=True)
    else:
        st.markdown("### 系统状态: ⚫ <span style='color:#b0bec5'>未启动</span>", unsafe_allow_html=True)

# === 主区域 ===
st.markdown("# CTP 穿透式测试执行系统")

col1, col2 = st.columns([1, 2])

with col1:
    st.markdown('<div class="stCard">', unsafe_allow_html=True)
    st.subheader("⚙️ 操作控制")
    
    # 启动/停止 测试进程
    if not st.session_state.test_running:
        if st.button("🚀 启动自动化测试", type="primary", use_container_width=True):
            env = os.environ.copy()
            env["PYTHONPATH"] = os.getcwd()
            try:
                p = subprocess.Popen(
                    [sys.executable, "src/main.py"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                )
                st.session_state.process = p
                st.session_state.test_running = True
                st.rerun()
            except Exception as e:
                st.error(f"启动失败: {e}")
    else:
        if st.button("🛑 强制停止测试", type="secondary", use_container_width=True):
            if st.session_state.process:
                st.session_state.process.terminate()
                st.session_state.process = None
            st.session_state.test_running = False
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="stCard">', unsafe_allow_html=True)
    st.markdown("### 🎮 人工干预 (RPC)")
    st.caption("模拟异常场景")
    
    disabled = not st.session_state.test_running
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔌 断网", disabled=disabled, use_container_width=True):
            success, msg = send_rpc_command("DISCONNECT")
            if success: st.success("已断线")
            else: st.error(msg)
            
    with c2:
        if st.button("🔗 重连", disabled=disabled, use_container_width=True):
            success, msg = send_rpc_command("RECONNECT")
            if success: st.success("已重连")
            else: st.error(msg)

    if st.button("⏸️ 暂停交易 (应急)", disabled=disabled, use_container_width=True):
        success, msg = send_rpc_command("PAUSE")
        if success: st.warning("已暂停")
        else: st.error(msg)
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="stCard">', unsafe_allow_html=True)
    st.subheader("📝 实时日志监控")
    
    # 自动刷新
    if st.session_state.test_running:
        time.sleep(1)
        st.rerun()
        
    log_file = get_latest_log_file(ctp_name)
    
    if log_file:
        log_content = tail_log(log_file, lines=30)
        st.text_area("Terminal Output", value=log_content, height=500, disabled=True)
        st.caption(f"File: {log_file}")
    else:
        st.info("等待日志文件生成...")
    st.markdown('</div>', unsafe_allow_html=True)

# 进程监控
if st.session_state.test_running and st.session_state.process:
    if st.session_state.process.poll() is not None:
        st.session_state.test_running = False
        st.rerun()
```

### 2.3 启动与使用

1.  **运行**: 在终端中执行以下命令：
    ```bash
    streamlit run streamlit_app.py
    ```

2.  **新版界面特点**: 
    *   **Dark Glassmorphism**: 采用深色渐变背景 (#0f2027 -> #2c5364)，搭配半透明磨砂玻璃卡片。
    *   **极客风格日志**: 日志区域模拟绿色荧光屏终端显示，字体使用 Consolas/Courier New。
    *   **交互动效**: 按钮增加了悬停发光和上浮效果。

```