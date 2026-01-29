import os
import sys
import logging
import socket
import json
import uuid
import time
import subprocess

# 确保项目根目录在 sys.path 中（当作为脚本运行时）
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from flask_socketio import SocketIO
from src.socket_handler import SocketIOHandler
from src import read_config as config
from src.logger import setup_logger
import engineio

# Increase max_decode_packets to prevent "Too many packets in payload" error
engineio.payload.Payload.max_decode_packets = 100

app = Flask(__name__)
# Generate a random key on startup to invalidate previous sessions
app.config['SECRET_KEY'] = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

setup_logger()

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORKER_ENTRY = os.path.join(PROJECT_ROOT, "src", "worker.py")


class ProcessManager:
    def __init__(self):
        self.process = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start_worker(self) -> bool:
        if self.is_running():
            return True

        env = os.environ.copy()
        env.setdefault("PYTHONPATH", PROJECT_ROOT)

        self.process = subprocess.Popen(
            [sys.executable, WORKER_ENTRY],
            cwd=PROJECT_ROOT,
            env=env,
        )
        return True

    def kill_worker(self) -> bool:
        if not self.process:
            return True
        try:
            self.process.kill()
        except Exception:
            pass
        return True

    def restart_worker(self) -> bool:
        self.kill_worker()
        time.sleep(0.2)
        return self.start_worker()


class RpcClient:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def request(self, req_type: str, payload: dict | None = None, timeout: float = 5.0) -> dict:
        req = {
            "request_id": str(uuid.uuid4()),
            "type": req_type,
            "payload": payload or {},
            "timeout_ms": int(timeout * 1000),
        }

        data = (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8")

        with socket.create_connection((self.host, self.port), timeout=timeout) as s:
            s.sendall(data)
            s.shutdown(socket.SHUT_WR)

            raw = b""
            s.settimeout(timeout)
            while b"\n" not in raw and len(raw) < 65536:
                chunk = s.recv(4096)
                if not chunk:
                    break
                raw += chunk

        line = raw.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()
        if not line:
            return {"ok": False, "error": "empty_response"}
        try:
            return json.loads(line)
        except Exception:
            return {"ok": False, "error": "invalid_response", "raw": line}


process_manager = ProcessManager()
rpc = RpcClient("127.0.0.1", 9999)

log = logging.getLogger(__name__)

root_logger = logging.getLogger()
if not any(isinstance(h, SocketIOHandler) for h in root_logger.handlers):
    socket_handler = SocketIOHandler(socketio)
    socket_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
    root_logger.addHandler(socket_handler)


@socketio.on("new_log")
def _relay_new_log(data):
    socketio.emit("new_log", data)


@socketio.on("worker_status")
def _relay_worker_status(data):
    socketio.emit("worker_status", data)


@socketio.on("case_started")
def _relay_case_started(data):
    socketio.emit("case_started", data)


@socketio.on("case_finished")
def _relay_case_finished(data):
    socketio.emit("case_finished", data)


def get_masked_env():
    """读取配置 (按需脱敏)"""
    # 每次读取最新配置
    env_vars = config.load_env(config.ENV_PATH)
    return {
        "CTP_NAME": env_vars.get("CTP_NAME", "Unknown"),
        "CTP_USERNAME": env_vars.get("CTP_USERNAME", ""),
        "CTP_TD_SERVER": env_vars.get("CTP_TD_SERVER", ""),
        "CTP_MD_SERVER": env_vars.get("CTP_MD_SERVER", "")
    }


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Get data from form
        data = {
            'CTP_NAME': request.form.get('CTP_NAME'),
            'CTP_USERNAME': request.form.get('CTP_USERNAME'),
            'CTP_PASSWORD': request.form.get('CTP_PASSWORD'),
            'CTP_BROKER_ID': request.form.get('CTP_BROKER_ID'),
            'CTP_TD_SERVER': request.form.get('CTP_TD_SERVER'),
            'CTP_MD_SERVER': request.form.get('CTP_MD_SERVER'),
            'APPID': request.form.get('APPID'),
            'CTP_AUTH_CODE': request.form.get('CTP_AUTH_CODE'),
            'CTP_PRODUCT_INFO': request.form.get('CTP_PRODUCT_INFO', '')
        }
        
        # Save to .env
        config.save_env(config.ENV_PATH, data)
        
        # Set session
        session['logged_in'] = True
        
        # Restart worker to pick up new config
        if process_manager.is_running():
            process_manager.restart_worker()
        else:
            process_manager.start_worker()
            
        return redirect(url_for('index'))
        
    # GET
    env_vars = config.load_env(config.ENV_PATH)
    return render_template('login.html', env=env_vars)


@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('index.html', env=get_masked_env())

def _now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

def _wait_ping_ok(timeout_s: float) -> bool:
    deadline = time.time() + max(0.1, float(timeout_s))
    while time.time() < deadline:
        try:
            resp = rpc.request("PING", {}, timeout=1.0)
            if resp.get("ok"):
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False

def _hard_disconnect_orchestrate(case_id: str) -> tuple[bool, dict]:
    disconnect_window_s = float(os.environ.get("HARD_DISCONNECT_WINDOW_S", "10"))
    restart_ping_timeout_s = float(os.environ.get("HARD_DISCONNECT_RESTART_PING_TIMEOUT_S", "60"))
    ping_timeout_s = float(os.environ.get("HARD_DISCONNECT_PING_TIMEOUT_S", "10"))

    process_manager.start_worker()

    status_resp = None
    try:
        status_resp = rpc.request("GET_STATUS", {}, timeout=2.0)
    except Exception:
        status_resp = None

    if status_resp and status_resp.get("ok"):
        data = status_resp.get("data") or {}
        if data.get("busy"):
            return False, {"reason": "busy", "status": data}

    if not _wait_ping_ok(timeout_s=ping_timeout_s):
        return False, {"reason": "ping_timeout_before_kill"}

    t1 = time.time()
    log.info(f"【{case_id}】2.2.1.1：连接成功（在线） {_now_text()}")

    log.info(f"【{case_id}】2.2.1.2：连接断开 {_now_text()}")
    process_manager.kill_worker()
    t2 = time.time()

    time.sleep(max(0.0, disconnect_window_s))

    process_manager.start_worker()
    t3_start = time.time()

    if not _wait_ping_ok(timeout_s=restart_ping_timeout_s):
        return False, {"reason": "ping_timeout_after_restart", "t1": t1, "t2": t2, "t3_start": t3_start}

    t3 = time.time()
    log.info(f"【{case_id}】2.2.1.3：重连成功 {_now_text()}")

    return True, {
        "t1": t1,
        "t2": t2,
        "t3": t3,
        "disconnect_window_s": disconnect_window_s,
    }

def _run_2_5_1_orchestrate(case_id: str) -> tuple[bool, dict]:
    """
    编排 2.5.1 测试：
    1. 调用 RPC 执行 2.5.1.1 和 2.5.1.2
    2. 等待执行完成
    3. 执行 2.5.1.3 (强制账号退出/Kill Worker)
    """
    # 1. 确保 Worker 启动
    process_manager.start_worker()
    if not _wait_ping_ok(10):
         return False, {"reason": "ping_timeout_start"}

    # 2. 调用 RPC 执行前两个子项
    resp = rpc.request("RUN_CASE", {"case_id": case_id}, timeout=3.0)
    if not resp.get("ok") or not resp.get("data", {}).get("accepted"):
        return False, {"reason": "rpc_failed_or_busy", "resp": resp, "busy": True}

    # 3. 等待 RPC 任务结束
    log.info(f"【{case_id}】等待 2.5.1.1/2.5.1.2 执行完成...")
    max_wait = 120 
    start_wait = time.time()
    rpc_finished = False
    
    while time.time() - start_wait < max_wait:
        time.sleep(1)
        status = None
        try:
            status = rpc.request("GET_STATUS", {}, timeout=2.0)
        except:
            pass
            
        if status and status.get("ok"):
            data = status.get("data") or {}
            # 当 busy 为 False 且 current_case_id 为 None 时认为结束
            if not data.get("busy") and not data.get("current_case_id"):
                rpc_finished = True
                break
    
    if not rpc_finished:
         return False, {"reason": "timeout_waiting_for_part1_2"}

    # 4. 执行 2.5.1.3 强制退出
    log.info(f"【{case_id}】2.5.1.3：强制账号退出（模拟断电/进程终止） {_now_text()}")
    
    t1 = time.time()
    process_manager.kill_worker()
    t2 = time.time()
    log.info(f"【{case_id}】Worker 已终止")

    disconnect_window_s = float(os.environ.get("HARD_DISCONNECT_WINDOW_S", "10"))
    time.sleep(max(0.0, disconnect_window_s))

    process_manager.start_worker()
    
    restart_ping_timeout_s = float(os.environ.get("HARD_DISCONNECT_RESTART_PING_TIMEOUT_S", "60"))
    if not _wait_ping_ok(restart_ping_timeout_s):
        return False, {"reason": "restart_failed_after_kill"}
        
    t3 = time.time()
    log.info(f"【{case_id}】2.5.1.3：重连成功 {_now_text()}")

    return True, {
        "t1": t1,
        "t2": t2,
        "t3": t3,
        "disconnect_window_s": disconnect_window_s
    }

@app.route('/api/run/<case_id>', methods=['POST'])
def run_case(case_id):
    process_manager.start_worker()
    case_id = (case_id or "").strip()
    if case_id == "2.2.1":
        ok, data = _hard_disconnect_orchestrate(case_id)
        if not ok and data.get("reason") == "busy":
            return jsonify({"status": "busy", "msg": "当前有测试正在运行，请等待结束", "data": data}), 200
        if not ok:
            return jsonify({"status": "error", "msg": f"{case_id} 连接中断演练失败", "data": data}), 500
        return jsonify({"status": "success", "msg": f"{case_id} 连接中断演练已完成", "data": data})

    if case_id == "2.5.1":
        ok, data = _run_2_5_1_orchestrate(case_id)
        if not ok:
            is_busy = data.get("busy") or (data.get("reason") == "rpc_failed_or_busy")
            msg = "当前有测试正在运行，请等待结束" if is_busy else f"{case_id} 执行失败: {data.get('reason')}"
            status_code = 200 if is_busy else 500
            return jsonify({"status": "busy" if is_busy else "error", "msg": msg, "data": data}), status_code
        return jsonify({"status": "success", "msg": f"{case_id} 测试已完成", "data": data})

    resp = rpc.request("RUN_CASE", {"case_id": case_id}, timeout=3.0)
    if not resp.get("ok"):
        return jsonify({"status": "error", "msg": resp.get("error", "RPC 调用失败")}), 500

    accepted = bool((resp.get("data") or {}).get("accepted"))
    return jsonify(
        {
            "status": "success" if accepted else "busy",
            "msg": "测试任务已启动" if accepted else "当前有测试正在运行，请等待结束",
        }
    )

@app.route('/api/control/reset', methods=['POST'])
def reset_system():
    process_manager.start_worker()
    resp = rpc.request("RESET_RISK", {}, timeout=3.0)
    if not resp.get("ok"):
        return jsonify({"status": "error", "msg": resp.get("error", "RPC 调用失败")}), 500
    return jsonify({"status": "success", "msg": "系统状态已重置"})

@app.route("/api/risk/thresholds", methods=["GET"])
def get_risk_thresholds():
    process_manager.start_worker()
    resp = rpc.request("GET_THRESHOLDS", {}, timeout=2.0)
    if not resp.get("ok"):
        return jsonify({"status": "error", "msg": resp.get("error", "RPC 调用失败")}), 500
    return jsonify({"status": "success", "data": resp.get("data") or {}})


@app.route("/api/risk/thresholds", methods=["POST"])
def set_risk_thresholds():
    process_manager.start_worker()
    body = request.get_json(silent=True) or {}

    payload = {}
    if "max_order_count" in body:
        payload["max_order_count"] = body.get("max_order_count")
    if "max_cancel_count" in body:
        payload["max_cancel_count"] = body.get("max_cancel_count")
    if "max_repeat_count" in body:
        payload["max_repeat_count"] = body.get("max_repeat_count")

    resp = rpc.request("SET_THRESHOLDS", payload, timeout=3.0)
    if not resp.get("ok"):
        return jsonify({"status": "error", "msg": resp.get("error", "RPC 调用失败")}), 500
    return jsonify({"status": "success", "data": resp.get("data") or {}})


@app.route("/api/test/config", methods=["GET"])
def get_test_config():
    process_manager.start_worker()
    resp = rpc.request("GET_TEST_CONFIG", {}, timeout=2.0)
    if not resp.get("ok"):
        return jsonify({"status": "error", "msg": resp.get("error", "RPC 调用失败")}), 500
    return jsonify({"status": "success", "data": resp.get("data") or {}})


@app.route("/api/test/config", methods=["POST"])
def set_test_config():
    process_manager.start_worker()
    body = request.get_json(silent=True) or {}
    
    payload = {}
    if "test_symbol" in body:
        payload["test_symbol"] = body.get("test_symbol")
    if "safe_buy_price" in body:
        payload["safe_buy_price"] = body.get("safe_buy_price")
    if "deal_buy_price" in body:
        payload["deal_buy_price"] = body.get("deal_buy_price")

    resp = rpc.request("SET_TEST_CONFIG", payload, timeout=3.0)
    if not resp.get("ok"):
        return jsonify({"status": "error", "msg": resp.get("error", "RPC 调用失败")}), 500
    return jsonify({"status": "success", "data": resp.get("data") or {}})


@app.route("/api/risk/snapshot", methods=["GET"])
def get_risk_snapshot():
    process_manager.start_worker()
    resp = rpc.request("GET_RISK_SNAPSHOT", {}, timeout=2.0)
    if not resp.get("ok"):
        return jsonify({"status": "error", "msg": resp.get("error", "RPC 调用失败")}), 500
    return jsonify({"status": "success", "data": resp.get("data") or {}})


@app.route("/api/worker/status", methods=["GET"])
def worker_status():
    process_manager.start_worker()
    resp = rpc.request("GET_STATUS", {}, timeout=2.0)
    if not resp.get("ok"):
        return jsonify({"status": "error", "msg": resp.get("error", "RPC 调用失败")}), 500
    return jsonify({"status": "success", "data": resp.get("data")})


@app.route("/api/worker/restart", methods=["POST"])
def worker_restart():
    process_manager.restart_worker()
    return jsonify({"status": "success", "msg": "Worker 已重启"})


@app.route("/api/worker/kill", methods=["POST"])
def worker_kill():
    process_manager.kill_worker()
    return jsonify({"status": "success", "msg": "Worker 已终止"})

if __name__ == '__main__':
    # process_manager.start_worker() # Delayed until login
    socketio.run(app, host='0.0.0.0', port=5006, debug=False)
