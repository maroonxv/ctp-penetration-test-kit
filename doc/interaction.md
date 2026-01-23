# CTP 穿透式测试可视化交互方案 (Flask + SocketIO)

本方案旨在构建一个**高实时性、非阻塞、安全可控**的 Web 交互控制台，用于 CTP 穿透式测试的执行与监控。
方案采用 **Flask + SocketIO + 单例引擎** 的单进程多线程架构，以实现毫秒级日志回显和精确的任务调度。
**本方案严格遵循 README.md 中的测试点划分，为每一个三级测试点（如 2.1.2）设计独立的测试按钮，且每个按钮的后端逻辑需完整覆盖其下属的所有四级测试点（如 2.1.2.1 ~ 2.1.2.3）。**

---

## 1. 系统架构设计

### 1.1 核心架构图
采用 **B/S 架构**，后端为单进程 Python 应用，内部维护 Web 服务线程与交易核心线程。

```mermaid
graph TD
    Browser[浏览器前端] <-->|WebSocket (SocketIO)| FlaskWeb[Flask Web Server]
    Browser <-->|HTTP REST| FlaskWeb
    
    subgraph "Python 进程 (src)"
        FlaskWeb -->|调用| Manager[TestManager (单例调度器)]
        
        subgraph "调度层"
            Manager -->|互斥锁 (Lock)| TaskLock
            Manager -->|异步提交| ThreadPool[ThreadPoolExecutor (Max=1)]
        end
        
        subgraph "执行层"
            ThreadPool -->|执行| Cases[测试用例 (cases.py)]
            Cases -->|操作| Engine[TestEngine (交易核心)]
            Engine -->|CTP API| Exchange[期货交易所]
        end
        
        subgraph "日志流"
            Engine -.->|LogRecord| RootLogger
            Cases -.->|LogRecord| RootLogger
            RootLogger -->|Emit| SocketHandler[SocketIOHandler]
            SocketHandler -->|Push| FlaskWeb
        end
    end
```

### 1.2 目录结构规划
所有新增代码均位于 `src/` 下，确保与核心逻辑紧密集成。

```text
c:\Users\Administrator\Lai\penetration_test\
├── doc/
│   └── interaction.md       <-- 本执行方案
├── src/
│   ├── manager.py           <-- [核心新增] 任务调度与引擎托管
│   ├── socket_handler.py    <-- [核心新增] 日志拦截与推送
│   ├── web/                 <-- [核心新增] Web 子模块
│   │   ├── __init__.py
│   │   ├── app.py           <-- Flask 入口
│   │   ├── static/
│   │   │   ├── css/
│   │   │   └── js/
│   │   └── templates/
│   │       └── index.html   <-- 前端主界面
│   ├── core/                <-- 既有核心代码 (保持不变)
│   ├── tests/               <-- 既有测试用例 (保持不变)
│   └── ...
└── requirements.txt         <-- 需新增依赖
```

---

## 2. 详细实施步骤与逻辑设计

### 2.1 环境依赖安装
在 `requirements.txt` 中追加 `flask`, `flask-socketio`, `eventlet` 等 Web 框架依赖。

### 2.2 核心组件逻辑设计

#### 2.2.1 任务调度器 (`src/manager.py`)
**职责**：全局单例，持有 `TestEngine`，管理线程池，防止并发冲突。

**逻辑伪代码**:
```text
Class TestManager (Singleton):
    // 成员变量
    Member engine: TestEngine 实例
    Member executor: 线程池 (容量=1)
    Member task_lock: 互斥锁

    // 初始化方法
    Method initialize():
        If 尚未初始化:
            实例化 TestEngine
            调用 engine.connect() 建立基础连接
            创建单线程 executor (确保任务串行)
            标记为已初始化

    // 任务提交接口
    Method run_task(target_function):
        Try Acquire task_lock (Non-blocking):
            If 成功获取锁:
                // 异步提交任务，将 engine 注入给测试函数
                executor.submit(_wrapped_task, target_function, self.engine)
                Return Success, "任务已启动"
            Else:
                Return Failure, "任务运行中，请等待"

    // 内部任务包装器
    Method _wrapped_task(function, engine):
        Try:
            Log "开始执行任务"
            Call function(engine)  // 执行具体的测试用例逻辑
            Log "任务执行完成"
        Catch Exception:
            Log Error 堆栈信息
        Finally:
            Release task_lock  // 必须释放锁，否则后续任务无法执行

    // 风控重置接口
    Method reset_risk_manager():
        Set engine.risk_manager.active = True
        Log "风控已重置"
```

#### 2.2.2 日志推流器 (`src/socket_handler.py`)
**职责**：拦截 Python `logging` 系统的日志，实时推送到 SocketIO。

**逻辑伪代码**:
```text
Class SocketIOHandler (Inherits logging.Handler):
    Member socketio: SocketIO 服务器实例

    // 日志发射方法 (Override)
    Method emit(log_record):
        Format log_record to string message
        Determine color based on log_record.level or content:
            If level == ERROR -> Red
            If level == WARNING -> Amber
            If message contains "Callback" -> Blue
            Else -> Grey/White
        
        // 推送 WebSocket 事件
        Call socketio.emit('new_log', {
            'message': message, 
            'color': color
        })
```

#### 2.2.3 Web 应用入口 (`src/web/app.py`)
**职责**：Flask 路由配置，脱敏数据注入，API 映射。

**逻辑伪代码**:
```text
Initialize Flask App
Initialize SocketIO (Async Mode = Threading)

// 初始化核心组件
Create TestManager Instance -> Call initialize()
Get Root Logger -> Add SocketIOHandler

// 路由定义
Route POST "/api/run/<case_id>":
    Map case_id to specific function in src.tests.cases:
        "2.1.1" -> cases.test_2_1_1_connectivity
        "2.1.2" -> cases.test_2_1_2_basic_trading
        "2.2.1" -> cases.test_2_2_1_connection_monitor
        "2.2.2" -> cases.test_2_2_2_count_monitor
        "2.2.3" -> cases.test_2_2_3_repeat_monitor
        "2.3.1" -> cases.test_2_3_1_threshold_alert
        "2.4.1" -> cases.test_2_4_1_order_check
        "2.4.2" -> cases.test_2_4_2_error_prompt
        "2.5.1" -> cases.test_2_5_1_pause_trading
        "2.5.2" -> cases.test_2_5_2_batch_cancel
        "2.6.1" -> cases.test_2_6_1_log_record
    
    If case_id not found: Return 404
    Call manager.run_task(mapped_function)
    Return JSON Result
```

#### 2.2.4 前端页面 (`src/web/templates/index.html`)
**职责**：基于 Bootstrap 5 的深色主题 UI，集成 SocketIO 客户端。

**UI 结构描述**:
*   **侧边栏 (Sidebar)**:
    *   显示环境信息。
    *   **手风琴菜单 (Accordion)**: 按二级章节分组 (2.1, 2.2, 2.3, 2.4, 2.5, 2.6)。
    *   **操作按钮**: **严格对应每个三级测试点 (如 2.1.1, 2.1.2)**。
*   **主内容区 (Main)**:
    *   **日志控制台**: 实时显示测试过程中的所有四级分点验证日志。

---

## 3. 功能交互与测试覆盖对照表

本表定义了每个按钮触发的后端逻辑，以及该逻辑如何覆盖 README.md 中的所有四级细分点。

### 2.1 接口适应性
| 按钮 (三级点) | 后端逻辑 (`cases.py`) | 覆盖细分测试点 (四级点) | 预期验证行为 |
| :--- | :--- | :--- | :--- |
| **2.1.1 连通性** | `test_2_1_1_connectivity` | **2.1.1.1** 登录认证 | 验证 `OnFrontConnected` 和 `OnRspUserLogin` 回调，输出认证成功日志。 |
| **2.1.2 基础交易** | `test_2_1_2_basic_trading` | **2.1.2.1** 开仓指令<br>**2.1.2.2** 平仓指令<br>**2.1.2.3** 撤单指令 | 1. 发送开仓单 -> 成交。<br>2. 发送平仓单 -> 成交。<br>3. 发送挂单 -> 撤单 -> 确认撤单回报。 |

### 2.2 异常监测
| 按钮 (三级点) | 后端逻辑 (`cases.py`) | 覆盖细分测试点 (四级点) | 预期验证行为 |
| :--- | :--- | :--- | :--- |
| **2.2.1 连接监测** | `test_2_2_1_connection_monitor` | **2.2.1.1** 连接状态显示<br>**2.2.1.2** 断线状态显示<br>**2.2.1.3** 重连成功显示 | 1. 检查当前连接。<br>2. 主动断开 Gateway -> 捕获断线日志。<br>3. 自动重连 -> 捕获重连日志。 |
| **2.2.2 笔数监测** | `test_2_2_2_count_monitor` | **2.2.2.1** 统计报单笔数<br>**2.2.2.2** 统计撤单笔数 | 1. 读取并打印内存中累计的 `OrderCount`。<br>2. 读取并打印累计的 `CancelCount`。 |
| **2.2.3 重复报单** | `test_2_2_3_repeat_monitor` | **2.2.3.1** 重复开仓统计<br>**2.2.3.2** 重复平仓统计<br>**2.2.3.3** 重复撤单统计 | 1. 连续发送3笔相同开仓单。<br>2. 连续发送3笔相同平仓单。<br>3. 连续发送3笔相同撤单。<br>验证系统是否识别并记录重复次数。 |

### 2.3 阈值管理
| 按钮 (三级点) | 后端逻辑 (`cases.py`) | 覆盖细分测试点 (四级点) | 预期验证行为 |
| :--- | :--- | :--- | :--- |
| **2.3.1 阈值预警** | `test_2_3_1_threshold_alert` | **2.3.1.1** 报单阈值设置<br>**2.3.1.2** 报单超限预警<br>**2.3.1.3** 撤单阈值设置<br>**2.3.1.4** 撤单超限预警<br>**2.3.1.5** 重复报单阈值<br>**2.3.1.6** 重复报单预警 | 1. 设置低阈值 (如 MaxOrder=5)。<br>2. 循环发单触发阈值 -> 验证 **黄色警告日志**。<br>3. 循环撤单触发阈值 -> 验证警告。<br>4. 触发重复报单阈值 -> 验证警告。 |

### 2.4 错误防范
| 按钮 (三级点) | 后端逻辑 (`cases.py`) | 覆盖细分测试点 (四级点) | 预期验证行为 |
| :--- | :--- | :--- | :--- |
| **2.4.1 指令检查** | `test_2_4_1_order_check` | **2.4.1.1** 合约代码错误<br>**2.4.1.2** 最小变动价位错误<br>**2.4.1.3** 委托超限错误 | 1. 发送 Symbol="ERROR"。<br>2. 发送 Price=Tick+0.0001。<br>3. 发送 Volume=Huge。<br>验证系统前端拦截并输出 **红色错误日志**。 |
| **2.4.2 错误提示** | `test_2_4_2_error_prompt` | **2.4.2.1** 资金不足<br>**2.4.2.2** 持仓不足<br>**2.4.2.3** 市场状态错误 | 1. 模拟巨额报单触发 CTP "资金不足"。<br>2. 模拟平无仓位合约触发 "平仓量超过持仓"。<br>验证 CTP 返回的 `OnRspOrderInsert` 错误信息显示。 |

### 2.5 应急处理
| 按钮 (三级点) | 后端逻辑 (`cases.py`) | 覆盖细分测试点 (四级点) | 预期验证行为 |
| :--- | :--- | :--- | :--- |
| **2.5.1 暂停交易** | `test_2_5_1_pause_trading` | **2.5.1.1** 限制交易权限<br>**2.5.1.2** 暂停策略<br>**2.5.1.3** 强制退出 | 1. 触发 `RiskManager.active = False`。<br>2. 尝试发单 -> 被拦截。<br>3. (选测) 调用 Gateway Close 模拟强退。 |
| **2.5.2 批量撤单** | `test_2_5_2_batch_cancel` | **2.5.2.1** 撤销部分成交单<br>**2.5.2.2** 撤销已报单 | 1. 发送多笔挂单。<br>2. 执行批量撤单逻辑。<br>3. 验证所有活动挂单状态变为 "Canceled"。 |

### 2.6 日志记录
| 按钮 (三级点) | 后端逻辑 (`cases.py`) | 覆盖细分测试点 (四级点) | 预期验证行为 |
| :--- | :--- | :--- | :--- |
| **2.6.1 日志验证** | `test_2_6_1_log_record` | **2.6.1.1** 交易日志<br>**2.6.1.2** 运行日志<br>**2.6.1.3** 监测日志<br>**2.6.1.4** 错误日志 | 遍历当前日志文件或内存日志流，确认包含上述关键字（如 "Trade", "Info", "Monitor", "Error"），并输出统计结果。 |

---

## 4. 启动与验证

1.  确保 `src` 目录包含上述所有文件。
2.  在项目根目录运行 Python 模块启动命令。
3.  打开浏览器访问本地端口。
4.  观察左侧手风琴菜单，确认包含了从 2.1 到 2.6 的所有测试分组。
5.  依次点击每个按钮，观察右侧日志是否完整覆盖了表格中列出的所有细分测试点。
