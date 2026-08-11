#!/usr/bin/env python3
"""Launch the workbench under the shared managed Python runtime."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bootstrap import load_lock, probe_runtime, runtime_paths  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="在受管 Python 3.12 中启动工作台")
    parser.add_argument("command", nargs="?", choices=("start", "doctor"), default="start")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
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

    command = [
        str(paths["venv_python"]), str(ROOT / "scripts" / "workbench.py"),
        "start", "--host", args.host, "--port", str(args.port),
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
