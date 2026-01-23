# 方法与类详细设计文档

本文档详细定义了 CTP 穿透式测试交互方案中涉及的核心类、方法及其逻辑流程。

## 1. 核心调度模块 (`src/manager.py`)

### 1.1 类: `TestManager`
**职责**: 全局单例，负责管理 `TestEngine` 生命周期、任务队列及并发锁。

#### 1.1.1 方法: `__new__` (单例模式)
```python
def __new__(cls):
    if not cls._instance:
        with cls._lock:
            if not cls._instance:
                cls._instance = super().__new__(cls)
                cls._instance.initialized = False
    return cls._instance
```

#### 1.1.2 方法: `initialize`
**职责**: 初始化引擎与线程池。仅执行一次。
```python
def initialize(self):
    if self.initialized: return
    
    # 1. 初始化核心引擎
    self.engine = TestEngine()
    self.engine.connect()  # 建立 CTP 连接
    
    # 2. 初始化线程池 (最大 1 个工作线程，确保串行)
    self.executor = ThreadPoolExecutor(max_workers=1)
    
    # 3. 初始化任务锁
    self.task_lock = threading.Lock()
    
    self.initialized = True
```

#### 1.1.3 方法: `run_task`
**职责**: 接收测试请求，尝试获取锁并提交到后台线程。
**参数**: `task_func` (函数对象), `*args`
**返回**: `(bool, str)` -> (是否成功, 提示信息)
```python
def run_task(self, task_func, *args):
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
```

#### 1.1.4 方法: `_wrapped_task`
**职责**: 任务执行包装器，负责异常捕获和锁释放。
```python
def _wrapped_task(self, task_func, *args):
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
```

#### 1.1.5 方法: `reset_risk_manager`
**职责**: 恢复风控状态，用于 2.5.1 测试后的恢复。
```python
def reset_risk_manager(self):
    if self.engine and self.engine.risk_manager:
        self.engine.risk_manager.active = True
        # 重置计数器以便进行下一轮测试
        self.engine.risk_manager.reset_counters() 
        log_info("系统状态已重置，允许继续交易。")
```

---

## 2. 日志处理模块 (`src/socket_handler.py`)

### 2.1 类: `SocketIOHandler`
**职责**: 继承自 `logging.Handler`，将日志记录转发至 SocketIO。

#### 2.1.1 方法: `emit`
```python
def emit(self, record):
    try:
        msg = self.format(record)
        
        # 颜色逻辑判断
        color = "#cccccc" # Default Grey
        if record.levelno >= logging.ERROR:
            color = "#ff4d4d" # Red
        elif record.levelno >= logging.WARNING:
            color = "#ffbf00" # Orange
        elif "OnRtn" in msg or "OnRsp" in msg:
            color = "#00ccff" # Blue (CTP Callback)
        elif "【" in msg:
            color = "#00ff00" # Green (Key Info)
            
        # 推送事件
        self.socketio.emit('new_log', {'message': msg, 'color': color})
    except:
        self.handleError(record)
```

---

## 3. 测试用例模块 (`src/tests/cases.py`)

本模块函数需严格对应 README.md 的测试点。

### 3.1 接口适应性 (2.1)

#### `test_2_1_1_connectivity(engine)`
*   **目标**: 2.1.1.1 验证登录认证
*   **逻辑**:
    1.  检查 `engine.main_engine` 的连接状态。
    2.  如果未连接，调用 `engine.connect()`。
    3.  等待 `OnFrontConnected` 和 `OnRspUserLogin` 日志出现。

#### `test_2_1_2_basic_trading(engine)`
*   **目标**: 2.1.2.1 开仓, 2.1.2.2 平仓, 2.1.2.3 撤单
*   **逻辑**:
    1.  **开仓**: 发送 Buy/Open 报单，等待成交回报。
    2.  **平仓**: 发送 Sell/Close 报单，等待成交回报。
    3.  **撤单**: 发送 Buy/Open (价格远离市价) 报单，获取 OrderID，随即发送 CancelReq，等待撤单回报。

### 3.2 异常监测 (2.2)

#### `test_2_2_1_connection_monitor(engine)`
*   **目标**: 2.2.1.1 连接状态, 2.2.1.2 断线, 2.2.1.3 重连
*   **逻辑**:
    1.  打印当前连接状态 (Connected)。
    2.  调用 `engine.main_engine.get_gateway("CTPTEST").close()` 模拟断线。
    3.  等待并验证 "OnFrontDisconnected" 日志。
    4.  等待 3 秒后，调用 `engine.connect()` 重连。
    5.  等待并验证 "OnFrontConnected" 日志。

#### `test_2_2_2_count_monitor(engine)`
*   **目标**: 2.2.2.1 报单统计, 2.2.2.2 撤单统计
*   **逻辑**:
    1.  读取 `engine.risk_manager.order_count` 并打印。
    2.  读取 `engine.risk_manager.cancel_count` 并打印。
    3.  (可选) 发送一笔新单，验证计数器 +1。

#### `test_2_2_3_repeat_monitor(engine)`
*   **目标**: 2.2.3.1 重复开仓, 2.2.3.2 重复平仓, 2.2.3.3 重复撤单
*   **逻辑**:
    1.  **重复开仓**: 循环 3 次发送完全相同的 Buy/Open 报单。
    2.  **重复平仓**: 循环 3 次发送完全相同的 Sell/Close 报单。
    3.  **重复撤单**: 对同一个 OrderID (假设存在) 循环发送 3 次撤单指令。
    4.  验证日志中是否出现风控模块的 "重复报单" 计数或警告。

### 3.3 阈值管理 (2.3)

#### `test_2_3_1_threshold_alert(engine)`
*   **目标**: 2.3.1.1~2.3.1.6 验证阈值设置及预警
*   **逻辑**:
    1.  **设置低阈值**: 调用 `engine.risk_manager.set_thresholds(max_order=5, max_cancel=3, max_repeat=2)`。
    2.  **触发报单预警**: 循环发送 6 笔报单，验证第 6 笔触发 "Warning"。
    3.  **触发撤单预警**: 循环发送 4 笔撤单，验证第 4 笔触发 "Warning"。
    4.  **触发重复预警**: 循环发送 3 笔相同单，验证第 3 笔触发 "Warning"。
    5.  **恢复阈值**: 测试结束后恢复默认高阈值。

### 3.4 错误防范 (2.4)

#### `test_2_4_1_order_check(engine)`
*   **目标**: 2.4.1.1 代码错误, 2.4.1.2 价格错误, 2.4.1.3 数量超限
*   **逻辑**:
    1.  构造 `OrderRequest(symbol="INVALID")`，发送，验证前端拦截日志。
    2.  构造 `OrderRequest(price=Tick+0.00001)`，发送，验证前端拦截日志。
    3.  构造 `OrderRequest(volume=1000000)`，发送，验证前端拦截日志。

#### `test_2_4_2_error_prompt(engine)`
*   **目标**: 2.4.2.1 资金不足, 2.4.2.2 持仓不足
*   **逻辑**:
    1.  **资金不足**: 发送价格极高或数量极大的买单 (绕过前端检查直接发往 CTP)，等待 `OnRspOrderInsert` 返回 "资金不足" 错误代码。
    2.  **持仓不足**: 发送平仓单 (Close) 但账户无持仓，等待 CTP 返回 "平仓量超过持仓" 错误。

### 3.5 应急处理 (2.5)

#### `test_2_5_1_pause_trading(engine)`
*   **目标**: 2.5.1.1 限制权限, 2.5.1.2 暂停策略, 2.5.1.3 强退
*   **逻辑**:
    1.  设置 `engine.risk_manager.active = False`。
    2.  尝试发送一笔正常报单。
    3.  验证日志输出 "【风控拦截】交易已暂停"。
    4.  (选测) 再次调用 `gateway.close()` 模拟强制退出。

#### `test_2_5_2_batch_cancel(engine)`
*   **目标**: 2.5.2.1 撤部分成交, 2.5.2.2 撤已报
*   **逻辑**:
    1.  前提：确保风控处于 Active 状态。
    2.  连续发送 3 笔挂单 (价格远离市价以保持 Un-traded 状态)。
    3.  获取当前所有活动订单列表 `engine.get_all_active_orders()`。
    4.  遍历列表，逐个发送 `CancelRequest`。
    5.  验证所有订单状态变为 Canceled。

### 3.6 日志记录 (2.6)

#### `test_2_6_1_log_record(engine)`
*   **目标**: 验证各类日志的存在性
*   **逻辑**:
    1.  此测试点更多是“人工核查”性质。
    2.  代码逻辑：在日志中打印一条汇总信息，提示用户“请检查 log/ 目录下日志文件，确认包含 Trade/Info/Error/Monitor 标签”。
    3.  或者读取当前内存中的 LogHandler 缓存（如果有）进行关键字匹配检查。

---

## 4. 风控模块更新 (`src/core/risk.py`)

### 4.1 类: `TestRiskManager`

需要新增方法以支持测试需求：

#### 4.1.1 方法: `set_thresholds`
```python
def set_thresholds(self, max_order=None, max_cancel=None, max_symbol_order=None):
    if max_order: self.max_order_count = max_order
    if max_cancel: self.max_cancel_count = max_cancel
    if max_symbol_order: self.max_symbol_order_count = max_symbol_order
    log_info(f"风控阈值已更新: Order={self.max_order_count}, Cancel={self.max_cancel_count}")
```

#### 4.1.2 方法: `reset_counters`
```python
def reset_counters(self):
    self.order_count = 0
    self.cancel_count = 0
    self.symbol_order_count.clear()
    log_info("风控计数器已重置")
```
