"""为正式长任务提供统一的 tmux 后台启动和日志管理。"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence


def launch_in_tmux(
    output_root: Path,
    session_prefix: str,
    arguments: Sequence[str] | None = None,
) -> str:
    """在独立 tmux session 中重启当前命令，成功后删除本次日志。"""
    tmux_executable = shutil.which("tmux")
    if tmux_executable is None:
        raise RuntimeError(
            "正式运行默认需要 tmux；请安装 tmux，或显式使用 --foreground。"
        )

    command_arguments = list(sys.argv[1:] if arguments is None else arguments)
    if "--foreground" not in command_arguments:
        command_arguments.append("--foreground")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_name = f"{session_prefix}_{timestamp}_{os.getpid()}"
    log_directory = output_root / "log"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / f"{session_name}.log"

    foreground_command = [
        sys.executable,
        str(Path(sys.argv[0]).resolve()),
        *command_arguments,
    ]
    shell_command = _logged_shell_command(foreground_command, log_path)
    subprocess.run(
        [
            tmux_executable,
            "new-session",
            "-d",
            "-s",
            session_name,
            "bash",
            "-lc",
            shell_command,
        ],
        check=True,
    )

    print(f"tmux session: {session_name}")
    print(f"log: {log_path}")
    print(f"attach: tmux attach -t {session_name}")
    return session_name


def _logged_shell_command(command: Sequence[str], log_path: Path) -> str:
    """构造保留 Python 退出码且仅在成功时删除日志的 Bash 命令。"""
    command_text = shlex.join(command)
    quoted_log_path = shlex.quote(str(log_path))
    return (
        "set -o pipefail; "
        f"{command_text} 2>&1 | tee {quoted_log_path}; "
        "status=${PIPESTATUS[0]}; "
        f"if [ \"$status\" -eq 0 ]; then rm -f -- {quoted_log_path}; fi; "
        "exit \"$status\""
    )
