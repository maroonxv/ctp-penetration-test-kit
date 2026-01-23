# 方案：捕获 CTP 底层日志并推送到前端

## 问题分析
当前 `src/socket_handler.py` 仅挂载在 Python 的 **Root Logger** 上。
而 `vnpy` 及其底层 CTP 接口产生的日志（如您看到的 `INFO | CTPTEST | ...`）通常是由 `vnpy.trader.utility.get_file_logger` 或类似机制生成的独立 Logger，或者直接使用了 `print` / 标准输出流。

如果这些日志通过 `logging` 模块发出但未传播（propagate）到 Root Logger，或者它们直接写入了 stdout/stderr，那么当前的 `SocketIOHandler` 就无法捕获它们。

## 解决方案

### 方案 A：重定向标准输出 (推荐用于捕获所有 print 和 C++层面的输出)
由于 CTP 的底层库（C++封装）有时会直接向 stdout 打印信息，且 vnpy 的某些组件可能使用 `print`，最彻底的方法是劫持 `sys.stdout` 和 `sys.stderr`。

1.  **原理**：
    创建自定义的 `StreamToSocket` 类，模拟文件对象的 `write` 和 `flush` 方法。
    将其赋值给 `sys.stdout` 和 `sys.stderr`。
2.  **流程**：
    *   `StreamToSocket.write(msg)` -> 触发 `socketio.emit`。
    *   同时保留原始 stdout 的功能（写入控制台），以免终端失去输出。

### 方案 B：挂载 SocketHandler 到 `vnpy` 的 Logger (推荐用于捕获 vnpy 结构化日志)
如果 vnpy 使用了标准的 `logging` 库，我们可以显式地将我们的 `socket_handler` 添加到 vnpy 的 logger 实例中。

1.  **原理**：
    vnpy 通常使用名为 `"vnpy"` 或 `"vnpy.trader"` 的 logger。
    我们需要在 `src/web/app.py` 初始化时，获取这些特定的 Logger 并添加 handler。
2.  **实施**：
    ```python
    logging.getLogger("vnpy").addHandler(socket_handler)
    logging.getLogger("vnpy.trader").addHandler(socket_handler)
    ```

## 综合实施建议

为了确保“万无一失”，建议**同时采用**以下两个步骤：

1.  **Logger 挂载增强**：
    在 `src/web/app.py` 中，不仅将 `socket_handler` 加到 Root Logger，还显式加到 `vnpy` 相关的 Logger 上。这将解决 `Terminal#92-94` 这种由 vnpy 框架发出的日志。

2.  **Stdout/Stderr 劫持 (可选但建议)**：
    如果某些底层 CTP 报错是通过 `printf` 直接输出的，Python 的 logging 无法捕获。劫持 `sys.stdout` 可以将这些信息也显示在 Web 端。

### 预期效果
实施后，所有在终端中看到的文字（包括白色 INFO 和 红色 ERROR），都会实时出现在网页的黑色日志框中。

## 下一步
我将优先执行 **方案 B (Logger 挂载增强)**，因为这风险最小且能覆盖绝大多数 vnpy 日志。如果仍有遗漏，再实施方案 A。
