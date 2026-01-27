import os
import sys
import logging
import socket
import json
import uuid
import time
import subprocess

# Ensure project root is in sys.path when running as script
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from src.socket_handler import SocketIOHandler
from src import read_config as config
from src.logger import setup_logger

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ctp_test_secret'
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
    return {
        "CTP_NAME": config.CTP_NAME,
        "CTP_USERNAME": config.CTP_USERNAME,
        "CTP_TD_SERVER": config.CTP_TD_SERVER,
        "CTP_MD_SERVER": config.CTP_SETTING.get("行情服务器", "")
    }

@app.route('/')
def index():
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
    process_manager.start_worker()
    socketio.run(app, host='0.0.0.0', port=5006, debug=False)
