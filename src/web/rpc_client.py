import json
import socket
import uuid


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
