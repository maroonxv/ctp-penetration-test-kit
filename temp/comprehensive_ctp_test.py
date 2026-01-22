import sys
import re
import time
import os
import threading
from collections import deque
from typing import Dict, List, Optional
from datetime import datetime, time as dtime

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

from vnpy.event import EventEngine, Event
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import EVENT_LOG, EVENT_CONTRACT, EVENT_ORDER, EVENT_TRADE, EVENT_POSITION, EVENT_ACCOUNT
from vnpy.trader.object import OrderRequest, CancelRequest, SubscribeRequest, ContractData, OrderData, TradeData, PositionData, AccountData, LogData
from vnpy.trader.constant import Exchange, OrderType, Direction, Offset, Status, Product
from vnpy_ctptest import CtptestGateway

# --- Configuration ---
TEST_SYMBOL = "IF2601"

# Market Price Reference: ~4649
SAFE_BUY_PRICE = 4000.0   # Buy Limit @ 4000 (Wait)
DEAL_BUY_PRICE = 4660.0   # Buy Limit @ 4660 (Deal)

RISK_LIMIT_ORDER_COUNT = 5
RISK_LIMIT_CANCEL_COUNT = 5
WAIT_SECONDS = 10
LOG_FILE_PATH = r"c:\Users\Administrator\Lai\haizheng_ctp_api_test\ctp_test_log.log"

class FileLogger:
    def __init__(self, filepath):
        self.filepath = filepath
        with open(self.filepath, 'a', encoding='utf-8') as f:
            f.write(f"\n=== Test Started at {datetime.now()} ===\n")
    
    def log(self, msg: str, also_print: bool = True):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        formatted_msg = f"[{timestamp}] {msg}"
        if also_print:
            print(formatted_msg)
        try:
            with open(self.filepath, 'a', encoding='utf-8') as f:
                f.write(formatted_msg + "\n")
        except Exception as e:
            print(f"Error writing to log file: {e}")

logger = FileLogger(LOG_FILE_PATH)

def print_log(msg: str):
    logger.log(msg, also_print=True)

def _now_cn() -> datetime:
    if ZoneInfo is None:
        return datetime.now()
    return datetime.now(ZoneInfo("Asia/Shanghai"))

def is_trading_time(now: Optional[datetime] = None) -> bool:
    if now is None:
        now = _now_cn()

    weekday = now.weekday()
    t = now.time()

    sessions = [
        (dtime(9, 0), dtime(10, 15)),
        (dtime(10, 30), dtime(11, 30)),
        (dtime(13, 0), dtime(15, 0)),
        (dtime(21, 0), dtime(23, 59, 59)),
        (dtime(0, 0), dtime(2, 30)),
    ]

    in_session = any(start <= t <= end for start, end in sessions)
    if not in_session:
        return False

    if t < dtime(3, 0):
        return weekday in (1, 2, 3, 4, 5)

    return weekday in (0, 1, 2, 3, 4)

class TestRiskManager:
    """
    模拟风控模块，用于满足【异常监测】和【阈值管理】的测试要求
    """
    def __init__(self, tester=None):
        self.order_count = 0
        self.cancel_count = 0
        self.active = True
        self.tester = tester
        
        self.max_order_count = RISK_LIMIT_ORDER_COUNT
        self.max_cancel_count = RISK_LIMIT_CANCEL_COUNT
        
        # New: Per-symbol tracking
        self.symbol_order_count = {} 
        self.max_symbol_order_count = 2  # Trigger on 3rd

    def check_order(self, req: OrderRequest) -> bool:
        if not self.active:
            print_log("【风控拦截】交易已暂停")
            return False
            
        if req.symbol == "INVALID_CODE":
            print_log(f"⚠️ 【交易指令检查】发现合约代码错误: {req.symbol}")
        
        if self.tester and self.tester.contract and req.symbol == self.tester.contract.symbol:
            tick = self.tester.contract.pricetick
            if tick > 0:
                remainder = req.price % tick
                if not (abs(remainder) < 1e-6 or abs(remainder - tick) < 1e-6):
                    print_log(f"⚠️ 【交易指令检查】委托价格({req.price})不符合最小变动价位({tick})")

        self.order_count += 1
        
        # Per-symbol check
        current_sym_count = self.symbol_order_count.get(req.symbol, 0) + 1
        self.symbol_order_count[req.symbol] = current_sym_count
        
        if current_sym_count > self.max_symbol_order_count:
             print_log(f"【风控预警】合约 {req.symbol} 报单过于频繁 (当前:{current_sym_count} > 阈值:{self.max_symbol_order_count})! 🚨")

        if self.order_count > self.max_order_count:
            print_log(f"【阈值预警】报单总数({self.order_count})超过阈值({self.max_order_count})! 🚨")
            return True 
        return True

    def check_cancel(self, req: CancelRequest) -> bool:
        if not self.active:
            print_log("【风控拦截】交易已暂停")
            return False
        return True

    def on_order_cancelled(self, order: OrderData) -> None:
        self.cancel_count += 1
        print_log(f"【监测】当前撤单总数: {self.cancel_count}")

        if self.cancel_count > self.max_cancel_count:
            print_log(f"【阈值预警】撤单总数({self.cancel_count})超过阈值({self.max_cancel_count})! 🚨")
            
    def on_order_submitted(self, order: OrderData) -> None:
        # 这里我们打印当前的 order_count (发单请求数)
        # 或者我们也可以维护一个 "submitted_ack_count"
        # 但为了简单且符合用户看到的数值，我们直接打印 order_count
        print_log(f"【监测】当前报单总数: {self.order_count}")
        
        if self.order_count > self.max_order_count:
            print_log(f"【阈值预警】报单总数({self.order_count})超过阈值({self.max_order_count})! 🚨")
    
    def emergency_stop(self):
        print_log("【应急处置】触发暂停交易功能！")
        self.active = False

class ComprehensiveTester:
    def __init__(self, main_engine: MainEngine, gateway_name: str):
        self.main_engine = main_engine
        self.gateway_name = gateway_name
        self.gateway = main_engine.get_gateway(gateway_name)
        self.risk_manager = TestRiskManager(self)

        self._log_lock = threading.Lock()
        self._recent_logs = deque(maxlen=500)
        self._counted_cancelled_orders = set()
        self._counted_submitted_orders = set() # 新增：用于记录已统计过报单数的订单
        
        # 记录脚本本次运行发出的所有订单ID，用于过滤外部订单
        self.my_order_ids = set()
        # 缓冲池：用于存储“抢跑”的回报（在send_order返回前就到达的回报）
        self.pending_order_events = {} # vt_orderid -> list of OrderData
        self.pending_trade_events = {} # vt_orderid -> list of TradeData

        self.contract: Optional[ContractData] = None
        self.orders: Dict[str, OrderData] = {}
        
        self.test_started = False
        
        self.main_engine.event_engine.register(EVENT_LOG, self.on_log)
        self.main_engine.event_engine.register(EVENT_CONTRACT, self.on_contract)
        self.main_engine.event_engine.register(EVENT_ORDER, self.on_order)
        self.main_engine.event_engine.register(EVENT_TRADE, self.on_trade)
        self.main_engine.event_engine.register(EVENT_POSITION, self.on_position)
        self.main_engine.event_engine.register(EVENT_ACCOUNT, self.on_account)

    def on_log(self, event: Event):
        log: LogData = event.data
        msg: str = log.msg
        with self._log_lock:
            self._recent_logs.append(msg)
        logger.log(msg, also_print=False)

    def _wait_for_log_match(self, regex: re.Pattern, timeout: float = 10.0) -> Optional[re.Match]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._log_lock:
                snapshot = list(self._recent_logs)
            for msg in reversed(snapshot):
                match = regex.search(msg)
                if match:
                    return match
            time.sleep(0.2)
        return None

    def _report_error_if_any(self, error_pattern: str, description: str, timeout: float = 10.0) -> None:
        pattern = re.compile(error_pattern)
        match = self._wait_for_log_match(pattern, timeout=timeout)
        if match:
            print_log(f"【验证成功】捕获到预期报错: {description}")
        else:
            print_log(f"【验证提醒】未在{timeout}秒内捕获到报错: {description}")

    def on_contract(self, event: Event):
        # We manually check contracts in run()
        pass

    def _process_order(self, order: OrderData):
        """实际处理订单回报的逻辑"""
        # 监测报单总数
        if order.vt_orderid not in self._counted_submitted_orders:
            self._counted_submitted_orders.add(order.vt_orderid)
            self.risk_manager.on_order_submitted(order)

        if order.status == Status.CANCELLED:
            if order.vt_orderid not in self._counted_cancelled_orders:
                self._counted_cancelled_orders.add(order.vt_orderid)
                self.risk_manager.on_order_cancelled(order)

        self.orders[order.vt_orderid] = order
        print_log(f"-> 收到委托回报: {order.vt_orderid} {order.direction.value} 状态:{order.status.value}")

    def on_order(self, event: Event):
        if not self.test_started:
            return
        order: OrderData = event.data

        # 过滤机制优化：处理多线程竞争条件
        if order.vt_orderid in self.my_order_ids:
            # 已知ID，直接处理
            self._process_order(order)
        else:
            # 未知ID，可能是抢跑的回报，先存入缓冲池
            if order.vt_orderid not in self.pending_order_events:
                self.pending_order_events[order.vt_orderid] = []
            self.pending_order_events[order.vt_orderid].append(order)

    def _process_trade(self, trade: TradeData):
        """实际处理成交回报的逻辑"""
        print_log(f"-> 收到成交回报: {trade.vt_tradeid} {trade.price} {trade.volume}")

    def on_trade(self, event: Event):
        if not self.test_started:
            return
        trade: TradeData = event.data
        
        if trade.vt_orderid in self.my_order_ids:
            self._process_trade(trade)
        else:
            if trade.vt_orderid not in self.pending_trade_events:
                self.pending_trade_events[trade.vt_orderid] = []
            self.pending_trade_events[trade.vt_orderid].append(trade)

    def on_position(self, event: Event):
        pass

    def on_account(self, event: Event):
        if not self.test_started:
            return
        account: AccountData = event.data
        print_log(f"-> 收到账户资金: 余额={account.balance} 可用={account.available}")

    def send_order(self, req: OrderRequest) -> str:
        if self.risk_manager.check_order(req):
            vt_orderid = self.gateway.send_order(req)
            if vt_orderid:
                self.my_order_ids.add(vt_orderid)  # 记录自己发出的订单ID
                print_log(f"【发单】{req.symbol} {req.direction.value} 价格:{req.price} -> ID:{vt_orderid}")
                
                # 检查是否有抢跑的回报
                if vt_orderid in self.pending_order_events:
                    for order in self.pending_order_events[vt_orderid]:
                        self._process_order(order)
                    del self.pending_order_events[vt_orderid]
                
                if vt_orderid in self.pending_trade_events:
                    for trade in self.pending_trade_events[vt_orderid]:
                        self._process_trade(trade)
                    del self.pending_trade_events[vt_orderid]
            else:
                print_log(f"【发单失败】接口返回空ID")
            return vt_orderid
        return ""

    def cancel_order(self, req: CancelRequest):
        if self.risk_manager.check_cancel(req):
            print_log(f"【撤单】请求撤单 OrderID: {req.orderid}")
            self.gateway.cancel_order(req)

    def run(self):
        print_log("\n=== 开始执行CptTest自动化测试 (目标: IF2601) ===\n")
        
        # 0. 初始查询账户资金
        print_log(">>> [0] 初始查询账户资金")
        self.gateway.query_account()
        time.sleep(3)

        # 1. Wait for contract
        print_log(f"正在等待合约 {TEST_SYMBOL} 加载...")
        target_contract = None
        
        # 尝试寻找指定合约
        for i in range(20):
            all_contracts = self.main_engine.get_all_contracts()
            for c in all_contracts:
                if c.symbol == TEST_SYMBOL:
                    target_contract = c
                    break
            if target_contract:
                break
            time.sleep(3)
            print_log(f"...等待合约加载 ({i+1}/20)")
            
        if not target_contract:
             print_log(f"❌ 错误：未找到目标合约 {TEST_SYMBOL}。退出测试。\n")
             return

        self.contract = target_contract
        print_log(f"成功锁定测试合约: {self.contract.vt_symbol}")
        
        # Subscribe
        self.gateway.subscribe(SubscribeRequest(symbol=self.contract.symbol, exchange=self.contract.exchange))
        print_log(f"已订阅行情")
        time.sleep(WAIT_SECONDS)
        
        self.test_started = True

        # --- Test Sequence ---

        # 1. Open Position (Buy Limit)
        print_log("\n>>> [1] 测试：开仓 (买入成交)")
        # Order A: Deal Price (~4660)
        print_log(f"   [1.A] 发送成交单 (价格 {DEAL_BUY_PRICE})")
        req_deal = OrderRequest(
            symbol=self.contract.symbol,
            exchange=self.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=DEAL_BUY_PRICE,
            offset=Offset.OPEN,
            reference="Deal"
        )
        self.send_order(req_deal)
        time.sleep(WAIT_SECONDS)

        # 2. Close Position (Sell Limit)
        print_log("\n>>> [2] 测试：平仓 (卖出成交)")
        print_log(f"   [2.A] 发送平仓单 (价格 {DEAL_BUY_PRICE})")
        req_close = OrderRequest(
            symbol=self.contract.symbol,
            exchange=self.contract.exchange,
            direction=Direction.SHORT,
            type=OrderType.LIMIT,
            volume=1,
            price=DEAL_BUY_PRICE,  # 使用相同价格平仓
            offset=Offset.CLOSE,
            reference="Close"
        )
        self.send_order(req_close)
        time.sleep(WAIT_SECONDS)

        # 3. Cancel Order (Send & Cancel)
        print_log("\n>>> [3] 测试：撤单 (发送4600单并撤销)")
        req_cancel_test = OrderRequest(
            symbol=self.contract.symbol,
            exchange=self.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=4600,
            offset=Offset.OPEN,
            reference="ToCancel"
        )
        vt_id_c = self.send_order(req_cancel_test)
        time.sleep(1)
        if vt_id_c:
             order_id_c = vt_id_c.split(".")[-1]
             req_c = CancelRequest(
                 orderid=order_id_c,
                 symbol=self.contract.symbol,
                 exchange=self.contract.exchange
             )
             self.cancel_order(req_c)
        time.sleep(WAIT_SECONDS)

        # 4. Repeat Orders (Trigger Specific Contract Alert)
        print_log("\n>>> [4] 测试：重复报单监测 (针对 IF2601 连续发3单)")
        # Send 3 orders to trigger limit
        for i in range(3):
            req_repeat = OrderRequest(
                symbol=self.contract.symbol,
                exchange=self.contract.exchange,
                direction=Direction.LONG,
                type=OrderType.LIMIT,
                volume=1,
                price=SAFE_BUY_PRICE,
                offset=Offset.OPEN,
                reference=f"Repeat{i}"
            )
            self.send_order(req_repeat)
            time.sleep(0.5)
        time.sleep(WAIT_SECONDS)

        # 5. Duplicate Cancel Test
        print_log("\n>>> [5] 测试：重复撤单 (对同一订单重复发送撤单请求)")
        req_dup_cancel = OrderRequest(
            symbol=self.contract.symbol,
            exchange=self.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=4600, # Safe price, won't fill
            offset=Offset.OPEN,
            reference="DupCancel"
        )
        vt_id_dup = self.send_order(req_dup_cancel)
        time.sleep(1)
        if vt_id_dup:
             order_id_dup = vt_id_dup.split(".")[-1]
             req_c_dup = CancelRequest(
                 orderid=order_id_dup,
                 symbol=self.contract.symbol,
                 exchange=self.contract.exchange
             )
             print_log(f"   [5.A] 第一次撤单: {order_id_dup}")
             self.cancel_order(req_c_dup)
             time.sleep(0.5)
             print_log(f"   [5.B] 第二次撤单 (预期被拒或忽略): {order_id_dup}")
             self.cancel_order(req_c_dup)
        time.sleep(WAIT_SECONDS)
        
        # 6. Invalid Symbol
        print_log("\n>>> [6] 测试：错误防范 (无效合约)")
        self.send_order(OrderRequest(
            symbol="INVALID",
            exchange=Exchange.SHFE, 
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=SAFE_BUY_PRICE,
            offset=Offset.OPEN,
            reference="ErrSym"
        ))
        time.sleep(WAIT_SECONDS)

        # 7. Invalid Price Tick
        print_log("\n>>> [7] 测试：错误防范 (无效价格Tick)")
        self.send_order(OrderRequest(
            symbol=self.contract.symbol,
            exchange=self.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=1,
            price=SAFE_BUY_PRICE + 0.12345, 
            offset=Offset.OPEN,
            reference="ErrTick"
        ))
        time.sleep(WAIT_SECONDS)

        # 8. Large Volume / Insufficient Funds
        print_log("\n>>> [8] 测试：资金不足/超限")
        self.send_order(OrderRequest(
            symbol=self.contract.symbol,
            exchange=self.contract.exchange,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=10000000, 
            price=SAFE_BUY_PRICE,
            offset=Offset.OPEN,
            reference="HugeVol"
        ))
        self._report_error_if_any(r"资金不足", "资金不足报错")
        time.sleep(WAIT_SECONDS)
        
        # 9. Emergency Stop (Commented out)
        # print_log("\n>>> [9] 测试：应急处置 (暂停交易)")
        # self.risk_manager.emergency_stop()
        # self.send_order(OrderRequest(
        #     symbol=self.contract.symbol,
        #     exchange=self.contract.exchange,
        #     direction=Direction.LONG,
        #     type=OrderType.LIMIT,
        #     volume=1,
        #     price=SAFE_BUY_PRICE,
        #     offset=Offset.OPEN,
        #     reference="Stop"
        # ))
        # time.sleep(WAIT_SECONDS)
        
        # Prepare for Cancel All: Send 2 active orders
        print_log("\n>>> [10前置] 发送两个挂单供批量撤单测试")
        for i in range(2):
            self.send_order(OrderRequest(
                symbol=self.contract.symbol,
                exchange=self.contract.exchange,
                direction=Direction.LONG,
                type=OrderType.LIMIT,
                volume=1,
                price=4600,
                offset=Offset.OPEN,
                reference=f"PreCancelAll_{i}"
            ))
            time.sleep(0.5)
        time.sleep(2)

        # 10. Cancel All Orders
        print_log("\n>>> [10] 测试：全部撤单 (批量撤销剩余活动订单)")
        active_orders = [o for o in self.orders.values() if o.is_active()]
        if active_orders:
            print_log(f"发现 {len(active_orders)} 个活动订单，开始撤销...")
            for order in active_orders:
                req_c = order.create_cancel_request()
                self.cancel_order(req_c)
                time.sleep(0.1)
        else:
            print_log("无活动订单可撤。")
        time.sleep(WAIT_SECONDS)

        print_log("\n=== 测试结束，请检查日志 ===")

def load_env(env_path: str) -> Dict[str, str]:
    env_vars = {}
    if not os.path.exists(env_path):
        return env_vars
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
    return env_vars

def main():
    now = _now_cn()
    if not is_trading_time(now):
        print_log(f"⚠️ 当前非交易时间({now.strftime('%Y-%m-%d %H:%M:%S %Z')})，退出脚本")
        return

    env_path = r"c:\Users\Administrator\Lai\haizheng_ctp_api_test\.env"
    env_vars = load_env(env_path)
    
    ctp_setting = {
        "用户名": env_vars.get("CTP_USERNAME", ""),
        "密码": env_vars.get("CTP_PASSWORD", ""),
        "经纪商代码": env_vars.get("CTP_BROKER_ID", ""),
        "交易服务器": env_vars.get("CTP_TD_SERVER", ""),
        "行情服务器": env_vars.get("CTP_MD_SERVER", ""),
        "产品名称": env_vars.get("APPID", ""),
        "授权编码": env_vars.get("CTP_AUTH_CODE", "")
    }

    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    main_engine.add_gateway(CtptestGateway)
    
    print_log("正在连接 CTP Test 环境...")
    main_engine.connect(ctp_setting, "CTPTEST")
    
    tester = ComprehensiveTester(main_engine, "CTPTEST")
    t = threading.Thread(target=tester.run)
    t.start()
    
    try:
        while t.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print_log("用户强制退出")
    finally:
        main_engine.close()

if __name__ == "__main__":
    main()
