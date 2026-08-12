"""外部进程管理工具。

业务 Service 不直接调用 subprocess.Popen；FFmpeg 等长期进程统一经由这里启动和回收。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, Thread


@dataclass
class ManagedProcess:
    """被托管的外部进程状态。"""

    process_id: str
    command: list[str]
    process: subprocess.Popen
    stderr_lines: list[str] = field(default_factory=list)

    @property
    def pid(self) -> int:
        """返回系统 PID。"""

        return self.process.pid

    @property
    def exit_code(self) -> int | None:
        """返回进程退出码；仍在运行时为 None。"""

        return self.process.poll()

    @property
    def running(self) -> bool:
        """进程是否仍在运行。"""

        return self.process.poll() is None


class ProcessManager:
    """通用外部进程生命周期管理器。"""

    def __init__(self, stderr_limit: int = 200) -> None:
        self._processes: dict[str, ManagedProcess] = {}
        self._stderr_limit = stderr_limit
        self._lock = Lock()

    def start(self, process_id: str, command: list[str], cwd: str | None = None) -> ManagedProcess:
        """启动进程并开始采集 stderr。"""

        with self._lock:
            if process_id in self._processes and self._processes[process_id].running:
                raise ValueError(f"process already running: {process_id}")

            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            managed = ManagedProcess(process_id=process_id, command=command, process=process)
            self._processes[process_id] = managed
            Thread(target=self._collect_stderr, args=(managed,), daemon=True).start()
            return managed

    def get(self, process_id: str) -> ManagedProcess:
        """获取已托管进程。"""

        with self._lock:
            process = self._processes.get(process_id)
            if process is None:
                raise KeyError(f"process not found: {process_id}")
            return process

    def stop(self, process_id: str, timeout_seconds: float = 5.0) -> ManagedProcess | None:
        """优雅停止进程，超时后强制结束。"""

        with self._lock:
            managed = self._processes.get(process_id)
        if managed is None:
            return None
        if managed.running:
            managed.process.terminate()
            try:
                managed.process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                managed.process.kill()
                managed.process.wait(timeout=timeout_seconds)
        with self._lock:
            self._processes.pop(process_id, None)
        return managed

    def stop_all(self, timeout_seconds: float = 5.0) -> None:
        """停止全部托管进程。"""

        for process_id in list(self._processes):
            self.stop(process_id, timeout_seconds)

    def _collect_stderr(self, managed: ManagedProcess) -> None:
        """后台采集 stderr，保留最近若干行用于故障诊断。"""

        if managed.process.stderr is None:
            return
        for line in managed.process.stderr:
            text = line.rstrip()
            managed.stderr_lines.append(text)
            if len(managed.stderr_lines) > self._stderr_limit:
                del managed.stderr_lines[: len(managed.stderr_lines) - self._stderr_limit]


def ensure_parent_dir(path: str) -> None:
    """确保文件父目录存在。"""

    Path(path).parent.mkdir(parents=True, exist_ok=True)
