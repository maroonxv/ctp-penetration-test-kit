import logging

from flask_socketio import SocketIO

from src.logging.color import color_for_log


def _is_flask_noise(msg: str) -> bool:
    """过滤 Werkzeug/Flask 访问日志和 socket.io 轮询噪音。"""
    return "GET /" in msg or "POST /" in msg or "HTTP/1.1" in msg or "socket.io" in msg


class SocketIOHandler(logging.Handler):
    """直接推送到 SocketIO（Web 进程使用）。"""

    def __init__(self, socketio: SocketIO):
        super().__init__()
        self.socketio = socketio

    def emit(self, record):
        try:
            msg = self.format(record)
            if _is_flask_noise(msg):
                return
            color = color_for_log(record.levelno, msg)
            self.socketio.emit("new_log", {"message": msg, "color": color})
        except Exception:
            self.handleError(record)


class QueueLogHandler(logging.Handler):
    """通过队列转发日志（Worker 子进程使用）。原 _SocketLogHandler。"""

    def __init__(self, out_queue):
        super().__init__()
        self.out_queue = out_queue

    def emit(self, record):
        try:
            msg = self.format(record)
            if _is_flask_noise(msg):
                return
            color = color_for_log(record.levelno, msg)
            self.out_queue.put(("new_log", {"message": msg, "color": color}))
        except Exception:
            self.handleError(record)
