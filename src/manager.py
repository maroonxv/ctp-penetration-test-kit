import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from src.core.engine import TestEngine
from src.logger import log_info, log_error

class TestManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(TestManager, cls).__new__(cls)
                    cls._instance.initialized = False
        return cls._instance

    def initialize(self):
        """
        初始化 TestEngine 和线程池
        """
        if self.initialized: return
        
        # 1. 初始化核心引擎
        log_info("正在初始化 TestEngine...")
        self.engine = TestEngine()
        self.engine.connect()  # 建立 CTP 连接
        
        # 2. 初始化线程池 (最大 1 个工作线程，确保串行)
        self.executor = ThreadPoolExecutor(max_workers=1)
        
        # 3. 初始化任务锁
        self.task_lock = threading.Lock()
        
        self.initialized = True
        log_info("TestManager 初始化完成")

    def run_task(self, task_func, *args):
        """
        运行测试任务
        :param task_func: 测试函数
        :param args: 参数
        :return: (bool, msg)
        """
        # 非阻塞尝试获取锁
        if self.task_lock.acquire(blocking=False):
            try:
                # 提交任务到线程池
                self.executor.submit(self._wrapped_task, task_func, *args)
                return True, "测试任务已启动"
            except Exception as e:
                self.task_lock.release() # 提交失败需释放锁
                return False, f"任务提交失败: {e}"
        else:
            return False, "当前有测试正在运行，请等待结束"

    def _wrapped_task(self, task_func, *args):
        """
        任务包装器
        """
        try:
            log_info(f"=== 开始执行: {task_func.__name__} ===")
            # 将 engine 实例注入为第一个参数
            task_func(self.engine, *args)
            log_info(f"=== 执行结束: {task_func.__name__} ===")
        except Exception as e:
            log_error(f"测试执行异常: {e}")
            log_error(traceback.format_exc())
        finally:
            # 无论成功失败，必须释放锁
            self.task_lock.release()

    def reset_risk_manager(self):
        """
        重置风控状态
        """
        if self.engine and self.engine.risk_manager:
            self.engine.risk_manager.active = True
            # 重置计数器以便进行下一轮测试
            self.engine.risk_manager.reset_counters() 
            log_info("系统状态已重置，允许继续交易。")
