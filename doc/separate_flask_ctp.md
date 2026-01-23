# CTP 穿透测试工具架构重构方案：Web 与 CTP 进程分离

## 1. 背景与问题

当前架构采用 **单进程模式**，Flask Web 服务与 VnPy CTP 交易引擎运行在同一个 Python 进程中。由于 CTP API 的底层特性（C++ 扩展、GIL 占用）以及网络操作的阻塞性质，存在以下严重问题：

1.  **进程级死锁**：当 CTP 网关执行 `close()` 或遭遇网络层阻塞时，会卡死整个 Python 主线程，导致 Flask Web 服务无法响应 HTTP 请求。
2.  **无法实现“真断线”**：在同一进程内，无法安全地彻底销毁并重建底层的 CTP 实例（尤其是静态数据区污染问题）。
3.  **容错性差**：交易模块的崩溃会导致 Web 控制台同时崩溃，用户无法查看最后的状态或日志。

### 1.1 与当前代码库现状的对应关系（务必纳入设计约束）

当前仓库中已经出现了“为了不拖死 Web，不得不放弃物理关闭”的权衡，这恰恰说明需要用进程边界隔离风险：

- `src/core/engine.py` 的 `disconnect()` 明确记录：调用底层网关 `close()` 可能锁死 Python 进程，因此采取“逻辑断线（不 close、仅移除 gateway 引用）”以保证 Web 存活。
- `src/web/app.py` 在启动阶段会实例化并初始化 `TestManager -> TestEngine.connect()`，也就是 Web 与 CTP 在同一进程内强耦合。
- `src/core/server.py` 已提供一个 TCP `CommandServer`（默认 9999 端口），目前命令集较小（`DISCONNECT/RECONNECT/PAUSE`）。
- `src/worker.py` 已存在独立 Worker 入口（初始化 `TestEngine` 并常驻），因此后续重构应优先“复用并强化现有入口”，而不是平行再造一个概念重复的入口文件。

## 2. 目标架构

采用 **多进程架构 (Master-Worker Pattern)** 进行重构：

*   **Master 进程 (Web/Manager)**
    *   运行 Flask Web Server 和 SocketIO Server。
    *   负责 UI 展示、用户指令接收。
    *   **核心职责**：管理 Worker 进程的生命周期（启动、停止、强制重启）。
    *   充当 RPC Client，将前端动作转换为对 Worker 的 RPC 请求。

*   **Worker 进程 (Trader)**
    *   独立运行 Python 进程。
    *   加载 `TestEngine` 和 CTP Gateway。
    *   **核心职责**：执行实际的 CTP 交易、行情订阅、风控检查。
    *   充当 RPC Server，监听来自 Master 的 RPC 请求，并严格串行执行用例。
    *   充当 Log/Status Producer，将日志与状态实时推送到 Master（供前端展示）。

## 3. 详细设计

### 3.1 进程管理 (Process Management)

在 `src/web/app.py` 中引入 `subprocess` 模块，使 Web 成为 Worker 的唯一“生命周期管理者”（单实例、可重启、可硬中断）。

```python
# 伪代码示例
class ProcessManager:
    def start_worker(self):
        # 启动独立的 Python 进程运行 Worker 入口（优先复用 src/worker.py）
        self.process = subprocess.Popen([sys.executable, "src/worker.py"])
    
    def kill_worker(self):
        # 强制杀进程，实现“硬中断”
        if self.process:
            self.process.kill()
            
    def restart_worker(self):
        self.kill_worker()
        self.start_worker()
```

建议补充的管理语义（避免“能杀能起但不可控”）：

- 单实例互斥：Web 侧维护 Worker 状态机（`STOPPED/STARTING/RUNNING/STOPPING/CRASHED`），避免重复启动导致 9999 端口争抢。
- Ready 探活：`start_worker()` 后先执行 `PING`（RPC）确认 Worker 已就绪再允许下发用例。
- 崩溃自愈：Worker 退出/崩溃时，Web 记录退出码与最后心跳时间，并提供“一键重启”。

此机制用于“真断线”测试：测试脚本/按钮只需调用 `kill_worker()` 即可模拟最真实的宕机/断网，再用 `start_worker()` 模拟重启恢复。

### 3.2 进程间通信 (IPC)

#### A. 指令下发 (Web -> Worker)
复用现有的 TCP Socket 机制（9999 端口），但需要从“简单字符串命令”升级为“可扩展、可返回结果的 RPC”：

- **Worker**：启动 `CommandServer`（TCP Server），接收请求，返回响应。
- **Web**：封装 `RpcClient`，将前端 HTTP 请求转换为 TCP RPC 请求，并处理超时/错误。

推荐的消息格式（JSON 一行一条，便于扩展与排障）：

```json
{"request_id":"uuid","type":"RUN_CASE","payload":{"case_id":"2.1.2"},"timeout_ms":600000}
```

响应格式：

```json
{"request_id":"uuid","ok":true,"data":{"accepted":true}}
```

建议支持的 RPC 类型（覆盖当前 Web 的核心功能）：

- `PING`：探活/就绪检查。
- `GET_STATUS`：返回 Worker 状态（连接状态、当前用例、是否 busy、最近错误等）。
- `RUN_CASE`：执行指定用例（由 Worker 内部映射到 `src/tests/cases.py` 的函数）。
- `RESET_RISK`：等价于现有 Web 的 `/api/control/reset`。
- `DISCONNECT/RECONNECT/PAUSE`：保留现有命令语义（用于软断线/重连/应急暂停）。

执行语义（关键点）：

- Worker 端必须**严格串行**执行（同一时间仅运行一个用例），对并发请求返回明确的 `busy`。
- `RUN_CASE` 的“接收响应”与“用例完成”应解耦：RPC 返回 `accepted/busy`，完成事件通过状态通道推送（见下节）。

#### B. 日志/状态上报 (Worker -> Web)
为了让前端能实时看到 Worker 的日志，Worker 需要将日志“流”回 Web 进程。

推荐采用“SocketIO 单向推送（Worker -> Web）”承载日志与状态：

- **Web**：启动 SocketIO Server（与现有 Web 使用同一端口 5006）。
- **Worker**：作为 SocketIO Client 连接 `localhost:5006`，并推送事件。

事件建议（把“靠日志猜状态”变成“状态可视化”）：

- `new_log`：日志行（复用现有前端消费方式）。
- `worker_status`：心跳与状态摘要（如 `RUNNING/busy/current_case/last_error`）。
- `case_started` / `case_finished`：用例开始/结束（含 case_id、耗时、成功与否、错误摘要）。
- `worker_exit`：Worker 即将退出或捕获到致命错误时的最后上报（可选）。

实现细节要求（保证不反噬交易线程）：

- Worker 侧日志 handler 不应在 `emit()` 内做同步网络发送；应采用“队列 + 后台线程批量发送/限速”，避免行情回调或日志风暴时拖慢引擎。

### 3.3 文件结构变更
以“最少新增文件、最大复用现有结构”为原则：

1.  **复用并改造 `src/worker.py`（优先）**：
    *   作为 Worker 进程入口文件。
    *   负责初始化 `TestEngine`，启动增强后的 RPC Server，配置 SocketIO 日志与状态回传。

2.  **改造 `src/web/app.py`（必须）**：
    *   移除 `TestEngine` 的直接实例化。
    *   增加 `ProcessManager`（管理 Worker 生命周期）与 `RpcClient`（与 Worker 通信）。
    *   `/api/run/<case_id>` 改为调用 `RpcClient.run_case(case_id)`。
    *   `/api/control/reset` 改为调用 `RpcClient.reset_risk()`。

3.  **改造 `src/core/server.py`（建议）**：
    *   从“字符串命令 + 固定集合”扩展为“JSON RPC + 扩展命令集 + 可返回结果”。

4.  **改造 `src/manager.py`（视情况）**：
    *   当前 `TestManager` 是 Web 内部的串行执行器；分离后应迁移到 Worker 或被替代。

## 4. 实施步骤

1.  **切断 Web 与引擎耦合**：Web 不再初始化 `TestEngine`，只保留 UI、HTTP API、SocketIO Server。
2.  **强化 Worker 入口**：在 `src/worker.py` 增加状态机/串行执行器，并暴露 `RUN_CASE/RESET_RISK/GET_STATUS/PING` 等 RPC。
3.  **升级 RPC 协议**：将 `src/core/server.py` 升级为 JSON 请求-响应，Web 侧实现 `RpcClient`。
4.  **实现日志与状态回传**：Worker 通过 SocketIO Client 推送日志与状态事件，Web 统一转发给浏览器。
5.  **联调与回归**：验证以下场景：
    - Worker 正常启动后，Web 能探活并执行用例。
    - 用例执行期间 Web 不阻塞、可持续接收日志。
    - `kill_worker()` 后 Web 仍可响应，并能重启 Worker 恢复执行。

## 5. 预期效果

*   点击“断线/重启”按钮时，Web 界面丝滑流畅，不会卡死。
*   支持两类断线：软断线（RPC `DISCONNECT`）与硬断线（`kill_worker()` 物理中断）。
*   Worker 崩溃或 CTP 卡死时，Web 控制台仍可查看最后日志与状态，并一键重启恢复。
*   重启后全新进程与全新内存空间，最大化降低重连失败与静态污染问题。
