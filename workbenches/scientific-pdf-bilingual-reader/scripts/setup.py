#!/usr/bin/env python3
"""One command setup: install the skill and provision its shared runtime."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bootstrap import install as install_runtime  # noqa: E402
from install_skill import DEFAULT_SOURCE, install as install_skill  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex + Claude 双生态安装及运行时自举")
    parser.add_argument("--targets", choices=("codex", "claude", "both"), default="both")
    parser.add_argument("--force", action="store_true", help="备份并替换已有 Skill")
    parser.add_argument("--yes", action="store_true", help="确认约 1.0–1.5 GB 下载和安装")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-assets", action="store_true")
    args = parser.parse_args()

    confirmed = args.yes
    if not args.dry_run and not confirmed:
        print("将安装到 Codex/Claude Skill 目录，并创建长期约 1.0–1.3 GB 的共享受管运行时。")
        print("不使用 sudo，不修改 shell 配置，不读取任何模型凭据。")
        if not sys.stdin.isatty() or input("继续？[y/N] ").strip().lower() not in {"y", "yes"}:
            raise SystemExit("已取消；未安装 Skill 或运行时。")
        confirmed = True

    install_skill(DEFAULT_SOURCE, args.targets, force=args.force, dry_run=args.dry_run)
    install_runtime(yes=confirmed, dry_run=args.dry_run, skip_assets=args.skip_assets)
    if not args.dry_run:
        print("安装完成。现在可在 Codex 或 Claude 中说：启动长 PDF 双语阅读器。")


if __name__ == "__main__":
    main()
