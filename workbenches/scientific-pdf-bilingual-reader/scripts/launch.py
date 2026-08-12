#!/usr/bin/env python3
"""Launch the workbench under the shared managed Python runtime."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bootstrap import load_lock, probe_runtime, runtime_paths  # noqa: E402


DEFAULT_PORT = 8765
FALLBACK_PORT = 8876


def port_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, port))
        return True
    except OSError:
        return False


def resolve_port(host: str, requested: int | None) -> int:
    if requested is not None:
        return requested
    for port in (DEFAULT_PORT, *range(FALLBACK_PORT, FALLBACK_PORT + 20)):
        if port_available(host, port):
            if port != DEFAULT_PORT:
                print(f"默认端口 {DEFAULT_PORT} 已占用；自动使用 {port}。", flush=True)
            return port
    raise RuntimeError("本机端口 8765、8876–8895 均被占用；请关闭冲突服务或用 --port 指定端口")


def main() -> None:
    parser = argparse.ArgumentParser(description="在受管 Python 3.12 中启动工作台")
    parser.add_argument("command", nargs="?", choices=("start", "doctor"), default="start")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    paths = runtime_paths()

    if args.command == "doctor":
        command = [sys.executable, str(ROOT / "scripts" / "bootstrap.py"), "doctor"]
        raise SystemExit(subprocess.run(command).returncode)

    report = probe_runtime(paths, load_lock(), check_assets=True)
    if not report["ready"]:
        command = f"{sys.executable} {ROOT / 'scripts' / 'bootstrap.py'} install"
        print("受管运行时尚未就绪。请先确认长期约 1.0–1.3 GB 磁盘占用，然后运行：")
        print(command)
        raise SystemExit(2)

    port = resolve_port(args.host, args.port)
    command = [
        str(paths["venv_python"]), str(ROOT / "scripts" / "workbench.py"),
        "start", "--host", args.host, "--port", str(port),
    ]
    if args.open:
        command.append("--open")
    env = os.environ.copy()
    env.update({
        "PDF_READER_RUNTIME_DIR": str(paths["root"]),
        "PDF_READER_PDF2ZH": str(paths["pdf2zh"]),
        "PDF_READER_MANAGED_LAUNCH": "1",
    })
    if args.dry_run:
        print(" ".join(command))
        return
    os.execve(command[0], command, env)


if __name__ == "__main__":
    main()
