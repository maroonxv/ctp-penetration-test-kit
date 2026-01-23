import threading
import time
from typing import Dict, Optional, List
from vnpy.event import EventEngine, Event
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import EVENT_LOG, EVENT_CONTRACT, EVENT_ORDER, EVENT_TRADE, EVENT_POSITION, EVENT_ACCOUNT
from vnpy.trader.object import OrderRequest, CancelRequest, SubscribeRequest, ContractData, OrderData, TradeData, LogData, AccountData
from vnpy_ctptest import CtptestGateway

from src import read_config as config
from src.logger import log_info, log_error, log_warning
from src.core.risk import TestRiskManager
from src.utils import wait_for_reaction

class TestEngine:
    """
    Core Engine for Penetration Test.
    Integrates:
    - VnPy MainEngine & Gateway
    - Risk Manager
    - RPC Command Server
    - Event Handling
    """
    def __init__(self):
        self.event_engine = EventEngine()
        self.main_engine = MainEngine(self.event_engine)
        self.main_engine.add_gateway(CtptestGateway)
        self.gateway_name = "CTPTEST"
        
        self.risk_manager = TestRiskManager(self)
        
        # State
        self.contract: Optional[ContractData] = None
        self.orders: Dict[str, OrderData] = {}
        self.last_account_data = None  # (balance, available)
        self.account: Optional[AccountData] = None # 缓存最新的账户信息
        self.session_order_ids = set() # 记录本次会话发出的订单ID
        
        # Event Hooks
        self.event_engine.register(EVENT_LOG, self.on_log)
        self.event_engine.register(EVENT_ORDER, self.on_order)
        self.event_engine.register(EVENT_TRADE, self.on_trade)
        self.event_engine.register(EVENT_CONTRACT, self.on_contract)
        self.event_engine.register(EVENT_ACCOUNT, self.on_account)

    def connect(self):
        log_info("Connecting to CTP Test Environment...")
        # 确保网关实例存在
        gateway = self.main_engine.get_gateway(self.gateway_name)
        if not gateway:
            log_info("Initializing CtptestGateway...")
            self.main_engine.add_gateway(CtptestGateway)
            
        self.main_engine.connect(config.CTP_SETTING, self.gateway_name)

    def disconnect(self):
        log_info("正在执行断线操作 (DISCONNECT)...")
        # 警告：经排查，调用 gateway.close() 会导致底层 CTP API 锁死 Python 进程
        # 导致 Flask Web 服务无法响应。
        # 因此，这里采取“逻辑断线”策略：
        # 1. 不调用 close()，任由旧连接在后台（可能泄露，但测试场景可接受）
        # 2. 直接从引擎移除网关引用
        
        if self.gateway_name in self.main_engine.gateways:
            self.main_engine.gateways.pop(self.gateway_name)
            log_info("网关实例已从引擎逻辑移除 (跳过物理关闭以防卡死)。")
        else:
            log_info("网关实例不在引擎中，无需移除。")

        # 立即返回，确保 Web 服务存活
        log_info("断线操作已完成 (逻辑层)。")

    def reconnect(self):
        log_info("正在执行重连操作 (RECONNECT)...")
        # 强制垃圾回收 (尝试性)
        import gc
        gc.collect()
        
        # 重新连接 (会自动触发 connect 中的 add_gateway)
        self.connect()

    def pause(self):
        log_info("正在执行暂停交易操作 (PAUSE)...")
        self.risk_manager.emergency_stop()

    def send_order(self, req: OrderRequest) -> str:
        if self.risk_manager.check_order(req):
            gateway = self.main_engine.get_gateway(self.gateway_name)
            if gateway:
                vt_orderid = gateway.send_order(req)
                log_info(f"【发单】{req.symbol} {req.direction.value} Price:{req.price} -> ID:{vt_orderid}")
                
                # Register order in Risk Manager for session tracking
                self.risk_manager.register_order(vt_orderid)
                self.session_order_ids.add(vt_orderid)
                
                return vt_orderid
        else:
            log_warning("Order rejected by Risk Manager.")
        return ""

    def cancel_order(self, req: CancelRequest):
        if self.risk_manager.check_cancel(req):
            gateway = self.main_engine.get_gateway(self.gateway_name)
            if gateway:
                log_info(f"【撤单】Req Cancel OrderID: {req.orderid}")
                gateway.cancel_order(req)
        else:
            log_warning("Cancel rejected by Risk Manager.")

    def subscribe(self, req: SubscribeRequest):
        gateway = self.main_engine.get_gateway(self.gateway_name)
        if gateway:
            gateway.subscribe(req)
            log_info(f"Subscribed to {req.symbol}")

    def on_log(self, event: Event):
        log: LogData = event.data
        # We log all underlying logs to our file
        # Avoid duplicate printing if logger already handles stdout, 
        # but vnpy log might be useful to see clearly.
        # logger.py handles formatting, so we just pass msg.
        # Check if it's error
        msg = f"[Gateway] {log.msg}"
        log_info(msg)

    def on_order(self, event: Event):
        order: OrderData = event.data
        self.orders[order.vt_orderid] = order
        
        # 仅当订单是本次会话产生的才打印日志
        if order.vt_orderid in self.session_order_ids:
            log_info(f"-> 收到委托回报: {order.vt_orderid} Status:{order.status.value}")
        
        if order.status == "AllTraded" or order.status == "PartTraded":
            pass # handled in trade
        
        # Update Risk Manager
        # We need to detect "Submitted" (just sent) vs "Cancelled"
        # Since on_order is fired for status changes.
        # We'll just pass everything to risk manager and let it filter.
        # But risk manager expects "on_order_submitted" only once per order?
        # Simplified: Risk manager counts submitted in 'send_order' actually (check_order adds count).
        # Wait, check_order adds count BEFORE send. 
        # The previous code had:
        # check_order -> count++
        # on_order_submitted -> print log
        # on_order_cancelled -> count++ and print log
        
        self.risk_manager.on_order_submitted(order) 
        if order.status.value == "已撤销" or order.status.value == "Cancelled":
             self.risk_manager.on_order_cancelled(order)

    def on_trade(self, event: Event):
        trade: TradeData = event.data
        log_info(f"-> 收到成交回报: {trade.vt_tradeid} Price:{trade.price} Vol:{trade.volume}")

    def on_contract(self, event: Event):
        contract: ContractData = event.data
        # 仅处理测试目标合约
        if contract.symbol == config.TEST_SYMBOL:
            self.contract = contract
            log_info(f"Contract found: {contract.vt_symbol}")
        # 其他合约静默处理，避免日志刷屏

    def on_account(self, event: Event):
        # 仅缓存数据，不再自动打印日志
        self.account = event.data

    def log_current_account(self):
        """主动打印当前账户资金"""
        if self.account:
             log_info(f"-> 账户资金: 余额={self.account.balance} 可用={self.account.available}")
        else:
             log_info("-> 尚未获取到账户资金信息")

    def get_all_active_orders(self) -> List[OrderData]:
        return [o for o in self.orders.values() if o.is_active()]

    def close(self):
        self.main_engine.close()
