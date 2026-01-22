import sys
import socket
import os

# Add project root to path to import config if needed, 
# but for simple script hardcoding port is fine or relative import if run from root.
# Let's try to be standalone or assume run from root.

RPC_HOST = "127.0.0.1"
RPC_PORT = 9999

def send_command(cmd: str):
    """
    通过 TCP 发送指令到运行中的测试进程。
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((RPC_HOST, RPC_PORT))
            s.sendall(cmd.encode('utf-8'))
            data = s.recv(1024)
            print(f"已发送: {cmd}, 收到: {data.decode('utf-8')}")
    except ConnectionRefusedError:
        print(f"错误: 无法连接到 {RPC_HOST}:{RPC_PORT}。测试程序运行了吗？")
        sys.exit(1)
    except Exception as e:
        print(f"发送指令错误: {e}")
        sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print("用法: python control.py <command>")
        print("指令: DISCONNECT, RECONNECT, PAUSE")
        sys.exit(1)

    cmd = sys.argv[1].upper()
    valid_cmds = ["DISCONNECT", "RECONNECT", "PAUSE"]
    
    if cmd not in valid_cmds:
        print(f"无效指令。可用: {valid_cmds}")
        sys.exit(1)
        
    send_command(cmd)

if __name__ == "__main__":
    main()
