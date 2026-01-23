import time
import traceback
from src import read_config as config
from src.logger import setup_logger, log_info, log_error
from src.core.engine import TestEngine
from src.utils import is_trading_time, wait_for_reaction
from src.tests import cases

def run_all_tests():
    # 1. Setup
    setup_logger()
    
    # 2. Time Check
    if not is_trading_time():
        log_error("当前非交易时间，停止测试。")
        return

    engine = None
    try:
        log_info("=== Starting CTP Penetration Test Suite ===")
        
        # 3. Init Engine
        engine = TestEngine()
        
        # 4. Connect
        cases.test_2_1_1_connectivity(engine)
        
        # 5. Wait for Contract
        cases.prepare_contract(engine)
        if not engine.contract:
            log_error("Contract not ready, aborting tests.")
            return

        # 6. Subscribe
        # Gateway usually auto-subscribes if we use vnpy's way, but let's be explicit if needed.
        # But wait, prepare_contract checks main_engine.get_all_contracts().
        # CTP gateway queries instruments on connect.
        # We need to subscribe market data to get quotes (optional for some tests but good for real simulation).
        # In comprehensive_ctp_test.py: gateway.subscribe(...)
        from vnpy.trader.object import SubscribeRequest
        engine.subscribe(SubscribeRequest(symbol=engine.contract.symbol, exchange=engine.contract.exchange))
        wait_for_reaction(msg="Wait for Market Data Subscription")

        # 7. Run Test Cases
        
        # 2.1.2 Basic Trading
        cases.test_2_1_2_basic_trading(engine)
        
        # 2.2.3 Repeat Order (before disconnect/pause)
        cases.test_2_2_3_repeat_order(engine)
        
        # 2.4.1 Order Check
        cases.test_2_4_1_order_check(engine)
        
        # 2.4.2 Error Prompt
        cases.test_2_4_2_error_prompt(engine)
        
        # 2.2.1 Disconnect (This will close connection)
        cases.test_2_2_1_disconnection(engine)
        
        # After disconnect test, we reconnected. Ensure contract/sub is still valid?
        # Reconnect calls connect(). CTP usually requires re-subscribing?
        # VnPy gateway usually handles re-subscription on re-connect automatically if using SubscribeRequest?
        # Or we might need to wait again.
        wait_for_reaction(msg="Stabilizing after reconnect")
        
        # 2.5.2 Batch Cancel (Requires active session)
        cases.test_2_5_2_batch_cancel(engine)
        
        # 2.5.1 Pause Trading (This disables risk manager)
        # Run this last as it stops trading.
        cases.test_2_5_1_pause_trading(engine)
        
        log_info("=== All Tests Completed ===")

    except Exception as e:
        log_error(f"Test Suite Crashed: {e}")
        log_error(traceback.format_exc())
    finally:
        if engine:
            log_info("Closing Engine...")
            engine.close()

if __name__ == "__main__":
    run_all_tests()
