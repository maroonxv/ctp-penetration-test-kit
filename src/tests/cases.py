import time
import subprocess
import sys
import os
from vnpy.trader.object import OrderRequest, CancelRequest, SubscribeRequest
from vnpy.trader.constant import Direction, OrderType, Offset, Exchange

from src import config
from src.core.engine import TestEngine
from src.utils import wait_for_reaction
from src.logger import log_info, log_error

# Helper to run control script
def run_control_script(command: str):
    script_path = os.path.join(config.PROJECT_ROOT, "scripts", "control.py")
    python_exe = sys.executable
    log_info(f"Executing external control: {command}")
    try:
        subprocess.run([python_exe, script_path, command], check=True)
    except subprocess.CalledProcessError as e:
        log_error(f"Failed to execute control script: {e}")

def prepare_contract(engine: TestEngine):
    """Wait for contract to be available"""
    log_info("Waiting for contract information...")
    for i in range(10):
        if engine.contract:
            return
        time.sleep(2)
    log_error("Timeout waiting for contract!")

def test_2_1_1_connectivity(engine: TestEngine):
    log_info("\n>>> [Test 2.1.1] 连通性测试")
    engine.connect()
    wait_for_reaction(msg="Waiting for connection and login")
    # Verification is done via log inspection manually as per requirement, 
    # but we can assume success if no crash.

def test_2_1_2_basic_trading(engine: TestEngine):
    log_info("\n>>> [Test 2.1.2] 基础交易功能测试 (开仓/平仓/撤单)")
    if not engine.contract:
        log_error("No contract, skip trading test.")
        return

    # 1. Open
    req_open = OrderRequest(
        symbol=engine.contract.symbol,
        exchange=engine.contract.exchange,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=1,
        price=config.DEAL_BUY_PRICE,
        offset=Offset.OPEN,
        reference="Open"
    )
    engine.send_order(req_open)
    wait_for_reaction(msg="Wait for Open Deal")

    # 2. Close
    req_close = OrderRequest(
        symbol=engine.contract.symbol,
        exchange=engine.contract.exchange,
        direction=Direction.SHORT,
        type=OrderType.LIMIT,
        volume=1,
        price=config.DEAL_BUY_PRICE,
        offset=Offset.CLOSE,
        reference="Close"
    )
    engine.send_order(req_close)
    wait_for_reaction(msg="Wait for Close Deal")

    # 3. Cancel Test (Send order far away)
    req_cancel = OrderRequest(
        symbol=engine.contract.symbol,
        exchange=engine.contract.exchange,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=1,
        price=config.SAFE_BUY_PRICE, # 4000
        offset=Offset.OPEN,
        reference="ToCancel"
    )
    vt_orderid = engine.send_order(req_cancel)
    wait_for_reaction(msg="Wait for Order Inserted before Cancel")
    
    if vt_orderid:
        # Extract ID
        orderid = vt_orderid.split(".")[-1]
        req_c = CancelRequest(
            orderid=orderid,
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange
        )
        engine.cancel_order(req_c)
        wait_for_reaction(msg="Wait for Cancel confirmation")

def test_2_2_1_disconnection(engine: TestEngine):
    log_info("\n>>> [Test 2.2.1] 系统连接异常监测功能 (断线重连)")
    
    # Disconnect
    run_control_script("DISCONNECT")
    wait_for_reaction(msg="Wait for Disconnect Log")
    
    # Reconnect
    run_control_script("RECONNECT")
    wait_for_reaction(msg="Wait for Reconnect Log")

def test_2_2_3_repeat_order(engine: TestEngine):
    log_info("\n>>> [Test 2.2.3] 重复报单监测功能 (连续发3单)")
    if not engine.contract: return

    for i in range(3):
        req = OrderRequest(
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=config.SAFE_BUY_PRICE,
            offset=Offset.OPEN,
            reference=f"Repeat{i}"
        )
        engine.send_order(req)
        wait_for_reaction(msg=f"Wait for Repeat Order {i+1}")

def test_2_4_1_order_check(engine: TestEngine):
    log_info("\n>>> [Test 2.4.1] 交易指令检查功能 (错误合约/价格)")
    
    # 1. Invalid Symbol
    req_inv_sym = OrderRequest(
        symbol="INVALID_CODE",
        exchange=Exchange.SHFE,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=1,
        price=4000,
        offset=Offset.OPEN
    )
    engine.send_order(req_inv_sym)
    wait_for_reaction(msg="Wait for Invalid Symbol Check")
    
    # 2. Invalid Price Tick
    if engine.contract:
        req_inv_tick = OrderRequest(
            symbol=engine.contract.symbol,
            exchange=engine.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=config.SAFE_BUY_PRICE + 0.12345,
            offset=Offset.OPEN
        )
        engine.send_order(req_inv_tick)
        wait_for_reaction(msg="Wait for Invalid Tick Check")

def test_2_4_2_error_prompt(engine: TestEngine):
    log_info("\n>>> [Test 2.4.2] 错误提示功能 (资金不足/超限)")
    if not engine.contract: return
    
    req_huge = OrderRequest(
        symbol=engine.contract.symbol,
        exchange=engine.contract.exchange,
        direction=Direction.LONG,
        type=OrderType.LIMIT,
        volume=1000000, # Huge
        price=config.SAFE_BUY_PRICE,
        offset=Offset.OPEN
    )
    engine.send_order(req_huge)
    wait_for_reaction(msg="Wait for Insufficient Funds Error")

def test_2_5_1_pause_trading(engine: TestEngine):
    log_info("\n>>> [Test 2.5.1] 暂停交易功能 (应急处置)")
    
    # Pause
    run_control_script("PAUSE")
    wait_for_reaction(msg="Wait for Pause State")
    
    # Try send order
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
        wait_for_reaction(msg="Wait for Pause Interception Log")

def test_2_5_2_batch_cancel(engine: TestEngine):
    log_info("\n>>> [Test 2.5.2] 批量撤单功能 (需先重启或恢复状态)")
    # Note: Previous test paused trading. 
    # If we want to test batch cancel, we need to resume or rely on restart.
    # Since our architecture doesn't have RESUME command implemented in RiskManager explicitly 
    # (only emergency_stop sets active=False), we might need to restart process or add resume.
    # For now, let's assume this test runs before pause or we add resume.
    # Actually, the requirement document puts Emergency Stop at 2.5.1 and Batch Cancel at 2.5.2.
    # To run 2.5.2, we need active state. 
    # Quick fix: Manually set active=True in this test function (backdoor) or implement RESUME.
    
    engine.risk_manager.active = True # Force resume for testing
    log_info("Force resumed trading for Batch Cancel test.")
    
    if not engine.contract: return
    
    # Send 2 orders
    for i in range(2):
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
        wait_for_reaction(msg=f"Send Batch Order {i}")
        
    # Cancel All
    active_orders = engine.get_all_active_orders()
    log_info(f"Found {len(active_orders)} active orders to cancel.")
    for order in active_orders:
        req = order.create_cancel_request()
        engine.cancel_order(req)
        # Wait for each cancel? Or batch then wait?
        # Requirement says "Atomic operation sleep 7s". 
        # So sleep after each cancel.
        wait_for_reaction(msg=f"Wait for Cancel {order.vt_orderid}")
