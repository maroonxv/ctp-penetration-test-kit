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
    Send command to the running test process via TCP.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((RPC_HOST, RPC_PORT))
            s.sendall(cmd.encode('utf-8'))
            data = s.recv(1024)
            print(f"Sent: {cmd}, Received: {data.decode('utf-8')}")
    except ConnectionRefusedError:
        print(f"Error: Could not connect to {RPC_HOST}:{RPC_PORT}. Is the test running?")
        sys.exit(1)
    except Exception as e:
        print(f"Error sending command: {e}")
        sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print("Usage: python control.py <command>")
        print("Commands: DISCONNECT, RECONNECT, PAUSE")
        sys.exit(1)

    cmd = sys.argv[1].upper()
    valid_cmds = ["DISCONNECT", "RECONNECT", "PAUSE"]
    
    if cmd not in valid_cmds:
        print(f"Invalid command. Available: {valid_cmds}")
        sys.exit(1)
        
    send_command(cmd)

if __name__ == "__main__":
    main()
