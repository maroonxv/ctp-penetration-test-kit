import os
import sys
import logging

# Ensure project root is in sys.path when running as script
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from src.manager import TestManager
from src.socket_handler import SocketIOHandler
from src.tests import cases
from src import config

# 1. 初始化 Flask 与 SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'ctp_test_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 2. 初始化核心管理器
manager = TestManager()
manager.initialize()

# 3. 挂载日志处理器 (关键步骤)
root_logger = logging.getLogger()
# 避免重复挂载
if not any(isinstance(h, SocketIOHandler) for h in root_logger.handlers):
    socket_handler = SocketIOHandler(socketio)
    socket_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
    
    # 挂载到 Root Logger (捕获 src.*)
    root_logger.addHandler(socket_handler)
    
    # 显式挂载到 vnpy 相关的 Logger (捕获底层日志)
    # vnpy 可能使用 'vnpy', 'vnpy.trader', 'vnpy.gateway' 等
    # 我们遍历所有已存在的 logger 并尝试挂载
    for name in logging.root.manager.loggerDict:
        if name.startswith("vnpy"):
            l = logging.getLogger(name)
            l.addHandler(socket_handler)
            l.setLevel(logging.INFO)
            
    # 额外确保 "vnpy" 和 "vnpy.trader" 被挂载（即使它们还没创建，现在创建并挂载）
    logging.getLogger("vnpy").addHandler(socket_handler)
    logging.getLogger("vnpy.trader").addHandler(socket_handler)
    
    # --- 方案: Loguru 拦截 (针对 vnpy 的 loguru 日志) ---
    try:
        from loguru import logger as loguru_logger
        
        def loguru_sink(message):
            try:
                # Loguru message is a string-like object
                msg_str = str(message).strip()
                if not msg_str: return
                
                # 过滤 Werkzeug/Flask 访问日志
                if "GET /" in msg_str or "POST /" in msg_str or "HTTP/1.1" in msg_str or "socket.io" in msg_str:
                    return
                
                color = "#cccccc"
                if "ERROR" in msg_str or "Error" in msg_str:
                    color = "#ff4d4d"
                elif "WARNING" in msg_str or "Warning" in msg_str:
                    color = "#ffbf00"
                elif "INFO" in msg_str:
                    color = "#00ccff"
                    
                socketio.emit('new_log', {'message': msg_str, 'color': color})
            except:
                pass
                
        # 添加 sink
        loguru_logger.add(loguru_sink, format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name} | {message}")
    except ImportError:
        pass
    
    # --- 方案 A: 劫持 Stdout/Stderr (最强兜底) ---
    class StreamToSocket:
        def __init__(self, original_stream):
            self.original_stream = original_stream
            
        def write(self, message):
            # 保留原始输出
            self.original_stream.write(message)
            self.original_stream.flush()
            
            # 过滤空行
            if not message.strip():
                return
                
            # 过滤 Werkzeug/Flask 访问日志
            msg_str = message.strip()
            if "GET /" in msg_str or "POST /" in msg_str or "HTTP/1.1" in msg_str or "socket.io" in msg_str:
                return
                
            # 推送到前端
            try:
                # 简单区分颜色：如果包含 Error/失败 -> 红，其他 -> 默认
                color = "#cccccc"
                if "Error" in message or "失败" in message or "Exception" in message:
                    color = "#ff4d4d"
                elif "Warning" in message or "警告" in message:
                    color = "#ffbf00"
                elif "INFO" in message and "|" in message: # 识别 loguru/vnpy 格式
                    color = "#00ccff"
                    
                socketio.emit('new_log', {'message': message.strip(), 'color': color})
            except:
                pass
                
        def flush(self):
            self.original_stream.flush()
            
    # 启用劫持
    sys.stdout = StreamToSocket(sys.stdout)
    sys.stderr = StreamToSocket(sys.stderr) # 同时也劫持 stderr，因为 loguru 默认输出到 stderr
    
    # 防止 vnpy 日志双重打印 (如果它已经有 StreamHandler)
    # 但我们需要确保它至少有一个 Handler 才能工作，这里只加我们的

# --- 辅助函数：脱敏 ---
def get_masked_env():
    """读取并脱敏配置"""
    username = config.CTP_USERNAME or "N/A"
    masked_user = username
    if len(username) > 4:
        masked_user = username[:2] + "****" + username[-2:]
        
    return {
        "BROKER": config.CTP_BROKER_ID,
        "SERVER": config.CTP_TD_SERVER,
        "USER": masked_user,
        "APPID": config.CTP_APP_ID
    }

# --- 路由定义 ---

@app.route('/')
def index():
    return render_template('index.html', env=get_masked_env())

@app.route('/api/run/<case_id>', methods=['POST'])
def run_case(case_id):
    """
    统一的测试执行接口
    映射 case_id 到 cases.py 中的函数
    """
    case_map = {
        # 2.1 基础
        '2.1.1': cases.test_2_1_1_connectivity,
        '2.1.2': cases.test_2_1_2_basic_trading,
        
        # 2.2 异常
        '2.2.1': cases.test_2_2_1_connection_monitor,
        '2.2.2': cases.test_2_2_2_count_monitor,
        '2.2.3': cases.test_2_2_3_repeat_monitor,
        
        # 2.3 阈值
        '2.3.1': cases.test_2_3_1_threshold_alert,
        
        # 2.4 错误
        '2.4.1': cases.test_2_4_1_order_check,
        '2.4.2': cases.test_2_4_2_error_prompt,
        
        # 2.5 应急
        '2.5.1': cases.test_2_5_1_pause_trading,
        '2.5.2': cases.test_2_5_2_batch_cancel,
        
        # 2.6 日志
        '2.6.1': cases.test_2_6_1_log_record
    }
    
    func = case_map.get(case_id)
    if not func:
        return jsonify({"status": "error", "msg": f"未找到测试项 {case_id}"}), 404
        
    success, msg = manager.run_task(func)
    return jsonify({"status": "success" if success else "busy", "msg": msg})

@app.route('/api/control/reset', methods=['POST'])
def reset_system():
    manager.reset_risk_manager()
    return jsonify({"status": "success", "msg": "系统状态已重置"})

if __name__ == '__main__':
    # 允许 host='0.0.0.0' 以便局域网访问
    socketio.run(app, host='0.0.0.0', port=5006, debug=False)
