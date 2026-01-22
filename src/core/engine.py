import threading
import time
from typing import Dict, Optional, List
from vnpy.event import EventEngine, Event
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import EVENT_LOG, EVENT_CONTRACT, EVENT_ORDER, EVENT_TRADE, EVENT_POSITION, EVENT_ACCOUNT
from vnpy.trader.object import OrderRequest, CancelRequest, SubscribeRequest, ContractData, OrderData, TradeData, LogData
from vnpy_ctptest import CtptestGateway

from src import config
from src.logger import log_info, log_error, log_warning
from src.core.risk import TestRiskManager
from src.core.server import CommandServer
from src.utils import wait_for_reaction

class TestEngine:
    """
    穿透测试核心引擎。
    集成:
    - VnPy 主引擎 & 网关
    - 风控管理器
    - RPC 指令服务器
    - 事件处理
    """
    def __init__(self):
        self.event_engine = EventEngine()
        self.main_engine = MainEngine(self.event_engine)
        self.main_engine.add_gateway(CtptestGateway)
        self.gateway_name = "CTPTEST"
        
        self.risk_manager = TestRiskManager(self)
        self.command_server = CommandServer(self)
        
        # 状态
        self.contract: Optional[ContractData] = None
        self.orders: Dict[str, OrderData] = {}
        
        # 事件钩子
        self.event_engine.register(EVENT_LOG, self.on_log)
        self.event_engine.register(EVENT_ORDER, self.on_order)
        self.event_engine.register(EVENT_TRADE, self.on_trade)
        self.event_engine.register(EVENT_CONTRACT, self.on_contract)
        
        # 启动服务器
        self.command_server.start()

    def connect(self):
        log_info("正在连接到 CTP 测试环境...")
        self.main_engine.connect(config.CTP_SETTING, self.gateway_name)
        # 我们在测试用例中依赖外部等待，但初始连接比较特殊。
        # 但为了保持一致，我们让运行器处理等待。

    def disconnect(self):
        log_info("正在执行断开连接指令...")
        gateway = self.main_engine.get_gateway(self.gateway_name)
        if gateway:
            gateway.close()
            log_info("网关已关闭。")

    def reconnect(self):
        log_info("正在执行重新连接指令...")
        # 重新连接通常意味着在关闭后再次调用连接
        self.connect()

    def pause(self):
        log_info("正在执行暂停指令...")
        self.risk_manager.emergency_stop()

    def send_order(self, req: OrderRequest) -> str:
        if self.risk_manager.check_order(req):
            gateway = self.main_engine.get_gateway(self.gateway_name)
            if gateway:
                vt_orderid = gateway.send_order(req)
                log_info(f"【发单】{req.symbol} {req.direction.value} Price:{req.price} -> ID:{vt_orderid}")
                return vt_orderid
        else:
            log_warning("订单被风控模块拒绝。")
        return ""

    def cancel_order(self, req: CancelRequest):
        if self.risk_manager.check_cancel(req):
            gateway = self.main_engine.get_gateway(self.gateway_name)
            if gateway:
                log_info(f"【撤单】Req Cancel OrderID: {req.orderid}")
                gateway.cancel_order(req)
        else:
            log_warning("撤单请求被风控模块拒绝。")

    def subscribe(self, req: SubscribeRequest):
        gateway = self.main_engine.get_gateway(self.gateway_name)
        if gateway:
            gateway.subscribe(req)
            log_info(f"已订阅行情: {req.symbol}")

    def on_log(self, event: Event):
        log: LogData = event.data
        # 我们将所有底层日志记录到我们的文件中
        # 避免在日志器已经处理 stdout 时重复打印，
        # 但 vnpy 日志可能有助于清晰查看。
        # logger.py 处理格式化，所以我们只传递 msg。
        # 检查是否为错误
        msg = f"[Gateway] {log.msg}"
        log_info(msg)

    def on_order(self, event: Event):
        order: OrderData = event.data
        self.orders[order.vt_orderid] = order
        log_info(f"-> 收到委托回报: {order.vt_orderid} Status:{order.status.value}")
        
        if order.status == "AllTraded" or order.status == "PartTraded":
            pass # 在 trade 中处理
        
        # 更新风控管理器
        # 我们需要检测 "Submitted" (刚刚发送) vs "Cancelled"
        # 因为 on_order 在状态变化时触发。
        # 我们只需将所有内容传递给风控管理器，让其进行过滤。
        # 但风控管理器期望每个订单只有一次 "on_order_submitted"？
        # 简化：风控管理器实际上在 'send_order' 中计数 (check_order 增加计数)。
        # 等等，check_order 在发送之前增加计数。
        # 之前的代码有：
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
        if contract.symbol == config.TEST_SYMBOL:
            self.contract = contract
            log_info(f"发现合约: {contract.vt_symbol}")

    def get_all_active_orders(self) -> List[OrderData]:
        return [o for o in self.orders.values() if o.is_active()]

    def close(self):
        self.command_server.stop()
        self.main_engine.close()
