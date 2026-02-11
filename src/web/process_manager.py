import os
import sys
import subprocess
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORKER_ENTRY = os.path.join(PROJECT_ROOT, "src", "worker", "controller.py")


class ProcessManager:
    def __init__(self):
        self.process = None
        self.disconnect_mode = False  # 断线模式：阻止自动重启

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start_worker(self, force: bool = False) -> bool:
        """启动 Worker 进程
        
        Args:
            force: 强制启动，忽略断线模式
        """
        # 断线模式下不自动启动（除非强制）
        if self.disconnect_mode and not force:
            return False
            
        if self.is_running():
            return True

        env = os.environ.copy()
        env.setdefault("PYTHONPATH", PROJECT_ROOT)

        self.process = subprocess.Popen(
            [sys.executable, WORKER_ENTRY],
            cwd=PROJECT_ROOT,
            env=env,
        )
        return True

    def kill_worker(self) -> bool:
        if not self.process:
            return True
        try:
            self.process.kill()
        except Exception:
            pass
        return True

    def restart_worker(self) -> bool:
        self.disconnect_mode = False  # 重启时退出断线模式
        self.kill_worker()
        time.sleep(0.2)
        return self.start_worker(force=True)
    
    def enter_disconnect_mode(self):
        """进入断线模式，阻止自动重启"""
        self.disconnect_mode = True
    
    def exit_disconnect_mode(self):
        """退出断线模式"""
        self.disconnect_mode = False
