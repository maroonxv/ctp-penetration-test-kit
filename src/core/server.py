import socket
import threading
import json
from src import read_config as config
from src.logger import log_info, log_error

class CommandServer(threading.Thread):
    """
    RPC Server to receive control commands from external script (scripts/control.py).
    Commands: DISCONNECT, RECONNECT, PAUSE
    """
    def __init__(self, context):
        super().__init__()
        self.context = context  # Should provide methods: disconnect(), reconnect(), pause()
        self.host = config.RPC_HOST
        self.port = config.RPC_PORT
        self.running = True
        self.server_socket = None

    def run(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(1)
            log_info(f"Command Server listening on {self.host}:{self.port}")

            while self.running:
                try:
                    self.server_socket.settimeout(1.0)
                    client_socket, addr = self.server_socket.accept()
                    with client_socket:
                        client_socket.settimeout(0.5)
                        raw = b""
                        while True:
                            try:
                                chunk = client_socket.recv(4096)
                                if not chunk:
                                    break
                                raw += chunk
                                if b"\n" in raw or len(raw) > 65536:
                                    break
                            except socket.timeout:
                                break

                        data = raw.decode("utf-8", errors="replace").strip()
                        if not data:
                            continue

                        if data.startswith("{"):
                            try:
                                req = json.loads(data)
                                resp = self.process_request(req)
                            except Exception as e:
                                resp = {"ok": False, "error": f"invalid_request: {e}"}
                            client_socket.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                        else:
                            log_info(f"RPC Received command: {data}")
                            self.process_command(data)
                            client_socket.sendall(b"OK")
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        log_error(f"RPC Server accept error: {e}")

        except Exception as e:
            log_error(f"RPC Server startup error: {e}")
        finally:
            self.stop()

    def process_command(self, cmd: str):
        cmd = cmd.upper()
        if cmd == "DISCONNECT":
            self.context.disconnect()
        elif cmd == "RECONNECT":
            self.context.reconnect()
        elif cmd == "PAUSE":
            self.context.pause()
        else:
            log_error(f"Unknown RPC command: {cmd}")

    def process_request(self, req: dict) -> dict:
        if hasattr(self.context, "handle_rpc_request"):
            return self.context.handle_rpc_request(req)

        request_id = req.get("request_id")
        req_type = str(req.get("type", "")).upper()
        payload = req.get("payload") or {}

        try:
            if req_type == "PING":
                return {"request_id": request_id, "ok": True, "data": {"pong": True}}
            if req_type in {"DISCONNECT", "RECONNECT", "PAUSE"}:
                self.process_command(req_type)
                return {"request_id": request_id, "ok": True}
            if req_type == "GET_STATUS" and hasattr(self.context, "get_status"):
                return {"request_id": request_id, "ok": True, "data": self.context.get_status()}
            if req_type == "RESET_RISK" and hasattr(self.context, "reset_risk"):
                self.context.reset_risk()
                return {"request_id": request_id, "ok": True}
            if req_type == "RUN_CASE" and hasattr(self.context, "run_case"):
                accepted = self.context.run_case(str(payload.get("case_id", "")).strip())
                return {"request_id": request_id, "ok": True, "data": {"accepted": bool(accepted)}}
            return {"request_id": request_id, "ok": False, "error": f"unknown_type: {req_type}"}
        except Exception as e:
            return {"request_id": request_id, "ok": False, "error": str(e)}

    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        log_info("Command Server stopped.")
