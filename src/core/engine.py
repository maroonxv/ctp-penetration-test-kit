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
    渗透测试的核心引擎。
    集成：
    - VnPy 主引擎和网关
    - 风控管理器
    - RPC 命令服务器
    - 事件处理
    """
    def __init__(self):
        self.event_engine = EventEngine()
        self.main_engine = MainEngine(self.event_engine)
        self.main_engine.add_gateway(CtptestGateway)
        self.gateway_name = "CTPTEST"
        
        self.risk_manager = TestRiskManager(self)
        
        # 状态
        self.contract: Optional[ContractData] = None
        self.orders: Dict[str, OrderData] = {}
        self.last_account_data = None  # (balance, available)
        self.account: Optional[AccountData] = None # 缓存最新的账户信息
        self.session_order_ids = set() # 记录本次会话发出的订单ID
        
        # 事件钩子
        self.event_engine.register(EVENT_LOG, self.on_log)
        self.event_engine.register(EVENT_ORDER, self.on_order)
        self.event_engine.register(EVENT_TRADE, self.on_trade)
        self.event_engine.register(EVENT_CONTRACT, self.on_contract)
        self.event_engine.register(EVENT_ACCOUNT, self.on_account)

    def connect(self):
        log_info("正在连接 CTP 测试环境...")
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
                
                # 在风控管理器中注册订单以进行会话追踪
                self.risk_manager.register_order(vt_orderid)
                self.session_order_ids.add(vt_orderid)
                
                return vt_orderid
        else:
            log_warning("订单被风控管理器拒绝。")
        return ""

    def cancel_order(self, req: CancelRequest):
        if self.risk_manager.check_cancel(req):
            self.risk_manager.register_cancel_request(req)
            gateway = self.main_engine.get_gateway(self.gateway_name)
            if gateway:
                log_info(f"【撤单】Req Cancel OrderID: {req.orderid}")
                gateway.cancel_order(req)
        else:
            log_warning("撤单被风控管理器拒绝。")

    def subscribe(self, req: SubscribeRequest):
        gateway = self.main_engine.get_gateway(self.gateway_name)
        if gateway:
            gateway.subscribe(req)
            log_info(f"Subscribed to {req.symbol}")

    def on_log(self, event: Event):
        log: LogData = event.data
        # 我们将所有底层日志记录到我们的文件中
        # 如果 logger 已经处理了 stdout，则避免重复打印，
        # 但 vnpy 日志可能有助于清晰查看。
        # logger.py 处理格式化，所以我们只传递消息。
        # 检查是否为错误
        msg = f"[Gateway] {log.msg}"
        log_info(msg)

    def on_order(self, event: Event):
        order: OrderData = event.data
        self.orders[order.vt_orderid] = order
        
        # 仅当订单是本次会话产生的才打印日志
        if order.vt_orderid in self.session_order_ids:
            log_info(f"-> 收到委托回报: {order.vt_orderid} Status:{order.status.value}")
        
        if order.status == "AllTraded" or order.status == "PartTraded":
            pass # 在 trade 中处理
        
        # 更新风控管理器
        # 我们需要检测“已提交”（刚发送）与“已撤销”
        # 因为 on_order 会在状态变更时触发。
        # 我们只需将所有内容传递给风控管理器并让其过滤。
        # 但风控管理器期望每个订单只触发一次 "on_order_submitted"？
        # 简化：实际上风控管理器在 'send_order' 中计数提交（check_order 增加计数）。
        # 等等，check_order 在发送前增加计数。
        # 以前的代码有：
        # check_order -> count++
        # on_order_submitted -> 打印日志
        # on_order_cancelled -> count++ 并打印日志
        
        self.risk_manager.on_order_submitted(order) 
        if order.status.value == "已撤销" or order.status.value == "Cancelled":
             self.risk_manager.on_order_cancelled(order)

    def on_trade(self, event: Event):
        trade: TradeData = event.data
        vt_orderid = getattr(trade, "vt_orderid", "") or ""
        if not vt_orderid and getattr(trade, "orderid", None):
            vt_orderid = f"{self.gateway_name}.{trade.orderid}"

        if vt_orderid in self.session_order_ids:
            log_info(f"-> 收到成交回报: {vt_orderid} {trade.vt_tradeid} Price:{trade.price} Vol:{trade.volume}")

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
