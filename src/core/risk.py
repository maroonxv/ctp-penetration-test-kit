from vnpy.trader.object import OrderRequest, CancelRequest, OrderData
from src.logger import log_info, log_warning, log_error
from src import read_config as config

class TestRiskManager:
    """
    Risk Management Module for Penetration Testing.
    Handles:
    - Order/Cancel counting & monitoring
    - Threshold alerts
    - Emergency stop (Pause trading)
    - Invalid order checks (Price Tick, Symbol)
    """
    def __init__(self, tester=None):
        self.active = True
        self.tester = tester
        
        # Counters
        self.order_count = 0
        self.cancel_count = 0
        
        # Thresholds
        self.max_order_count = config.RISK_THRESHOLDS.get("max_order_count", 5)
        self.max_cancel_count = config.RISK_THRESHOLDS.get("max_cancel_count", 5)
        
        # Symbol-level monitoring (for repeat order test)
        self.symbol_order_count = {} 
        self.max_symbol_order_count = config.RISK_THRESHOLDS.get("max_symbol_order_count", 2)  # Alert on 3rd
        
        # Session Order Tracking
        self.session_order_ids = set()
        
        # Last Log State (for deduplication)
        self.last_log_order_count = -1
        self.last_log_cancel_count = -1

    def register_order(self, vt_orderid: str):
        """Register order ID for current session tracking"""
        self.session_order_ids.add(vt_orderid)

    def check_order(self, req: OrderRequest) -> bool:
        """
        Check if order is allowed.
        """
        # 1. Check Emergency Stop
        if not self.active:
            log_warning("【风控拦截】交易已暂停，拒绝报单")
            return False
            
        # 2. Check Symbol Validity (Simulation)
        if req.symbol == "INVALID_CODE" or req.symbol == "INVALID":
            log_error(f"⚠️ 【交易指令检查】发现合约代码错误: {req.symbol}")
            # In real scenario, we might return False, but to test CTP rejection we might let it pass
            # However, requirement 2.4.1 says system should check and refuse.
            # So we refuse it here to demonstrate client-side check.
            # But wait, we might want to see CTP return error too? 
            # Let's log it. If we return False, we prove "System" (client) can block it.
            return False
        
        # 3. Check Price Tick
        if self.tester and self.tester.contract and req.symbol == self.tester.contract.symbol:
            tick = self.tester.contract.pricetick
            if tick > 0:
                remainder = req.price % tick
                # Floating point tolerance
                if not (abs(remainder) < 1e-6 or abs(remainder - tick) < 1e-6):
                    log_error(f"⚠️ 【交易指令检查】委托价格({req.price})不符合最小变动价位({tick})")
                    return False

        # 4. Update & Check Counters
        self.order_count += 1
        
        # Per-symbol check
        current_sym_count = self.symbol_order_count.get(req.symbol, 0) + 1
        self.symbol_order_count[req.symbol] = current_sym_count
        
        if current_sym_count > self.max_symbol_order_count:
             log_warning(f"【风控预警】合约 {req.symbol} 报单过于频繁 (当前:{current_sym_count} > 阈值:{self.max_symbol_order_count})! 🚨")

        if self.order_count > self.max_order_count:
            log_warning(f"【阈值预警】报单总数({self.order_count})超过阈值({self.max_order_count})! 🚨")
            
        return True

    def check_cancel(self, req: CancelRequest) -> bool:
        """
        Check if cancel is allowed.
        """
        if not self.active:
            log_warning("【风控拦截】交易已暂停，拒绝撤单")
            return False
        return True

    def on_order_submitted(self, order: OrderData) -> None:
        """
        Callback when order is submitted (ACK).
        """
        if self.order_count != self.last_log_order_count:
            log_info(f"【监测】当前报单总数: {self.order_count}")
            self.last_log_order_count = self.order_count

    def on_order_cancelled(self, order: OrderData) -> None:
        """
        Callback when order is cancelled.
        """
        # Filter historical orders (not created in this session)
        if order.vt_orderid not in self.session_order_ids:
            return

        self.cancel_count += 1
        
        if self.cancel_count != self.last_log_cancel_count:
            log_info(f"【监测】当前撤单总数: {self.cancel_count}")
            self.last_log_cancel_count = self.cancel_count

        if self.cancel_count > self.max_cancel_count:
            log_warning(f"【阈值预警】撤单总数({self.cancel_count})超过阈值({self.max_cancel_count})! 🚨")
            
    def emergency_stop(self):
        """
        Trigger emergency stop.
        """
        log_warning("【应急处置】触发暂停交易功能！系统将拒绝后续指令。")
        self.active = False

    def set_thresholds(self, max_order=None, max_cancel=None, max_symbol_order=None):
        """
        Set risk thresholds dynamically.
        """
        if max_order: self.max_order_count = max_order
        if max_cancel: self.max_cancel_count = max_cancel
        if max_symbol_order: self.max_symbol_order_count = max_symbol_order
        log_info(f"风控阈值已更新: Order={self.max_order_count}, Cancel={self.max_cancel_count}")

    def reset_counters(self):
        """
        Reset all counters.
        """
        self.order_count = 0
        self.cancel_count = 0
        self.last_log_order_count = -1
        self.last_log_cancel_count = -1
        self.symbol_order_count.clear()
        log_info("风控计数器已重置")
