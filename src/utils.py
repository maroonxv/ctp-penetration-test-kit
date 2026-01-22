import time
from datetime import datetime, time as dtime
from typing import Optional
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

from src import config
from src.logger import log_info

def wait_for_reaction(seconds: int = config.ATOMIC_WAIT_SECONDS, msg: str = ""):
    """
    Atomic wait function to ensure gateway/counter has enough time to process requests.
    """
    if msg:
        log_info(f"Wait {seconds}s for: {msg}")
    else:
        log_info(f"Wait {seconds}s for reaction...")
    time.sleep(seconds)

def _now_cn() -> datetime:
    if ZoneInfo is None:
        return datetime.now()
    return datetime.now(ZoneInfo("Asia/Shanghai"))

def is_trading_time(now: Optional[datetime] = None) -> bool:
    if now is None:
        now = _now_cn()

    weekday = now.weekday()
    t = now.time()

    sessions = [
        (dtime(9, 0), dtime(10, 15)),
        (dtime(10, 30), dtime(11, 30)),
        (dtime(13, 0), dtime(15, 0)),
        (dtime(21, 0), dtime(23, 59, 59)),
        (dtime(0, 0), dtime(2, 30)),
    ]

    in_session = any(start <= t <= end for start, end in sessions)
    if not in_session:
        return False

    if t < dtime(3, 0):
        return weekday in (1, 2, 3, 4, 5)

    return weekday in (0, 1, 2, 3, 4)
