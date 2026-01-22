import time
import traceback
from src import config
from src.logger import setup_logger, log_info, log_error
from src.core.engine import TestEngine
from src.utils import is_trading_time, wait_for_reaction
from src.tests import cases

def run_all_tests():
    # 1. 设置
    setup_logger()
    
    # 2. 时间检查
    if not is_trading_time():
        log_error("当前非交易时间，停止测试。")
        return

    engine = None
    try:
        log_info("=== 开始执行 CTP 穿透测试套件 ===")
        
        # 3. 初始化引擎
        engine = TestEngine()
        
        # 4. 连接
        cases.test_2_1_1_connectivity(engine)
        
        # 5. 等待合约
        cases.prepare_contract(engine)
        if not engine.contract:
            log_error("合约未就绪，中止测试。")
            return

        # 6. 订阅
        # Gateway usually auto-subscribes if we use vnpy's way, but let's be explicit if needed.
        # But wait, prepare_contract checks main_engine.get_all_contracts().
        # CTP gateway queries instruments on connect.
        # We need to subscribe market data to get quotes (optional for some tests but good for real simulation).
        # In comprehensive_ctp_test.py: gateway.subscribe(...)
        from vnpy.trader.object import SubscribeRequest
        engine.subscribe(SubscribeRequest(symbol=engine.contract.symbol, exchange=engine.contract.exchange))
        wait_for_reaction(msg="等待行情订阅")

        # 7. 运行测试用例
        
        # 2.1.2 基础交易
        cases.test_2_1_2_basic_trading(engine)
        
        # 2.2.3 重复报单 (在断开/暂停之前)
        cases.test_2_2_3_repeat_order(engine)
        
        # 2.4.1 订单检查
        cases.test_2_4_1_order_check(engine)
        
        # 2.4.2 错误提示
        cases.test_2_4_2_error_prompt(engine)
        
        # 2.2.1 断开连接 (这将关闭连接)
        cases.test_2_2_1_disconnection(engine)
        
        # After disconnect test, we reconnected. Ensure contract/sub is still valid?
        # Reconnect calls connect(). CTP usually requires re-subscribing?
        # VnPy gateway usually handles re-subscription on re-connect automatically if using SubscribeRequest?
        # Or we might need to wait again.
        wait_for_reaction(msg="等待重连稳定")
        
        # 2.5.2 批量撤单 (Requires active session)
        cases.test_2_5_2_batch_cancel(engine)
        
        # 2.5.1 暂停交易 (This disables risk manager)
        # Run this last as it stops trading.
        cases.test_2_5_1_pause_trading(engine)
        
        log_info("=== 所有测试执行完毕 ===")

    except Exception as e:
        log_error(f"测试套件崩溃: {e}")
        log_error(traceback.format_exc())
    finally:
        if engine:
            log_info("正在关闭引擎...")
            engine.close()

if __name__ == "__main__":
    run_all_tests()
