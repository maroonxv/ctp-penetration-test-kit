from vnpy.trader.object import OrderRequest, CancelRequest, OrderData
from src.logger import log_info, log_warning, log_error
from src import read_config as config
 
class TestRiskManager:
    """
    渗透测试的风控模块。
    处理：
    - 订单/撤单计数与监测
    - 阈值预警
    - 紧急停止（暂停交易）
    - 无效订单检查（价格 Tick、合约代码）
    """
    def __init__(self, tester=None):
        self.active = True
        self.tester = tester
        
        # 计数器
        self.order_count = 0
        self.cancel_count = 0
        self.repeat_order_count = 0
        self.repeat_cancel_count = 0
        
        # 阈值
        self.max_order_count = config.RISK_THRESHOLDS.get("max_order_count", 5)
        self.max_cancel_count = config.RISK_THRESHOLDS.get("max_cancel_count", 5)
        self.max_repeat_count = config.RISK_THRESHOLDS.get(
            "max_repeat_count",
            config.RISK_THRESHOLDS.get("max_symbol_order_count", 0),
        )
        
        self.order_signature_count = {}
        self.cancel_signature_count = {}
        
        # 会话订单追踪
        self.session_order_ids = set()
        
        # 上一次日志状态（用于去重）
        self.last_log_order_count = -1
        self.last_log_cancel_count = -1
        self._warned_order_threshold = False
        self._warned_cancel_threshold = False
        self._warned_repeat_threshold = False

    def register_order(self, vt_orderid: str):
        """注册当前会话追踪的订单 ID"""
        self.session_order_ids.add(vt_orderid)

    def register_cancel_request(self, req: CancelRequest) -> None:
        sig = (
            str(getattr(req, "orderid", "") or ""),
            str(getattr(req, "symbol", "") or ""),
            str(getattr(req, "exchange", "") or ""),
        )
        current = int(self.cancel_signature_count.get(sig, 0)) + 1
        self.cancel_signature_count[sig] = current
        if current >= 2:
            self.repeat_cancel_count += 1
            self._check_repeat_threshold()

    def _order_signature(self, req: OrderRequest) -> tuple:
        direction = getattr(req, "direction", None)
        offset = getattr(req, "offset", None)
        order_type = getattr(req, "type", None)
        return (
            str(getattr(req, "symbol", "") or ""),
            str(getattr(direction, "value", direction)),
            str(getattr(offset, "value", offset)),
            str(getattr(order_type, "value", order_type)),
            float(getattr(req, "volume", 0) or 0),
            round(float(getattr(req, "price", 0) or 0), 10),
        )

    def _repeat_total(self) -> int:
        return int(self.repeat_order_count) + int(self.repeat_cancel_count)

    def _check_repeat_threshold(self) -> None:
        if self._warned_repeat_threshold:
            return
        threshold = int(self.max_repeat_count or 0)
        if threshold <= 0:
            return
        current = self._repeat_total()
        if current >= threshold:
            log_warning(f"【阈值预警】重复报单统计({current})达到或超过阈值({threshold})! 🚨")
            self._warned_repeat_threshold = True

    def check_order(self, req: OrderRequest) -> bool:
        """
        检查订单是否允许。
        """
        # 1. 检查紧急停止
        if not self.active:
            log_warning("【风控拦截】交易已暂停，拒绝报单")
            return False
            
        # 2. 检查合约代码有效性（模拟）
        if req.symbol == "INVALID_CODE" or req.symbol == "INVALID":
            log_error(f"⚠️ 【交易指令检查】发现合约代码错误: {req.symbol}")
            return False

        # 2.5 检查委托数量
        if req.volume >= 10000 and req.reference != "FundTest":
            log_error(f"⚠️ 【交易指令检查】发现数量错误: 不合法的数量")
            return False
        
        # 3. 检查价格 Tick
        if self.tester and self.tester.contract and req.symbol == self.tester.contract.symbol:
            tick = self.tester.contract.pricetick
            if tick > 0:
                remainder = req.price % tick
                # 浮点数容差
                if not (abs(remainder) < 1e-6 or abs(remainder - tick) < 1e-6):
                    log_error(f"⚠️ 【交易指令检查】委托价格({req.price})不符合最小变动价位({tick})")
                    return False

        # 4. 更新并检查计数器
        self.order_count += 1

        sig = self._order_signature(req)
        current_sig = int(self.order_signature_count.get(sig, 0)) + 1
        self.order_signature_count[sig] = current_sig
        if current_sig >= 2:
            self.repeat_order_count += 1
            self._check_repeat_threshold()

        order_threshold = int(self.max_order_count or 0)
        if order_threshold > 0 and (not self._warned_order_threshold) and self.order_count >= order_threshold:
            log_warning(f"【阈值预警】报单总数({self.order_count})达到或超过阈值({order_threshold})! 🚨")
            self._warned_order_threshold = True
            
        return True

    def check_cancel(self, req: CancelRequest) -> bool:
        """
        检查撤单是否允许。
        """
        if not self.active:
            log_warning("【风控拦截】交易已暂停，拒绝撤单")
            return False
        return True

    def on_order_submitted(self, order: OrderData) -> None:
        """
        订单提交时的回调（ACK）。
        """
        if self.order_count != self.last_log_order_count:
            log_info(f"【监测】当前报单总数: {self.order_count}")
            self.last_log_order_count = self.order_count

    def on_order_cancelled(self, order: OrderData) -> None:
        """
        订单撤销时的回调。
        """
        # 过滤历史订单（非本次会话创建）
        if order.vt_orderid not in self.session_order_ids:
            return

        self.cancel_count += 1
        
        if self.cancel_count != self.last_log_cancel_count:
            log_info(f"【监测】当前撤单总数: {self.cancel_count}")
            self.last_log_cancel_count = self.cancel_count

        cancel_threshold = int(self.max_cancel_count or 0)
        if cancel_threshold > 0 and (not self._warned_cancel_threshold) and self.cancel_count >= cancel_threshold:
            log_warning(f"【阈值预警】撤单总数({self.cancel_count})达到或超过阈值({cancel_threshold})! 🚨")
            self._warned_cancel_threshold = True
            
    def emergency_stop(self):
        """
        触发紧急停止。
        """
        log_warning("【应急处置】触发暂停交易功能！系统将拒绝后续指令。")
        self.active = False

    def set_thresholds(self, max_order=None, max_cancel=None, max_repeat=None):
        """
        动态设置风控阈值。
        """
        if max_order is not None:
            self.max_order_count = int(max_order)
        if max_cancel is not None:
            self.max_cancel_count = int(max_cancel)
        if max_repeat is not None:
            self.max_repeat_count = int(max_repeat)
        self._warned_order_threshold = False
        self._warned_cancel_threshold = False
        self._warned_repeat_threshold = False
        log_info(
            f"风控阈值已更新: Order={self.max_order_count}, Cancel={self.max_cancel_count}, Repeat={self.max_repeat_count}"
        )

    def get_thresholds(self) -> dict:
        return {
            "max_order_count": int(self.max_order_count or 0),
            "max_cancel_count": int(self.max_cancel_count or 0),
            "max_repeat_count": int(self.max_repeat_count or 0),
        }

    def get_metrics(self) -> dict:
        return {
            "order_count": int(self.order_count),
            "cancel_count": int(self.cancel_count),
            "repeat_order_count": int(self.repeat_order_count),
            "repeat_cancel_count": int(self.repeat_cancel_count),
            "repeat_total": int(self._repeat_total()),
        }

    def reset_counters(self):
        """
        重置所有计数器。
        """
        self.order_count = 0
        self.cancel_count = 0
        self.repeat_order_count = 0
        self.repeat_cancel_count = 0
        self.last_log_order_count = -1
        self.last_log_cancel_count = -1
        self.order_signature_count.clear()
        self.cancel_signature_count.clear()
        self._warned_order_threshold = False
        self._warned_cancel_threshold = False
        self._warned_repeat_threshold = False
        log_info("风控计数器已重置")
