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

@app.route('/api/run/<case_id>', methods=['POST'])
def run_case(case_id):
    process_manager.start_worker()
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
