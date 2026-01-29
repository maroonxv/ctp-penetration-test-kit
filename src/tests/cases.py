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
    
    # 增加等待逻辑，防止合约信息尚未就绪
    if not engine.contract:
        for _ in range(10):
            log_info("等待合约信息同步...")
            wait_for_reaction(1)
            if engine.contract:
                break

    if not engine.contract:
        log_error(f"未获取到合约信息 ({config.TEST_SYMBOL})，跳过测试")
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
    log_info("\n>>> [2.2.1] 连接监测测试（软断线/软重连）")
    
    # 2.2.1.1 连接状态
    log_info("--- 测试点 2.2.1.1: 当前连接状态 ---")
    gateway = engine.main_engine.get_gateway(engine.gateway_name)
    if gateway:
        log_info("当前网关对象: 存在（真实连接状态以底层回调/日志为准）")
    else:
        log_error("当前网关对象: 不存在（可能未完成初始化或已被逻辑断开）")

    # 2.2.1.2 断线模拟
    log_info("--- 测试点 2.2.1.2: 模拟断线（逻辑断线） ---")
    engine.disconnect()

    log_info("已调用 disconnect（本工具采用逻辑断线：不物理 close，避免底层卡死）。")
    gateway = engine.main_engine.get_gateway(engine.gateway_name)
    if gateway:
        log_warning("断线后网关对象仍存在（与预期不符），后续以回调/日志为准。")
    else:
        log_info("断线后网关对象已移除（符合逻辑断线预期）。")

    log_info("等待 5 秒，观察断线/重连相关日志...")
    time.sleep(5)
    log_info("等待结束，准备发起重连（软重连）...")

    # 2.2.1.3 重连模拟
    log_info("--- 测试点 2.2.1.3: 模拟重连（逻辑重连） ---")
    
    # 强制重新连接
    try:
        engine.reconnect()
        # 等待连接成功
        wait_for_reaction(5, "等待重连日志 (OnFrontConnected)")
    except Exception as e:
        log_error(f"重连尝试失败: {e}")

    # 验证重连后状态
    # 重连后 gateway 对象可能发生变化（如果被重新创建），重新获取
    gateway = engine.main_engine.get_gateway(engine.gateway_name)
    if gateway:
        log_info("重连后网关对象: 存在（真实连接状态以底层回调/日志为准）")
    else:
        log_error("重连后网关对象: 不存在（重连未就绪）")
    
    # 重连后再次检查资金
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
    
    rm = engine.risk_manager
    thresholds = {}
    try:
        thresholds = rm.get_thresholds()
    except Exception:
        thresholds = {}

    max_order_count = int(thresholds.get("max_order_count", getattr(rm, "max_order_count", 0)) or 0)
    max_cancel_count = int(thresholds.get("max_cancel_count", getattr(rm, "max_cancel_count", 0)) or 0)
    max_repeat_count = int(thresholds.get("max_repeat_count", getattr(rm, "max_repeat_count", 0)) or 0)

    log_info(f"当前阈值: 报单={max_order_count}, 撤单={max_cancel_count}, 重复报单(选测)={max_repeat_count}")
    rm.reset_counters()

    if not engine.contract:
        log_error("未获取到合约信息，跳过阈值触发测试")
        return

    max_actions = 10
    sent_vt_orderids = []

    # 2.3.1.1 / 2.3.1.2
    if max_order_count > 0:
        send_n = min(max_actions, max_order_count + 1)
        log_info(f"--- 触发报单总数预警 (阈值={max_order_count}, 本次发单={send_n}) ---")
        for _ in range(send_n):
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
        wait_for_reaction(2, "检查是否出现报单阈值预警")
    else:
        log_warning("报单阈值未启用(<=0)，跳过 2.3.1.1/2.3.1.2")

    wait_for_reaction(10, "测试间隔等待 10 秒")

    # 2.3.1.3 / 2.3.1.4
    if max_cancel_count > 0:
        all_active = engine.get_all_active_orders()
        target_orders = [o for o in all_active if o.vt_orderid in sent_vt_orderids]
        
        need_cancel = min(max_actions, max_cancel_count + 1)
        log_info(f"--- 触发撤单总数预警 (阈值={max_cancel_count}, 计划撤单={need_cancel}, 目标待撤={len(target_orders)}) ---")
        count = 0
        for o in target_orders:
            engine.cancel_order(o.create_cancel_request())
            count += 1
            if count >= need_cancel:
                break
        wait_for_reaction(2, "检查是否出现撤单阈值预警")
    else:
        log_warning("撤单阈值未启用(<=0)，跳过 2.3.1.3/2.3.1.4")

    wait_for_reaction(10, "测试间隔等待 10 秒")

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
    wait_for_reaction(5, "等待 5 秒，查看是否出现错误日志")

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

    # 3. 数量超限
    log_info("--- 测试点 2.4.1.3: 委托数量超限 ---")
    if engine.contract:
        req_err_vol = OrderRequest(
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=10000,
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
        offset=Offset.OPEN,
        reference="FundTest"
    )
    # 强制发送，绕过 risk manager (如果 risk manager 拦截的话)
    # 但我们现在的 send_order 必过 risk manager。
    # 只要 2.4.1.3 没拦截 50000，就能发出去。
    engine.send_order(req_fund)
    wait_for_reaction(5, "等待 5 秒，查看是否出现错误日志")
    
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

# =============================================================================
# 2.5 应急处理
# =============================================================================

def test_2_5_1_pause_trading(engine: TestEngine):
    """
    2.5.1 暂停交易功能
    覆盖: 
    2.5.1.1 限制账号交易权限
    2.5.1.2 暂停策略执行
    2.5.1.3 强制账号退出
    """
    log_info("\n>>> [2.5.1] 暂停交易测试")
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

    # ==========================================
    # 2.5.1.2 暂停策略执行
    # ==========================================
    log_info("--- 测试点 2.5.1.2: 暂停策略执行 ---")
    import datetime
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    
    # 执行暂停
    engine.pause() # 调用 emergency_stop
    
    engine.send_order(req)
    wait_for_reaction(1, "验证暂停策略下被拦截")
    
    # 恢复
    engine.risk_manager.active = True
    log_info("已恢复策略执行")
    wait_for_reaction(2)

    # ==========================================
    # 2.5.1.3 强制账号退出
    # ==========================================
    log_info("--- 测试点 2.5.1.3: 强制账号退出 ---")
    log_info("说明: 该测试点将由外部编排器执行（模拟物理断线/进程终止）。")
    log_info("当前 Python 用例结束，等待 Web 控制端执行后续步骤...")

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
