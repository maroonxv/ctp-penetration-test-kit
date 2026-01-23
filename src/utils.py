import time
from datetime import datetime, time as dtime
from typing import Optional
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

from src import config
from src.logger import log_info
from vnpy.trader.object import OrderRequest, CancelRequest
from vnpy.trader.constant import Direction, Offset, OrderType

def wait_for_reaction(seconds: int = config.ATOMIC_WAIT_SECONDS, msg: str = ""):
    """
    原子等待函数，确保网关/柜台有足够的时间处理请求。
    """
    time.sleep(seconds)

def clean_environment(engine):
    """
    清理交易环境：撤销所有挂单并平掉所有持仓。
    释放被占用的保证金，确保后续测试有足够资金。
    """
    log_info(">>> 开始清理交易环境...")
    
    # 1. 撤销所有挂单
    active_orders = engine.get_all_active_orders()
    if active_orders:
        log_info(f"发现 {len(active_orders)} 个挂单，正在撤销...")
        for order in active_orders:
            req = CancelRequest(
                orderid=order.orderid,
                symbol=order.symbol,
                exchange=order.exchange
            )
            engine.cancel_order(req)
        wait_for_reaction(2, "等待撤单完成")
    else:
        log_info("当前无挂单。")
        
    # 2. 平掉所有持仓
    # 注意：engine.main_engine.get_all_positions() 返回所有持仓
    positions = engine.main_engine.get_all_positions()
    has_position = False
    
    for pos in positions:
        if pos.volume > 0:
            has_position = True
            log_info(f"发现持仓: {pos.vt_symbol} {pos.direction.value} {pos.volume}手，正在平仓...")
            
            # 简单策略：多头用跌停价卖平，空头用涨停价买平 (这里简化处理，使用 DEAL_BUY_PRICE 微调)
            # 为了确保成交，多头平仓价格要极低，空头平仓价格要极高
            # 如果是 IF，涨停价约 5185，跌停价约 4242 (基于 4714 估算 10%)
            # 也可以直接用 config.DEAL_BUY_PRICE 作为参考
            
            close_price = 0.0
            close_direction = None
            
            if pos.direction == Direction.LONG:
                close_direction = Direction.SHORT
                close_price = 100.0 # 极低价卖出
            else:
                close_direction = Direction.LONG
                close_price = 100000.0 # 极高价买入
                
            req = OrderRequest(
                symbol=pos.symbol,
                exchange=pos.exchange,
                direction=close_direction,
                type=OrderType.LIMIT,
                volume=pos.volume,
                price=close_price,
                offset=Offset.CLOSE, # 优先平仓，不区分今昨
                reference="CleanEnv"
            )
            engine.send_order(req)
            
    if has_position:
        wait_for_reaction(5, "等待平仓成交")
        log_info("环境清理完成。")
    else:
        log_info("当前无持仓。")

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
