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
import signal

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
            # 简单读取所有行然后取最后 N 行 (对于小日志文件足够高效)
            content = f.readlines()
            return "".join(content[-lines:])
    except Exception:
        return "等待日志生成..."

# --- 2. 页面布局与逻辑 ---

st.set_page_config(
    page_title="CTP 穿透测试控制台",
    page_icon="🛡️",
    layout="wide"
)

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
    st.title("🛡️ 控制面板")
    
    st.info(f"当前期货公司: **{ctp_name}**")
    
    st.subheader("环境配置 (.env)")
    st.code(f"""
User: {env_config.get('CTP_USERNAME', 'N/A')}
Broker: {env_config.get('CTP_BROKER_ID', 'N/A')}
Server: {env_config.get('CTP_TD_SERVER', 'N/A')}
    """, language="yaml")

    st.markdown("---")
    status_color = "green" if st.session_state.test_running else "gray"
    status_text = "🟢 正在运行" if st.session_state.test_running else "⚫ 未启动"
    st.markdown(f"### 系统状态: {status_text}")

# === 主区域 ===
st.title("CTP 穿透式测试执行系统")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("⚙️ 操作控制")
    
    # 启动/停止 测试进程
    if not st.session_state.test_running:
        if st.button("🚀 启动自动化测试", type="primary", use_container_width=True):
            # 准备环境变量
            env = os.environ.copy()
            env["PYTHONPATH"] = os.getcwd()  # 确保能导入 src
            
            # 启动子进程
            try:
                # 使用 sys.executable 确保使用当前的 python 解释器 (即 .venv 中的)
                p = subprocess.Popen(
                    [sys.executable, "src/main.py"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NEW_CONSOLE # Windows下弹出一个新窗口显示原始日志，避免阻塞
                )
                st.session_state.process = p
                st.session_state.test_running = True
                st.toast("测试进程已启动！")
                st.rerun()
            except Exception as e:
                st.error(f"启动失败: {e}")
    else:
        if st.button("🛑 强制停止测试", type="secondary", use_container_width=True):
            if st.session_state.process:
                st.session_state.process.terminate()
                st.session_state.process = None
            st.session_state.test_running = False
            st.toast("测试进程已终止")
            st.rerun()

    st.markdown("### 🎮 人工干预 (RPC)")
    st.caption("点击下方按钮模拟异常场景（需在测试运行中操作）")
    
    disabled = not st.session_state.test_running
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔌 断开网线 (Disconnect)", disabled=disabled, use_container_width=True):
            success, msg = send_rpc_command("DISCONNECT")
            if success: st.success("已发送断线指令")
            else: st.error(f"指令发送失败: {msg}")
            
    with c2:
        if st.button("🔗 恢复连接 (Reconnect)", disabled=disabled, use_container_width=True):
            success, msg = send_rpc_command("RECONNECT")
            if success: st.success("已发送重连指令")
            else: st.error(f"指令发送失败: {msg}")

    if st.button("⏸️ 暂停交易 (Pause/Emergency)", disabled=disabled, use_container_width=True):
        success, msg = send_rpc_command("PAUSE")
        if success: st.warning("已触发应急暂停（停止风控）")
        else: st.error(f"指令发送失败: {msg}")

with col2:
    st.subheader("📝 实时日志监控")
    
    # 自动刷新机制
    if st.session_state.test_running:
        st.caption("自动刷新中...")
        time.sleep(1) # 简单的轮询间隔
        st.rerun()
        
    log_file = get_latest_log_file(ctp_name)
    
    if log_file:
        log_content = tail_log(log_file, lines=30)
        st.text_area("最新日志内容", value=log_content, height=500, disabled=True)
        st.caption(f"读取文件: {log_file}")
    else:
        st.warning("暂未找到日志文件，请先启动测试。")

# 检查进程是否意外结束
if st.session_state.test_running and st.session_state.process:
    if st.session_state.process.poll() is not None:
        st.session_state.test_running = False
        st.warning("测试进程已退出。")
        st.rerun()
```

### 2.3 启动与使用

1.  **运行**: 在终端中执行以下命令：
    ```bash
    streamlit run streamlit_app.py
    ```

2.  **功能说明**:
    *   **启动自动化测试**: 点击后会弹出一个新的命令行窗口运行测试核心，Web 界面同步显示“正在运行”。
    *   **实时日志**: 右侧区域会自动滚动显示 `log/` 目录下最新的日志文件内容，方便查看测试进度和报错。
    *   **人工干预**:
        *   `断开网线`: 模拟客户端网络断开。
        *   `恢复连接`: 模拟网络恢复重连。
        *   `暂停交易`: 模拟触发风控紧急停止，系统将拒绝后续报单。

## 3. 优势

*   **安全隔离**: UI 层与核心逻辑层通过 RPC 解耦，Web 界面的操作不会影响底层交易逻辑的即时性。
*   **非侵入式**: 无需修改 `src/` 下任何现有代码即可集成。
*   **Windows 兼容**: 针对 Windows 环境特别优化了子进程启动方式 (`CREATE_NEW_CONSOLE`)，避免日志阻塞。
