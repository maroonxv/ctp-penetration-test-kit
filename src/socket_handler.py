import logging
from flask_socketio import SocketIO

class SocketIOHandler(logging.Handler):
    """
    将日志记录转发至 SocketIO
    """
    def __init__(self, socketio: SocketIO):
        super().__init__()
        self.socketio = socketio

    def emit(self, record):
        try:
            msg = self.format(record)
            
            # 颜色逻辑判断
            color = "#cccccc" # Default Grey
            if record.levelno >= logging.ERROR:
                color = "#ff4d4d" # Red
            elif record.levelno >= logging.WARNING:
                color = "#ffbf00" # Orange
            elif "OnRtn" in msg or "OnRsp" in msg or "收到" in msg or "回调" in msg:
                color = "#00ccff" # Blue (CTP Callback)
            elif "【" in msg:
                color = "#00ff00" # Green (Key Info)
            elif "Success" in msg or "成功" in msg:
                color = "#00ff00" # Green
                
            # 推送事件
            self.socketio.emit('new_log', {'message': msg, 'color': color})
        except Exception:
            self.handleError(record)
