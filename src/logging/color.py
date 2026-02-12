import logging


def color_for_log(levelno: int, msg: str) -> str:
    """统一的日志颜色分配函数。合并自 worker._color_for 和 socket_handler 内联逻辑。
    
    颜色方案与 CodexBar 深蓝主题协调：
    - 错误: #f85149 (danger-color)
    - 警告: #d29922 (warning-color)
    - 回调/响应: #58a6ff (accent-color)
    - 成功: #3fb950 (success-color)
    - 普通: #8b949e (text-secondary)
    """
    if levelno >= logging.ERROR:
        return "#f85149"  # danger-color
    if levelno >= logging.WARNING:
        return "#d29922"  # warning-color
    if "OnRtn" in msg or "OnRsp" in msg or "收到" in msg or "回调" in msg:
        return "#58a6ff"  # accent-color
    if "【" in msg or "Success" in msg or "成功" in msg or "✓" in msg:
        return "#3fb950"  # success-color
    return "#8b949e"  # text-secondary
