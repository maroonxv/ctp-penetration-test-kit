import logging


def color_for_log(levelno: int, msg: str) -> str:
    """统一的日志颜色分配函数。合并自 worker._color_for 和 socket_handler 内联逻辑。"""
    if levelno >= logging.ERROR:
        return "#ff4d4d"
    if levelno >= logging.WARNING:
        return "#ffbf00"
    if "OnRtn" in msg or "OnRsp" in msg or "收到" in msg or "回调" in msg:
        return "#00ccff"
    if "【" in msg or "Success" in msg or "成功" in msg:
        return "#00ff00"
    return "#cccccc"
