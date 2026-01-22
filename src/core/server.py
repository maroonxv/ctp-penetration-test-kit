import socket
import threading
from src import config
from src.logger import log_info, log_error

class CommandServer(threading.Thread):
    """
    RPC 服务器，用于接收来自外部脚本 (scripts/control.py) 的控制指令。
    指令: DISCONNECT, RECONNECT, PAUSE
    """
    def __init__(self, context):
        super().__init__()
        self.context = context  # 应提供方法: disconnect(), reconnect(), pause()
        self.host = config.RPC_HOST
        self.port = config.RPC_PORT
        self.running = True
        self.server_socket = None

    def run(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(1)
            log_info(f"指令服务器正在监听 {self.host}:{self.port}")

            while self.running:
                try:
                    self.server_socket.settimeout(1.0)
                    client_socket, addr = self.server_socket.accept()
                    with client_socket:
                        data = client_socket.recv(1024).decode('utf-8').strip()
                        if data:
                            log_info(f"RPC 收到指令: {data}")
                            self.process_command(data)
                            client_socket.sendall(b"OK")
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        log_error(f"RPC 服务器接收错误: {e}")

        except Exception as e:
            log_error(f"RPC 服务器启动错误: {e}")
        finally:
            self.stop()

    def process_command(self, cmd: str):
        cmd = cmd.upper()
        if cmd == "DISCONNECT":
            self.context.disconnect()
        elif cmd == "RECONNECT":
            self.context.reconnect()
        elif cmd == "PAUSE":
            self.context.pause()
        else:
            log_error(f"未知 RPC 指令: {cmd}")

    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        log_info("指令服务器已停止。")
