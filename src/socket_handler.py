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
            
            # 过滤 Werkzeug/Flask 访问日志
            if "GET /" in msg or "POST /" in msg or "HTTP/1.1" in msg or "socket.io" in msg:
                return
            
            # 颜色逻辑判断
            color = "#cccccc" # 默认灰色
            if record.levelno >= logging.ERROR:
                color = "#ff4d4d" # 红色
            elif record.levelno >= logging.WARNING:
                color = "#ffbf00" # 橙色
            elif "OnRtn" in msg or "OnRsp" in msg or "收到" in msg or "回调" in msg:
                color = "#00ccff" # 蓝色（CTP 回调）
            elif "【" in msg:
                color = "#00ff00" # 绿色（关键信息）
            elif "Success" in msg or "成功" in msg:
                color = "#00ff00" # 绿色
                
            # 推送事件
            self.socketio.emit('new_log', {'message': msg, 'color': color})
        except Exception:
            self.handleError(record)
