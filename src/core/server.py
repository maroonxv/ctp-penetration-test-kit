import socket
import threading
from src import read_config as config
from src.logger import log_info, log_error

class CommandServer(threading.Thread):
    """
    RPC Server to receive control commands from external script (scripts/control.py).
    Commands: DISCONNECT, RECONNECT, PAUSE
    """
    def __init__(self, context):
        super().__init__()
        self.context = context  # Should provide methods: disconnect(), reconnect(), pause()
        self.host = config.RPC_HOST
        self.port = config.RPC_PORT
        self.running = True
        self.server_socket = None

    def run(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(1)
            log_info(f"Command Server listening on {self.host}:{self.port}")

            while self.running:
                try:
                    self.server_socket.settimeout(1.0)
                    client_socket, addr = self.server_socket.accept()
                    with client_socket:
                        data = client_socket.recv(1024).decode('utf-8').strip()
                        if data:
                            log_info(f"RPC Received command: {data}")
                            self.process_command(data)
                            client_socket.sendall(b"OK")
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        log_error(f"RPC Server accept error: {e}")

        except Exception as e:
            log_error(f"RPC Server startup error: {e}")
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
            log_error(f"Unknown RPC command: {cmd}")

    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        log_info("Command Server stopped.")
