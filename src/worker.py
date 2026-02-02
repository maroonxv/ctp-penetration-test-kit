import os
import sys

# 注入本地库路径，确保 vnpy_ctptest 的 C 扩展能正确加载
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

LIB_CTPTEST_PATH = os.path.join(PROJECT_ROOT, "lib", "vnpy_ctptest")
if LIB_CTPTEST_PATH not in sys.path:
    sys.path.insert(0, LIB_CTPTEST_PATH)

# 处理 Windows 下的 DLL 依赖加载问题
DLL_PATH = os.path.join(LIB_CTPTEST_PATH, "vnpy_ctptest", "api")
if os.name == "nt":
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(DLL_PATH)
        except Exception:
            pass
    os.environ["PATH"] = DLL_PATH + os.pathsep + os.environ["PATH"]

import time
import queue
import logging
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor

from src.core.engine import TestEngine
from src.core.server import CommandServer
from src.tests import cases
from src import read_config
from src.logger import setup_logger, log_info, log_error

try:
    import socketio as socketio_client
except Exception:
    socketio_client = None




def _color_for(levelno: int, msg: str) -> str:
    if levelno >= logging.ERROR:
        return "#ff4d4d"
    if levelno >= logging.WARNING:
        return "#ffbf00"
    if "OnRtn" in msg or "OnRsp" in msg or "收到" in msg or "回调" in msg:
        return "#00ccff"
    if "【" in msg:
        return "#00ff00"
    return "#cccccc"


class _SocketLogHandler(logging.Handler):
    def __init__(self, out_queue: queue.Queue):
        super().__init__()
        self.out_queue = out_queue

    def emit(self, record):
        try:
            msg = self.format(record)
            if "GET /" in msg or "POST /" in msg or "HTTP/1.1" in msg or "socket.io" in msg:
                return
            self.out_queue.put(
                (
                    "new_log",
                    {"message": msg, "color": _color_for(record.levelno, msg)},
                )
            )
        except Exception:
            self.handleError(record)


class _StreamToQueue:
    def __init__(self, original_stream, out_queue: queue.Queue):
        self.original_stream = original_stream
        self.out_queue = out_queue

    def write(self, message):
        self.original_stream.write(message)
        self.original_stream.flush()

        text = str(message)
        if not text.strip():
            return
        if text.lstrip().startswith(("[INFO]", "[WARNING]", "[ERROR]")):
            return
        if "GET /" in text or "POST /" in text or "HTTP/1.1" in text or "socket.io" in text:
            return
        self.out_queue.put(("new_log", {"message": text.rstrip("\n"), "color": "#cccccc"}))

    def flush(self):
        self.original_stream.flush()


class WorkerController:
    def __init__(self, web_socketio_url: str = "http://127.0.0.1:5006"):
        self.web_socketio_url = web_socketio_url
        self.engine = TestEngine()
        self.engine.connect()

        self.executor = ThreadPoolExecutor(max_workers=1)
        self.task_lock = threading.Lock()
        self.current_case_id = None
        self.last_error = None
        self.last_case_finished_at = None

        self.out_queue = queue.Queue()
        self._stop_event = threading.Event()

        self.sio = None
        if socketio_client is not None:
            self.sio = socketio_client.Client(reconnection=True, reconnection_attempts=0, reconnection_delay=1)

        root_logger = logging.getLogger()
        if not any(isinstance(h, _SocketLogHandler) for h in root_logger.handlers):
            handler = _SocketLogHandler(self.out_queue)
            handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
            root_logger.addHandler(handler)

        sys.stdout = _StreamToQueue(sys.stdout, self.out_queue)
        sys.stderr = _StreamToQueue(sys.stderr, self.out_queue)

        self._start_background_threads()

    def _start_background_threads(self):
        threading.Thread(target=self._socketio_connect_loop, daemon=True).start()
        threading.Thread(target=self._socketio_emit_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def _socketio_connect_loop(self):
        if not self.sio:
            return
        while not self._stop_event.is_set():
            try:
                if self.sio.connected:
                    time.sleep(1)
                    continue
                self.sio.connect(self.web_socketio_url, transports=["polling"])
            except Exception:
                time.sleep(2)

    def _socketio_emit_loop(self):
        while not self._stop_event.is_set():
            try:
                event, payload = self.out_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if self.sio and self.sio.connected:
                    self.sio.emit(event, payload)
            except Exception:
                pass

    def _heartbeat_loop(self):
        while not self._stop_event.is_set():
            try:
                if self.sio and self.sio.connected:
                    self.sio.emit("worker_status", self.get_status())
            except Exception:
                pass
            time.sleep(1)

    def get_status(self) -> dict:
        gateway = None
        try:
            gateway = self.engine.main_engine.get_gateway(self.engine.gateway_name)
        except Exception:
            gateway = None

        return {
            "state": "RUNNING",
            "busy": self.task_lock.locked(),
            "current_case_id": self.current_case_id,
            "gateway_exists": bool(gateway),
            "last_error": self.last_error,
            "last_case_finished_at": self.last_case_finished_at,
            "risk": self.get_risk_snapshot(),
        }

    def get_risk_snapshot(self) -> dict:
        rm = getattr(self.engine, "risk_manager", None)
        if not rm:
            return {}
        thresholds = {}
        metrics = {}
        try:
            thresholds = rm.get_thresholds()
        except Exception:
            thresholds = {}
        try:
            metrics = rm.get_metrics()
        except Exception:
            metrics = {}
        return {
            "active": bool(getattr(rm, "active", True)),
            "thresholds": thresholds,
            "metrics": metrics,
        }

    def set_thresholds(self, max_order_count=None, max_cancel_count=None, max_repeat_count=None) -> dict:
        rm = getattr(self.engine, "risk_manager", None)
        if not rm:
            raise RuntimeError("risk_manager_not_ready")
        rm.set_thresholds(max_order=max_order_count, max_cancel=max_cancel_count, max_repeat=max_repeat_count)
        return self.get_risk_snapshot()

    def reset_risk(self):
        if self.engine and self.engine.risk_manager:
            self.engine.risk_manager.active = True
            self.engine.risk_manager.reset_counters()

    def run_case(self, case_id: str) -> bool:
        case_id = (case_id or "").strip()
        func = self._case_map().get(case_id)
        if not func:
            raise ValueError(f"未找到测试项 {case_id}")

        if not self.task_lock.acquire(blocking=False):
            return False

        self.executor.submit(self._wrapped_case, case_id, func)
        return True

    def _wrapped_case(self, case_id: str, func):
        start = time.time()
        self.current_case_id = case_id
        self.last_error = None
        try:
            if hasattr(self.engine, "session_order_ids") and self.engine.session_order_ids is not None:
                self.engine.session_order_ids.clear()
            if self.sio and self.sio.connected:
                self.sio.emit("case_started", {"case_id": case_id, "started_at": time.time()})
            log_info(f"=== 开始执行: {case_id} ===")
            func(self.engine)
            log_info(f"=== 执行结束: {case_id} ===")
            if self.sio and self.sio.connected:
                self.sio.emit(
                    "case_finished",
                    {"case_id": case_id, "ok": True, "elapsed_s": round(time.time() - start, 3)},
                )
        except Exception as e:
            self.last_error = str(e)
            log_error(f"测试执行异常: {e}")
            log_error(traceback.format_exc())
            if self.sio and self.sio.connected:
                self.sio.emit(
                    "case_finished",
                    {"case_id": case_id, "ok": False, "elapsed_s": round(time.time() - start, 3), "error": str(e)},
                )
        finally:
            self.last_case_finished_at = time.time()
            self.current_case_id = None
            self.task_lock.release()

    def _case_map(self):
        return {
            "2.1.1": cases.test_2_1_1_connectivity,
            "2.1.2.1": cases.test_2_1_2_1_open,
            "2.1.2.2": cases.test_2_1_2_2_close,
            "2.1.2.3": cases.test_2_1_2_3_cancel,
            "2.2.1.1": cases.test_2_2_1_1_connect_status,
            "2.2.1.2": cases.test_2_2_1_2_disconnect,
            "2.2.1.3": cases.test_2_2_1_3_reconnect,
            "2.2.2.1": cases.test_2_2_2_1_order_count,
            "2.2.2.2": cases.test_2_2_2_2_cancel_count,
            "2.2.3.1": cases.test_2_2_3_1_repeat_open,
            "2.2.3.2": cases.test_2_2_3_2_repeat_close,
            "2.2.3.3": cases.test_2_2_3_3_repeat_cancel,
            "2.3.1.1": cases.test_2_3_1_1_order_threshold,
            "2.3.1.3": cases.test_2_3_1_3_cancel_threshold,
            "2.3.1.5": cases.test_2_3_1_5_repeat_threshold,
            "2.4.1.1": cases.test_2_4_1_1_code_error,
            "2.4.1.2": cases.test_2_4_1_2_price_error,
            "2.4.1.3": cases.test_2_4_1_3_volume_error,
            "2.4.2.1": cases.test_2_4_2_1_fund_error,
            "2.4.2.2": cases.test_2_4_2_2_pos_error,
            "2.4.2.3": cases.test_2_4_2_3_market_error,
            "2.5.1.1": cases.test_2_5_1_1_limit_perms,
            "2.5.1.2": cases.test_2_5_1_2_pause_strategy,
            "2.5.2.1": cases.test_2_5_2_1_cancel_part,
            "2.5.2.2": cases.test_2_5_2_2_cancel_all,
            "2.6.1": cases.test_2_6_1_log_record,
        }

    def handle_rpc_request(self, req: dict) -> dict:
        request_id = req.get("request_id")
        req_type = str(req.get("type", "")).upper()
        payload = req.get("payload") or {}

        try:
            if req_type == "PING":
                return {"request_id": request_id, "ok": True, "data": {"pong": True}}
            if req_type == "GET_STATUS":
                return {"request_id": request_id, "ok": True, "data": self.get_status()}
            if req_type == "GET_THRESHOLDS":
                return {"request_id": request_id, "ok": True, "data": (self.get_risk_snapshot().get("thresholds") or {})}
            if req_type == "GET_RISK_SNAPSHOT":
                return {"request_id": request_id, "ok": True, "data": self.get_risk_snapshot()}
            if req_type == "GET_TEST_CONFIG":
                return {
                    "request_id": request_id,
                    "ok": True,
                    "data": {
                        "test_symbol": read_config.TEST_SYMBOL,
                        "safe_buy_price": read_config.SAFE_BUY_PRICE,
                        "deal_buy_price": read_config.DEAL_BUY_PRICE
                    }
                }
            if req_type == "SET_TEST_CONFIG":
                test_symbol = payload.get("test_symbol")
                safe_buy_price = payload.get("safe_buy_price")
                deal_buy_price = payload.get("deal_buy_price")
                
                # Update memory
                if test_symbol:
                    read_config.TEST_SYMBOL = str(test_symbol)
                if safe_buy_price:
                    read_config.SAFE_BUY_PRICE = float(safe_buy_price)
                if deal_buy_price:
                    read_config.DEAL_BUY_PRICE = float(deal_buy_price)
                    
                # Save to file
                data_to_save = {}
                if test_symbol:
                    data_to_save["test_symbol"] = read_config.TEST_SYMBOL
                if safe_buy_price:
                    data_to_save["safe_buy_price"] = read_config.SAFE_BUY_PRICE
                if deal_buy_price:
                    data_to_save["deal_buy_price"] = read_config.DEAL_BUY_PRICE
                
                read_config.save_yaml_config(read_config.CONFIG_YAML_PATH, data_to_save)
                
                return {
                    "request_id": request_id, 
                    "ok": True, 
                    "data": {
                        "test_symbol": read_config.TEST_SYMBOL,
                        "safe_buy_price": read_config.SAFE_BUY_PRICE,
                        "deal_buy_price": read_config.DEAL_BUY_PRICE
                    }
                }
            if req_type == "SET_THRESHOLDS":
                max_order_count = payload.get("max_order_count")
                max_cancel_count = payload.get("max_cancel_count")
                max_repeat_count = payload.get("max_repeat_count")
                data = self.set_thresholds(
                    max_order_count=max_order_count,
                    max_cancel_count=max_cancel_count,
                    max_repeat_count=max_repeat_count,
                )
                return {"request_id": request_id, "ok": True, "data": data}
            if req_type == "RESET_RISK":
                self.reset_risk()
                return {"request_id": request_id, "ok": True}
            if req_type == "RUN_CASE":
                accepted = self.run_case(str(payload.get("case_id", "")))
                return {"request_id": request_id, "ok": True, "data": {"accepted": bool(accepted)}}
            if req_type == "DISCONNECT":
                self.engine.disconnect()
                return {"request_id": request_id, "ok": True}
            if req_type == "RECONNECT":
                self.engine.reconnect()
                return {"request_id": request_id, "ok": True}
            if req_type == "PAUSE":
                self.engine.pause()
                return {"request_id": request_id, "ok": True}
            return {"request_id": request_id, "ok": False, "error": f"unknown_type: {req_type}"}
        except Exception as e:
            return {"request_id": request_id, "ok": False, "error": str(e)}

    def disconnect(self):
        self.engine.disconnect()

    def reconnect(self):
        self.engine.reconnect()

    def pause(self):
        self.engine.pause()

    def stop(self):
        self._stop_event.set()
        try:
            if self.sio and self.sio.connected:
                self.sio.disconnect()
        except Exception:
            pass


def main():
    setup_logger()
    log_info("=== 交易进程 (Worker) 启动 ===")

    controller = None
    server = None
    try:
        log_info("正在初始化 TestEngine...")
        controller = WorkerController()
        server = CommandServer(controller)
        server.start()
        
        # 给一点时间让 Server 启动并绑定端口
        time.sleep(1.0)
        if not server.is_alive():
             log_error("RPC Server 未能成功启动（可能端口被占用），Worker 即将退出。")
             if controller:
                 controller.stop()
                 if controller.engine:
                     controller.engine.disconnect()
             return

        log_info("交易进程就绪，等待指令...")

        while server.is_alive():
            time.sleep(1)
            
        log_error("RPC Server 已停止，Worker 即将退出。")
            
    except KeyboardInterrupt:
        log_info("交易进程收到退出信号。")
    except Exception as e:
        log_error(f"交易进程发生未捕获异常: {e}")
        log_error(traceback.format_exc())
    finally:
        try:
            if server:
                server.stop()
        except Exception:
            pass
        try:
            if controller:
                controller.stop()
        except Exception:
            pass
        try:
            if controller and controller.engine:
                controller.engine.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
