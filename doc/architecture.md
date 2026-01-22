# CTP 穿透式测试程序架构设计文档

本稳档旨在详细描述 CTP 穿透式测试程序的系统架构、模块划分及核心机制实现方案，直接指导后续的代码编写。

## 1. 设计目标

- **合规性**：完全覆盖中国期货市场监控中心（CFMMC）的穿透式测试要求（基础交易、异常监测、阈值管理、错误防范、应急处理、日志记录）。
- **自动化**：实现全自动测试流程，包括模拟断线、暂停交易等需要外部干预的场景。
- **模块化**：采用高内聚低耦合的分层架构，便于维护和扩展。
- **稳定性**：引入原子操作延迟机制，确保网关与柜台交互的稳定性。

## 2. 系统架构

系统采用 **"主测试进程 + 外部控制脚本"** 的协作模式。主进程负责执行测试用例和维持网关连接，外部脚本通过 RPC（TCP Socket）向主进程发送控制指令，触发断线、暂停等状态变更，从而实现全自动化测试。

### 2.1 目录结构

```text
penetration_test/
├── .env                    # 环境变量配置文件 (CTP_NAME, 账户, 密码等)
├── run.bat                 # Windows 启动脚本
├── log/                    # 日志根目录
│   └── [CTP_NAME]/         # 按期货公司名称自动分类 (如: 宏源期货)
│       └── [CTP_NAME]_[YYYY-MM-DD].log  # 日志文件 (如: 宏源期货_2026-01-22.log)
├── doc/
│   ├── README.md           # 测试要求说明
│   └── architecture.md     # 本架构文档
├── scripts/
│   └── control.py          # [Client] 外部控制脚本，用于发送指令
└── src/                    # 核心源码包
    ├── __init__.py
    ├── config.py           # [Config] 配置加载与全局常量定义
    ├── logger.py           # [Log] 日志系统初始化与封装
    ├── utils.py            # [Utils] 通用工具 (原子等待、时间检查)
    ├── core/               # [Core] 核心组件层
    │   ├── __init__.py
    │   ├── engine.py       # 封装 vnpy MainEngine，集成各组件
    │   ├── risk.py         # 风控模块 (计数、阈值、拦截逻辑)
    │   └── server.py       # [Server] 命令监听服务 (TCP Server)
    └── tests/              # [Tests] 测试业务层
        ├── __init__.py
        ├── runner.py       # 测试调度器 (编排用例执行顺序)
        └── cases.py        # 测试用例集 (具体的测试步骤实现)
```

## 3. 核心机制

### 3.1 日志管理系统 (Standard Logging)
- **目标**：满足监管对日志记录的严格要求（交易、运行、监测、错误）。
- **实现**：
  - 使用 Python 标准库 `logging`。
  - **目录策略**：程序启动时读取 `.env` 中的 `CTP_NAME`。若 `log/{CTP_NAME}` 目录不存在则自动创建。
  - **文件命名**：`{CTP_NAME}_{YYYY-MM-DD}.log`。
  - **格式**：`%(asctime)s - %(levelname)s - %(module)s - %(message)s`。
  - **输出**：同时输出到控制台（StreamHandler）和文件（FileHandler）。

### 3.2 原子操作延迟 (Atomic Wait)
- **目标**：解决异步回报导致的测试竞态条件，确保每个操作有足够时间被柜台处理。
- **实现**：
  - 定义常量 `ATOMIC_WAIT_SECONDS = 7`。
  - 封装 `wait_for_reaction(seconds=ATOMIC_WAIT_SECONDS)` 函数。
  - **应用场景**：在每一次 `connect`（连接）、`send_order`（发单）、`cancel_order`（撤单）、`query_account`（查询）操作后，**必须**调用该函数进行阻塞等待。

### 3.3 自动化控制与 RPC (Auto-Coordination)
- **目标**：自动化测试“断线重连”和“暂停交易”等场景。
- **原理**：
  - **Server 端** (`src.core.server`)：在主进程的独立线程中运行，监听本地端口（如 9999）。接收指令并调用 `MainEngine` 或 `RiskManager` 的相应方法。
  - **Client 端** (`scripts/control.py`)：一个独立的 Python 脚本，接受命令行参数（如 `disconnect`, `pause`）。
  - **交互流程**：
    1. 主测试程序运行到特定步骤（如“测试断线”）。
    2. 主程序通过 `subprocess.run` 调用 `scripts/control.py disconnect`。
    3. `control.py` 向端口 9999 发送 `DISCONNECT` 指令。
    4. 主程序的 `Server` 线程收到指令，执行 `gateway.close()`。
    5. 主程序主线程检测到连接断开，验证通过。

## 4. 模块详细设计

### 4.1 src.config
- 加载 `.env` 文件。
- 导出配置字典 `CTP_SETTING`。
- 定义全局常量：
  - `LOG_DIR_NAME` (from CTP_NAME)
  - `ATOMIC_WAIT_SECONDS`
  - `RPC_PORT`

### 4.2 src.core.risk (TestRiskManager)
- **职责**：
  - 维护 `order_count`, `cancel_count`。
  - 维护 `symbol_order_count` (用于重复报单检测)。
  - 管理 `active` 状态 (用于暂停交易测试)。
  - 拦截异常指令 (价格 Tick 检查, 代码检查)。
- **接口**：
  - `check_order(req)` -> bool
  - `check_cancel(req)` -> bool
  - `on_order_submitted(order)`
  - `on_order_cancelled(order)`
  - `emergency_stop()`

### 4.3 src.core.server (CommandServer)
- **职责**：处理外部控制指令。
- **支持指令**：
  - `PAUSE`: 调用 `risk_manager.emergency_stop()`。
  - `RESUME`: 恢复交易权限 (可选)。
  - `DISCONNECT`: 调用 `gateway.close()`。
  - `RECONNECT`: 调用 `gateway.connect()`。

### 4.4 src.tests.cases
- 包含具体的测试函数，每个函数对应 README 中的一个测试点。
- **示例函数签名**：
  - `test_2_1_1_connectivity(tester)`
  - `test_2_1_2_basic_trading(tester)`
  - `test_2_2_1_disconnection(tester)`
- **逻辑**：每个函数内部执行 `Action` -> `wait_for_reaction` -> `Assert/Log`。

### 4.5 src.tests.runner
- **职责**：
  - 初始化 `MainEngine` 和 `CtptestGateway`。
  - 启动 `CommandServer`。
  - 按序调用 `src.tests.cases` 中的函数。
  - 捕获异常，确保测试流程不中断（或在致命错误时安全退出）。

## 5. 关键测试流程实现映射

| README 项目 | 自动化实现方案 |
| :--- | :--- |
| **2.1.1 连通性** | 启动程序 -> `connect` -> `wait` -> 检查 `OnFrontConnected` 日志。 |
| **2.1.2 基础交易** | `send_order(Open)` -> `wait` -> `send_order(Close)` -> `wait` -> `send_order(Cancel)` -> `wait`。 |
| **2.2.1 连接异常** | 调用 `control.py disconnect` -> `Server` 断开网关 -> `wait` -> 检查断开日志 -> 调用 `control.py reconnect` -> `wait` -> 检查重连日志。 |
| **2.2.2 笔数监测** | `RiskManager` 自动计数，每次操作后日志输出当前计数值。 |
| **2.3.1 阈值预警** | 当计数超过阈值时，`RiskManager` 写入 WARNING 日志。 |
| **2.4.1 指令检查** | 发送错误合约/价格指令 -> `RiskManager` 返回 False 或 网关拒单 -> 检查报错日志。 |
| **2.5.1 暂停交易** | 调用 `control.py pause` -> `Server` 设置 `active=False` -> 尝试发单 -> 检查“风控拦截”日志。 |

## 6. 运行说明

### 6.1 环境准备
- 确保 `.env` 配置正确。
- 确保 `.venv` 环境可用。

### 6.2 启动方式
双击运行 `run.bat` 或在终端执行：
```batch
run.bat
```
脚本内容：
```batch
@echo off
set PYTHONPATH=%cd%
".venv\Scripts\python.exe" src/main.py
pause
```
