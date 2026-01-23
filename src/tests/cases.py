import time
import traceback
from src import read_config as config
from src.core.engine import TestEngine
from src.utils import wait_for_reaction, clean_environment
from src.logger import log_info, log_error, log_warning
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

def test_2_1_2_basic_trading(engine: TestEngine):
    """
    2.1.2 基础交易功能
    覆盖: 2.1.2.1 开仓, 2.1.2.2 平仓, 2.1.2.3 撤单
    """
    log_info("\n>>> [2.1.2] 基础交易功能测试")
    if not engine.contract:
        log_error("未获取到合约信息，跳过测试")
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

# =============================================================================
# 2.2 异常监测
# =============================================================================

def test_2_2_1_connection_monitor(engine: TestEngine):
    """
    2.2.1 系统连接异常监测
    覆盖: 2.2.1.1 连接显示, 2.2.1.2 断线显示, 2.2.1.3 重连显示
    """
    log_info("\n>>> [2.2.1] 连接监测测试")
    
    # 2.2.1.1 连接状态
    log_info("--- 测试点 2.2.1.1: 当前连接状态 ---")
    gateway = engine.main_engine.get_gateway(engine.gateway_name)
    if gateway:
        log_info("当前网关状态: 已连接")
    else:
        log_error("当前网关未连接")

    # 2.2.1.2 断线模拟
    log_info("--- 测试点 2.2.1.2: 模拟断线 ---")
    engine.disconnect()
    wait_for_reaction(3, "等待断线日志 (OnFrontDisconnected)")

    # 2.2.1.3 重连模拟
    log_info("--- 测试点 2.2.1.3: 模拟重连 ---")
    engine.connect()
    wait_for_reaction(5, "等待重连日志 (OnFrontConnected)")
    
    # 重连后再次检查资金
    gateway = engine.main_engine.get_gateway(engine.gateway_name)
    if gateway:
        gateway.query_account()
        wait_for_reaction(2)
        engine.log_current_account()

def test_2_2_2_count_monitor(engine: TestEngine):
    """
    2.2.2 报撤单笔数监测
    覆盖: 2.2.2.1 报单统计, 2.2.2.2 撤单统计
    """
    log_info("\n>>> [2.2.2] 笔数监测测试")
    
    log_info(f"--- 测试点 2.2.2.1: 当前报单总数: {engine.risk_manager.order_count}")
    log_info(f"--- 测试点 2.2.2.2: 当前撤单总数: {engine.risk_manager.cancel_count}")
    
    # 发送一笔单测试计数增加
    if engine.contract:
        req = OrderRequest(
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=config.SAFE_BUY_PRICE,
            offset=Offset.OPEN
        )
        engine.send_order(req)
        wait_for_reaction(1, "验证计数器更新")
        log_info(f"更新后报单总数: {engine.risk_manager.order_count}")
        
        # 撤单
        active = engine.get_all_active_orders()
        for o in active:
            engine.cancel_order(o.create_cancel_request())
        wait_for_reaction(1, "验证撤单计数更新")
        log_info(f"更新后撤单总数: {engine.risk_manager.cancel_count}")

def test_2_2_3_repeat_monitor(engine: TestEngine):
    """
    2.2.3 重复报单监测
    覆盖: 2.2.3.1 重复开仓, 2.2.3.2 重复平仓, 2.2.3.3 重复撤单
    """
    log_info("\n>>> [2.2.3] 重复报单监测测试")
    if not engine.contract: return

    # 1. 重复开仓
    log_info("--- 测试点 2.2.3.1: 重复开仓 ---")
    for i in range(3):
        req = OrderRequest(
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=config.SAFE_BUY_PRICE,
            offset=Offset.OPEN,
            reference="RepeatOpen"
        )
        engine.send_order(req)
    wait_for_reaction(2, "等待重复开仓反馈")

    # 2. 重复平仓
    log_info("--- 测试点 2.2.3.2: 重复平仓 ---")
    for i in range(3):
        req = OrderRequest(
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
            direction=Direction.SHORT,
            type=OrderType.LIMIT,
            volume=1,
            price=config.SAFE_BUY_PRICE,
            offset=Offset.CLOSE,
            reference="RepeatClose"
        )
        engine.send_order(req)
    wait_for_reaction(2, "等待重复平仓反馈")

    # 3. 重复撤单 (构造一个存在的订单ID进行重复撤销)
    log_info("--- 测试点 2.2.3.3: 重复撤单 ---")
    # 先发一个单
    req_base = OrderRequest(
        symbol=engine.contract.symbol,
        exchange=engine.contract.exchange,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=1,
        price=config.SAFE_BUY_PRICE,
        offset=Offset.OPEN
    )
    vt_orderid = engine.send_order(req_base)
    wait_for_reaction(1)
    
    if vt_orderid:
        orderid = vt_orderid.split(".")[-1]
        req_c = CancelRequest(
            orderid=orderid,
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange
        )
        # 连续撤3次
        for i in range(3):
            engine.cancel_order(req_c)
        wait_for_reaction(2, "等待重复撤单反馈")

# =============================================================================
# 2.3 阈值管理
# =============================================================================

def test_2_3_1_threshold_alert(engine: TestEngine):
    """
    2.3.1 阈值设置及预警功能
    覆盖: 2.3.1.1~2.3.1.6
    """
    log_info("\n>>> [2.3.1] 阈值预警测试")
    
    # 1. 设置低阈值
    engine.risk_manager.set_thresholds(max_order=5, max_cancel=3, max_symbol_order=2)
    engine.risk_manager.reset_counters()
    
    # 2. 触发报单预警 (2.3.1.1, 2.3.1.2)
    log_info("--- 触发报单总数预警 (阈值=5) ---")
    for i in range(6):
        req = OrderRequest(
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=config.SAFE_BUY_PRICE,
            offset=Offset.OPEN
        )
        engine.send_order(req)
    wait_for_reaction(2, "检查是否出现黄色报单预警")

    # 3. 触发撤单预警 (2.3.1.3, 2.3.1.4)
    # 先清理订单
    active = engine.get_all_active_orders()
    log_info(f"--- 触发撤单总数预警 (阈值=3, 当前待撤={len(active)}) ---")
    count = 0
    for o in active:
        engine.cancel_order(o.create_cancel_request())
        count += 1
        if count >= 4: break # 超过3次
    wait_for_reaction(2, "检查是否出现黄色撤单预警")

    # 恢复默认
    engine.risk_manager.set_thresholds(max_order=100, max_cancel=100, max_symbol_order=100)
    log_info("测试结束，已恢复默认阈值")

# =============================================================================
# 2.4 错误防范
# =============================================================================

def test_2_4_1_order_check(engine: TestEngine):
    """
    2.4.1 交易指令检查
    覆盖: 2.4.1.1 代码错误, 2.4.1.2 价格错误, 2.4.1.3 数量超限
    """
    log_info("\n>>> [2.4.1] 指令检查测试")
    
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

    # 3. 数量超限
    log_info("--- 测试点 2.4.1.3: 委托数量超限 ---")
    if engine.contract:
        req_err_vol = OrderRequest(
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1000000,
            price=config.SAFE_BUY_PRICE,
            offset=Offset.OPEN
        )
        engine.send_order(req_err_vol)
    
    wait_for_reaction(2, "验证红色错误日志")

def test_2_4_2_error_prompt(engine: TestEngine):
    """
    2.4.2 错误提示功能
    覆盖: 2.4.2.1 资金不足, 2.4.2.2 持仓不足
    """
    log_info("\n>>> [2.4.2] 错误提示测试")
    if not engine.contract: return

    # 1. 资金不足 (绕过前端检查，假设前端没拦截或者阈值很大，这里直接发巨额单给CTP)
    # 为了测试CTP回报，我们需要临时禁用 RiskManager 的 check_order 里的数量检查吗？
    # 假设 RiskManager 没拦截 1000 手
    log_info("--- 测试点 2.4.2.1: 资金不足回报 ---")
    req_fund = OrderRequest(
        symbol=engine.contract.symbol,
        exchange=engine.contract.exchange,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=50000, # 足够大
        price=config.SAFE_BUY_PRICE,
        offset=Offset.OPEN
    )
    # 强制发送，绕过 risk manager (如果 risk manager 拦截的话)
    # 但我们现在的 send_order 必过 risk manager。
    # 只要 2.4.1.3 没拦截 50000，就能发出去。
    engine.send_order(req_fund)
    
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

# =============================================================================
# 2.5 应急处理
# =============================================================================

def test_2_5_1_pause_trading(engine: TestEngine):
    """
    2.5.1 暂停交易功能
    覆盖: 2.5.1.1 限制权限
    """
    log_info("\n>>> [2.5.1] 暂停交易测试")
    
    # 触发暂停
    engine.risk_manager.emergency_stop()
    
    # 尝试发单
    log_info("--- 尝试在暂停状态下发单 ---")
    if engine.contract:
        req = OrderRequest(
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=config.SAFE_BUY_PRICE,
            offset=Offset.OPEN
        )
        engine.send_order(req)
    
    wait_for_reaction(1, "验证被拦截")
    
    # 恢复交易权限（如果测试流程需要继续）并查询资金
    # 这里演示恢复后确认资金状态
    log_info("--- 恢复交易权限并确认状态 ---")
    engine.risk_manager.active = True
    gateway = engine.main_engine.get_gateway(engine.gateway_name)
    if gateway:
        gateway.query_account()
        wait_for_reaction(2)
        engine.log_current_account()

def test_2_5_2_batch_cancel(engine: TestEngine):
    """
    2.5.2 批量撤单功能
    覆盖: 2.5.2.1, 2.5.2.2
    """
    log_info("\n>>> [2.5.2] 批量撤单测试")
    
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
