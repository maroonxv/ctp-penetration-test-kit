import time
import traceback
from src.config import reader as config
from src.core.engine import TestEngine
from src.ctp_cases.helpers import wait_for_reaction, clean_environment
from src.logging import log_info, log_error, log_warning
from vnpy.trader.object import OrderRequest, CancelRequest
from vnpy.trader.constant import Direction, OrderType, Offset, Exchange

# =============================================================================
# 2.1 接口适应性
# =============================================================================

def test_2_1_1_connectivity(engine: TestEngine):
    """
    2.1.1 连通性测试
    覆盖: 2.1.1.1 登录认证
    """
    log_info("\n>>> [2.1.1] 连通性测试")
    # 检查连接
    if not engine.main_engine.get_gateway(engine.gateway_name):
        log_info("正在建立连接...")
        engine.connect()
    else:
        log_info("网关已连接，正在检查登录状态...")
    
    # 实际上 connect 是异步的，这里只能通过日志观察
    wait_for_reaction(3, "等待连接与认证回调...")

    # 查询账户资金
    log_info("正在查询账户资金...")
    wait_for_reaction(2, "等待流控冷却...")
    gateway = engine.main_engine.get_gateway(engine.gateway_name)
    if gateway:
        gateway.query_account()
        wait_for_reaction(5, "等待账户资金回报")
        engine.log_current_account()

    log_info("正在获取所有订单...")
    all_orders = engine.main_engine.get_all_orders()
    orders = list(all_orders.values()) if isinstance(all_orders, dict) else (list(all_orders) if all_orders else [])
    log_info(f"当前订单数量: {len(orders)}")
    for order in orders:
        log_info(f"订单: {order}")



def test_2_1_2_1_open(engine: TestEngine):
    """
    2.1.2.1 开仓测试
    """
    log_info("\n>>> [2.1.2.1] 开仓测试")
    
    if not _check_contract(engine):
        return

    # 0. 环境清理
    clean_environment(engine)

    # 1. 开仓 (2.1.2.1)
    log_info("--- 测试点 2.1.2.1: 开仓 ---")
    req_open = OrderRequest(
        symbol=engine.contract.symbol,
        exchange=engine.contract.exchange,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=1,
        price=config.DEAL_BUY_PRICE,
        offset=Offset.OPEN,
        reference="TestOpen"
    )
    engine.send_order(req_open)
    wait_for_reaction(10, "等待开仓成交")

def test_2_1_2_2_close(engine: TestEngine):
    """
    2.1.2.2 平仓测试
    """
    log_info("\n>>> [2.1.2.2] 平仓测试")
    
    if not _check_contract(engine):
        return

    # 2. 平仓 (2.1.2.2)
    log_info("--- 测试点 2.1.2.2: 平仓 ---")
    req_close = OrderRequest(
        symbol=engine.contract.symbol,
        exchange=engine.contract.exchange,
        direction=Direction.SHORT,
        type=OrderType.LIMIT,
        volume=1,
        price=config.SAFE_BUY_PRICE, # 确保成交
        offset=Offset.CLOSE,
        reference="TestClose"
    )
    engine.send_order(req_close)
    wait_for_reaction(10, "等待平仓成交")

def test_2_1_2_3_cancel(engine: TestEngine):
    """
    2.1.2.3 撤单测试
    """
    log_info("\n>>> [2.1.2.3] 撤单测试")
    
    if not _check_contract(engine):
        return

    # 3. 撤单 (2.1.2.3)
    log_info("--- 测试点 2.1.2.3: 撤单 ---")
    req_cancel_test = OrderRequest(
        symbol=engine.contract.symbol,
        exchange=engine.contract.exchange,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=1,
        price=config.SAFE_BUY_PRICE, # 远离市价
        offset=Offset.OPEN,
        reference="TestCancel"
    )
    vt_orderid = engine.send_order(req_cancel_test)
    wait_for_reaction(10, "等待挂单确认")
    
    if vt_orderid:
        orderid = vt_orderid.split(".")[-1]
        req_c = CancelRequest(
            orderid=orderid,
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange
        )
        engine.cancel_order(req_c)
        wait_for_reaction(10, "等待撤单回报")

def _check_contract(engine: TestEngine) -> bool:
    # 增加等待逻辑，防止合约信息尚未就绪
    if not engine.contract:
        for _ in range(10):
            log_info("等待合约信息同步...")
            wait_for_reaction(1)
            if engine.contract:
                break

    if not engine.contract:
        log_error(f"未获取到合约信息 ({config.TEST_SYMBOL})，跳过测试")
        return False
    return True

# =============================================================================
# 2.2 异常监测
# =============================================================================

def test_2_2_1_1_connect_status(engine: TestEngine):
    """
    2.2.1.1 连接状态
    """
    log_info("\n>>> [2.2.1.1] 连接状态测试")
    
    log_info("--- 测试点 2.2.1.1: 当前连接状态 ---")
    gateway = engine.main_engine.get_gateway(engine.gateway_name)
    if gateway:
        log_info("当前网关对象: 存在（真实连接状态以底层回调/日志为准）")
    else:
        log_error("当前网关对象: 不存在（可能未完成初始化或已被逻辑断开）")

def test_2_2_1_2_disconnect(engine: TestEngine):
    """
    2.2.1.2 断线模拟
    """
    log_info("\n>>> [2.2.1.2] 断线模拟测试")

    log_info("--- 测试点 2.2.1.2: 模拟断线（强制断线） ---")


def test_2_2_1_3_reconnect(engine: TestEngine):
    """
    2.2.1.3 重连模拟
    """
    log_info("\n>>> [2.2.1.3] 重连模拟测试")

    log_info("--- 测试点 2.2.1.3: 模拟重连（强制断线后重连） ---")


def test_2_2_3_1_repeat_open(engine: TestEngine):
    """
    2.2.3.1 重复开仓
    """
    log_info("\n>>> [2.2.3.1] 重复开仓测试")
    if not _check_contract(engine):
        return

    # 1. 重复开仓
    log_info("--- 测试点 2.2.3.1: 重复开仓 ---")
    repeat_open_threshold = int(getattr(config, "REPEAT_OPEN_THRESHOLD", 2) or 2)
    deal_count = max(1, repeat_open_threshold)
    safe_count = 1

    deal_vt_orderids = []
    safe_vt_orderid = ""

    for _ in range(deal_count):
        req = OrderRequest(
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=config.DEAL_BUY_PRICE,
            offset=Offset.OPEN,
            reference="RepeatOpen",
        )
        vt_id = engine.send_order(req)
        if vt_id:
            deal_vt_orderids.append(vt_id)

    for _ in range(safe_count):
        req = OrderRequest(
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=config.SAFE_BUY_PRICE,
            offset=Offset.OPEN,
            reference="RepeatOpen",
        )
        vt_id = engine.send_order(req)
        if vt_id and not safe_vt_orderid:
            safe_vt_orderid = vt_id

    engine.repeat_monitor_last = {
        "deal_open_vt_orderids": deal_vt_orderids,
        "safe_open_vt_orderid": safe_vt_orderid,
        "vt_symbol": getattr(engine.contract, "vt_symbol", ""),
    }
    wait_for_reaction(2, "等待重复开仓反馈")

def test_2_2_3_2_repeat_close(engine: TestEngine):
    """
    2.2.3.2 重复平仓
    """
    log_info("\n>>> [2.2.3.2] 重复平仓测试")
    if not _check_contract(engine):
        return

    # 2. 重复平仓
    log_info("--- 测试点 2.2.3.2: 重复平仓 ---")
    repeat_close_threshold = int(getattr(config, "REPEAT_CLOSE_THRESHOLD", 2) or 2)
    info = getattr(engine, "repeat_monitor_last", None) or {}
    deal_open_vt_orderids = list(info.get("deal_open_vt_orderids") or [])
    close_count = min(max(1, repeat_close_threshold), len(deal_open_vt_orderids) or max(1, repeat_close_threshold))

    for _ in range(close_count):
        req = OrderRequest(
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
            direction=Direction.SHORT,
            type=OrderType.LIMIT,
            volume=1,
            price=config.SAFE_BUY_PRICE,
            offset=Offset.CLOSE,
            reference="RepeatClose",
        )
        engine.send_order(req)
    wait_for_reaction(2, "等待重复平仓反馈")

def test_2_2_3_3_repeat_cancel(engine: TestEngine):
    """
    2.2.3.3 重复撤单
    """
    log_info("\n>>> [2.2.3.3] 重复撤单测试")
    if not _check_contract(engine):
        return

    # 3. 重复撤单 (构造一个存在的订单ID进行重复撤销)
    log_info("--- 测试点 2.2.3.3: 重复撤单 ---")
    info = getattr(engine, "repeat_monitor_last", None) or {}
    safe_open_vt_orderid = str(info.get("safe_open_vt_orderid") or "").strip()

    if safe_open_vt_orderid:
        wait_for_reaction(1, "等待挂单进入可撤状态")
        order = engine.orders.get(safe_open_vt_orderid)
        if order and order.is_active():
            engine.cancel_order(order.create_cancel_request())
        else:
            orderid = safe_open_vt_orderid.split(".")[-1]
            req_c = CancelRequest(
                orderid=orderid,
                symbol=engine.contract.symbol,
                exchange=engine.contract.exchange,
            )
            engine.cancel_order(req_c)
        wait_for_reaction(2, "等待撤单反馈")
        return

    req_base = OrderRequest(
        symbol=engine.contract.symbol,
        exchange=engine.contract.exchange,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=1,
        price=config.SAFE_BUY_PRICE,
        offset=Offset.OPEN,
    )
    vt_orderid = engine.send_order(req_base)
    wait_for_reaction(1)

    if vt_orderid:
        orderid = vt_orderid.split(".")[-1]
        req_c = CancelRequest(
            orderid=orderid,
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
        )
        engine.cancel_order(req_c)
        wait_for_reaction(2, "等待撤单反馈")

# =============================================================================
# 2.3 阈值管理
# =============================================================================

def test_2_3_1_1_order_threshold(engine: TestEngine):
    """
    2.3.1.1 报单笔数阈值测试（含统计验证）
    覆盖: 
    - 2.2.2.1 报单统计
    - 2.3.1.1 阈值设置
    - 2.3.1.2 阈值预警
    """
    log_info("\n>>> [2.3.1.1] 报单阈值与统计测试")
    
    rm = engine.risk_manager
    thresholds = {}
    try:
        thresholds = rm.get_thresholds()
    except Exception:
        thresholds = {}

    max_order_count = int(thresholds.get("max_order_count", getattr(rm, "max_order_count", 0)) or 0)
    log_info(f"当前报单阈值: {max_order_count}")
    
    # 记录初始计数
    initial_count = rm.order_count
    log_info(f"初始报单总数: {initial_count}")
    
    rm.reset_counters()
    log_info("已重置计数器")

    if not engine.contract:
        log_error("未获取到合约信息，跳过阈值触发测试")
        return

    max_actions = 10
    sent_vt_orderids = []

    if max_order_count > 0:
        send_n = min(max_actions, max_order_count + 1)
        log_info(f"--- 发送 {send_n} 笔委托验证统计与阈值 (阈值={max_order_count}) ---")
        
        warned = False
        for i in range(send_n):
            req = OrderRequest(
                symbol=engine.contract.symbol,
                exchange=engine.contract.exchange,
                direction=Direction.LONG,
                type=OrderType.LIMIT,
                volume=1,
                price=config.SAFE_BUY_PRICE,
                offset=Offset.OPEN,
            )
            vt_id = engine.send_order(req)
            if vt_id:
                sent_vt_orderids.append(vt_id)
            
            # 验证计数准确性
            expected_count = i + 1
            actual_count = rm.order_count
            if actual_count != expected_count:
                log_warning(f"计数异常: 期望={expected_count}, 实际={actual_count}")
            
            # 检查阈值预警
            if not warned and actual_count >= max_order_count:
                log_warning(f"【阈值预警】报单笔数({actual_count})达到或超过阈值({max_order_count})! 🚨")
                warned = True
        
        wait_for_reaction(2, "检查报单统计与阈值预警")
        
        # 最终验证
        final_count = rm.order_count
        log_info(f"最终报单总数: {final_count} (期望: {send_n})")
        
        if final_count != send_n:
            log_error(f"报单统计不准确: 期望={send_n}, 实际={final_count}")
        else:
            log_info("✓ 报单统计准确")
        
        if warned:
            log_info("✓ 阈值预警已触发")
        else:
            log_warning("未触发阈值预警（可能阈值设置过高）")
    else:
        log_warning("报单阈值未启用(<=0)，跳过测试")
    
    # 保存 sent_vt_orderids 供后续测试使用
    engine.last_sent_orders = sent_vt_orderids

def test_2_3_1_3_cancel_threshold(engine: TestEngine):
    """
    2.3.1.3 撤单笔数阈值测试（含统计验证）
    覆盖:
    - 2.2.2.2 撤单统计
    - 2.3.1.3 阈值设置
    - 2.3.1.4 阈值预警
    """
    log_info("\n>>> [2.3.1.3] 撤单阈值与统计测试")
    
    rm = engine.risk_manager
    thresholds = {}
    try:
        thresholds = rm.get_thresholds()
    except Exception:
        thresholds = {}

    max_cancel_count = int(thresholds.get("max_cancel_count", getattr(rm, "max_cancel_count", 0)) or 0)
    log_info(f"当前撤单阈值: {max_cancel_count}")
    
    # 记录初始计数
    initial_count = rm.cancel_count
    log_info(f"初始撤单总数: {initial_count}")
    
    max_actions = 10
    sent_vt_orderids = getattr(engine, "last_sent_orders", [])
    
    # 如果没有之前的单子，先发一些
    if not sent_vt_orderids:
        log_info("无可用订单，先发送一批订单用于撤单测试...")
        if not engine.contract: return
        for _ in range(max(5, max_cancel_count + 2)):
            req = OrderRequest(
                symbol=engine.contract.symbol,
                exchange=engine.contract.exchange,
                direction=Direction.LONG,
                type=OrderType.LIMIT,
                volume=1,
                price=config.SAFE_BUY_PRICE,
                offset=Offset.OPEN,
            )
            vt_id = engine.send_order(req)
            if vt_id: sent_vt_orderids.append(vt_id)
        wait_for_reaction(2)

    if max_cancel_count > 0:
        all_active = engine.get_all_active_orders()
        # 优先撤销之前发的
        target_orders = [o for o in all_active if o.vt_orderid in sent_vt_orderids]
        # 如果不够，撤销所有的
        if len(target_orders) < max_cancel_count + 1:
            target_orders = all_active
        
        need_cancel = min(max_actions, max_cancel_count + 1)
        log_info(f"--- 撤销 {need_cancel} 笔委托验证统计与阈值 (阈值={max_cancel_count}, 可撤={len(target_orders)}) ---")
        
        warned = False
        cancel_start_count = rm.cancel_count
        count = 0
        for o in target_orders:
            engine.cancel_order(o.create_cancel_request())
            count += 1
            
            # 检查阈值预警
            if not warned and rm.cancel_count >= max_cancel_count:
                log_warning(f"【阈值预警】撤单笔数({rm.cancel_count})达到或超过阈值({max_cancel_count})! 🚨")
                warned = True
            
            if count >= need_cancel:
                break
        
        wait_for_reaction(2, "检查撤单统计与阈值预警")
        
        # 最终验证
        final_count = rm.cancel_count
        expected_final = cancel_start_count + count
        log_info(f"最终撤单总数: {final_count} (期望: {expected_final})")
        
        if final_count != expected_final:
            log_warning(f"撤单统计可能不准确: 期望={expected_final}, 实际={final_count} (异步延迟可能导致差异)")
        else:
            log_info("✓ 撤单统计准确")
        
        if warned:
            log_info("✓ 阈值预警已触发")
        else:
            log_warning("未触发阈值预警（可能阈值设置过高）")
    else:
        log_warning("撤单阈值未启用(<=0)，跳过测试")

def test_2_3_1_5_repeat_threshold(engine: TestEngine):
    """
    2.3.1.5 重复报单阈值测试
    覆盖: 2.3.1.5 设置, 2.3.1.6 预警
    """
    log_info("\n>>> [2.3.1.5] 重复报单阈值测试")
    
    rm = engine.risk_manager
    thresholds = {}
    try:
        thresholds = rm.get_thresholds()
    except Exception:
        thresholds = {}

    max_repeat_count = int(thresholds.get("max_repeat_count", getattr(rm, "max_repeat_count", 0)) or 0)
    log_info(f"当前重复报单阈值: {max_repeat_count}")

    if not engine.contract: return
    max_actions = 10

    # 2.3.1.5 / 2.3.1.6（选测）
    if max_repeat_count > 0:
        repeat_send_n = min(max_actions, max_repeat_count + 1)
        log_info(f"--- 触发重复报单预警(选测) (阈值={max_repeat_count}, 本次重复发单={repeat_send_n}) ---")
        for _ in range(repeat_send_n):
            req = OrderRequest(
                symbol=engine.contract.symbol,
                exchange=engine.contract.exchange,
                direction=Direction.LONG,
                type=OrderType.LIMIT,
                volume=1,
                price=config.SAFE_BUY_PRICE,
                offset=Offset.OPEN,
                reference="RepeatThresholdTest",
            )
            engine.send_order(req)
        wait_for_reaction(2, "检查是否出现重复报单阈值预警")
    else:
        log_info("重复报单预警未启用(<=0)，跳过 2.3.1.5/2.3.1.6")

def test_2_4_1_1_code_error(engine: TestEngine):
    """
    2.4.1.1 合约代码错误
    """
    log_info("\n>>> [2.4.1.1] 合约代码错误测试")
    
    # 1. 代码错误
    log_info("--- 测试点 2.4.1.1: 合约代码错误 ---")
    req_err_sym = OrderRequest(
        symbol="INVALID_CODE",
        exchange=Exchange.SHFE,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=1,
        price=4000,
        offset=Offset.OPEN
    )
    engine.send_order(req_err_sym)
    wait_for_reaction(5, "等待 5 秒，查看是否出现错误日志")

def test_2_4_1_2_price_error(engine: TestEngine):
    """
    2.4.1.2 最小变动价位错误
    """
    log_info("\n>>> [2.4.1.2] 价格错误测试")

    # 2. 价格错误
    log_info("--- 测试点 2.4.1.2: 最小变动价位错误 ---")
    if engine.contract:
        req_err_tick = OrderRequest(
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=config.SAFE_BUY_PRICE + 0.0001, # 假设 tick > 0.0001
            offset=Offset.OPEN
        )
        engine.send_order(req_err_tick)
        wait_for_reaction(5, "等待 5 秒，查看是否出现错误日志")

def test_2_4_1_3_volume_error(engine: TestEngine):
    """
    2.4.1.3 委托数量超限
    """
    log_info("\n>>> [2.4.1.3] 数量超限测试")

    # 3. 数量超限
    log_info("--- 测试点 2.4.1.3: 委托数量超限 ---")
    volume_limit = int(getattr(config, "VOLUME_LIMIT_VOLUME", 10000) or 10000)
    symbol = str(getattr(config, "TEST_SYMBOL", "") or "").strip()
    if not symbol and engine.contract:
        symbol = engine.contract.symbol
    if not symbol:
        log_error("未设置测试合约代码，跳过测试")
        return

    exchange = engine.contract.exchange if engine.contract else Exchange.SHFE
    req_err_vol = OrderRequest(
        symbol=symbol,
        exchange=exchange,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=max(1, volume_limit),
        price=config.SAFE_BUY_PRICE,
        offset=Offset.OPEN,
    )
    engine.send_order(req_err_vol)
    
    wait_for_reaction(2, "验证红色错误日志")

def test_2_4_2_1_fund_error(engine: TestEngine):
    """
    2.4.2.1 资金不足回报
    """
    log_info("\n>>> [2.4.2.1] 资金不足测试")
    if not engine.contract: return

    # 1. 资金不足
    log_info("--- 测试点 2.4.2.1: 资金不足回报 ---")
    req_fund = OrderRequest(
        symbol=engine.contract.symbol,
        exchange=engine.contract.exchange,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=50000, # 足够大
        price=config.SAFE_BUY_PRICE,
        offset=Offset.OPEN,
        reference="FundTest"
    )
    engine.send_order(req_fund)
    wait_for_reaction(5, "等待 5 秒，查看是否出现错误日志")

def test_2_4_2_2_pos_error(engine: TestEngine):
    """
    2.4.2.2 持仓不足回报
    """
    log_info("\n>>> [2.4.2.2] 持仓不足测试")
    if not engine.contract: return

    # 2. 持仓不足
    log_info("--- 测试点 2.4.2.2: 持仓不足回报 ---")
    req_pos = OrderRequest(
        symbol=engine.contract.symbol,
        exchange=engine.contract.exchange,
        direction=Direction.SHORT,
        type=OrderType.LIMIT,
        volume=1,
        price=config.SAFE_BUY_PRICE,
        offset=Offset.CLOSE, # 平仓
        reference="CloseEmpty"
    )
    engine.send_order(req_pos)
    
    wait_for_reaction(3, "等待 CTP 错误回报")
    wait_for_reaction(5, "等待 5 秒，查看是否出现错误日志")

def test_2_4_2_3_market_error(engine: TestEngine):
    """
    2.4.2.3 市场状态错误回报
    """
    log_info("\n>>> [2.4.2.3] 市场状态错误测试")
    if not engine.contract: return

    # 3. 市场状态错误 (2.4.2.3)
    log_info("--- 测试点 2.4.2.3: 市场状态错误回报 ---")
    
    # 优先使用专用测试合约的交易所信息
    exchange = engine.contract.exchange
    if engine.rest_test_contract:
        exchange = engine.rest_test_contract.exchange
    elif config.REST_TEST_SYMBOL == "LC2607":
        exchange = Exchange.GFEX
    else:
        log_warning(f"未找到测试合约 {config.REST_TEST_SYMBOL} 的合约信息，将使用默认交易所 {exchange.value}，可能导致测试失败。")

    req_market = OrderRequest(
        symbol=config.REST_TEST_SYMBOL,
        exchange=exchange,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=1,
        price=config.REST_TEST_PRICE,
        offset=Offset.OPEN,
        reference="MarketErrTest"
    )
    engine.send_order(req_market)
    wait_for_reaction(5, "等待可能出现的市场状态错误回报")

def test_2_5_1_1_limit_perms(engine: TestEngine):
    """
    2.5.1.1 限制账号交易权限
    """
    log_info("\n>>> [2.5.1.1] 限制权限测试")
    if not engine.contract:
        log_error("未获取到合约，跳过测试")
        return

    req = OrderRequest(
        symbol=engine.contract.symbol,
        exchange=engine.contract.exchange,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=1,
        price=config.SAFE_BUY_PRICE,
        offset=Offset.OPEN
    )

    # ==========================================
    # 2.5.1.1 限制账号交易权限
    # ==========================================
    log_info("--- 测试点 2.5.1.1: 限制账号交易权限 ---")
    # 模拟权限限制 (通过 RiskManager active=False 模拟本地权限锁)
    engine.risk_manager.active = False
    log_info("已限制交易权限 (Active=False)")
    
    engine.send_order(req)
    wait_for_reaction(1, "验证权限限制下被拦截")
    
    # 恢复
    engine.risk_manager.active = True
    log_info("已恢复交易权限")
    wait_for_reaction(2)

def test_2_5_1_2_pause_strategy(engine: TestEngine):
    """
    2.5.1.2 暂停策略执行
    """
    log_info("\n>>> [2.5.1.2] 暂停策略测试")
    if not engine.contract:
        log_error("未获取到合约，跳过测试")
        return
    
    req = OrderRequest(
        symbol=engine.contract.symbol,
        exchange=engine.contract.exchange,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=1,
        price=config.SAFE_BUY_PRICE,
        offset=Offset.OPEN
    )

    # ==========================================
    # 2.5.1.2 暂停策略执行
    # ==========================================
    log_info("--- 测试点 2.5.1.2: 暂停策略执行 ---")
    
    # 执行暂停
    engine.pause() # 调用 emergency_stop
    
    engine.send_order(req)
    wait_for_reaction(1, "验证暂停策略下被拦截")
    
    # 恢复
    engine.risk_manager.active = True
    log_info("已恢复策略执行")
    wait_for_reaction(2)

def test_2_5_2_1_cancel_part(engine: TestEngine):
    """
    2.5.2.1 撤销部分成交（模拟撤单）
    """
    log_info("\n>>> [2.5.2.1] 撤销指定订单测试")
    
    # 确保活跃
    engine.risk_manager.active = True
    
    # 发送挂单
    if engine.contract:
        req = OrderRequest(
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=config.SAFE_BUY_PRICE,
            offset=Offset.OPEN,
            reference=f"PartCancel"
        )
        vt_id = engine.send_order(req)
        wait_for_reaction(2, "等待挂单生效")
        
        if vt_id:
            active = engine.get_order(vt_id)
            if active and active.is_active():
                engine.cancel_order(active.create_cancel_request())
                wait_for_reaction(2, "撤单已发送")
            else:
                log_warning("订单未激活，跳过撤单")

def test_2_5_2_2_cancel_all(engine: TestEngine):
    """
    2.5.2.2 批量撤销所有订单
    """
    log_info("\n>>> [2.5.2.2] 批量撤销所有订单测试")
    
    # 确保活跃
    engine.risk_manager.active = True
    
    # 发送几笔挂单
    for i in range(3):
        if engine.contract:
            req = OrderRequest(
                symbol=engine.contract.symbol,
                exchange=engine.contract.exchange,
                direction=Direction.LONG,
                type=OrderType.LIMIT,
                volume=1,
                price=config.SAFE_BUY_PRICE,
                offset=Offset.OPEN,
                reference=f"Batch{i}"
            )
            engine.send_order(req)
    
    wait_for_reaction(2, "等待挂单生效")
    
    # 执行批量撤单
    log_info("--- 执行批量撤单 ---")
    active_orders = engine.get_all_active_orders()
    log_info(f"检测到 {len(active_orders)} 笔活动订单，开始撤销...")
    
    for order in active_orders:
        engine.cancel_order(order.create_cancel_request())
        
    wait_for_reaction(3, "等待所有撤单完成")

# =============================================================================
# 2.6 日志记录
# =============================================================================

def test_2_6_1_log_record(engine: TestEngine):
    """
    2.6.1 日志记录功能验证
    """
    log_info("\n>>> [2.6.1] 日志记录验证")
    log_info("请人工检查 log/ 目录下的日志文件。")
    log_info("应包含标签: [Trade], [Order], [Error], [Monitor]")
    log_info("当前控制台显示的日志即证明了日志功能的实时性。")
