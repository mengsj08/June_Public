#!/usr/bin/env python3
"""Install one canonical skill into Codex and/or Claude discovery roots."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SKILL_NAME = "scientific-pdf-bilingual-reader"
DEFAULT_SOURCE = Path(__file__).resolve().parents[1]
IGNORED_NAMES = {".DS_Store", "__pycache__", ".git", ".pytest_cache"}


def discovery_roots() -> dict[str, Path]:
    codex = Path(os.environ.get("CODEX_SKILLS_DIR", Path.home() / ".agents" / "skills")).expanduser()
    claude = Path(os.environ.get("CLAUDE_SKILLS_DIR", Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude")) / "skills")).expanduser()
    return {"codex": codex, "claude": claude}


def backup_root() -> Path:
    configured = os.environ.get("PDF_READER_SKILL_BACKUP_DIR")
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "Scientific PDF Bilingual Reader" / "skill-backups"


def ignore_copy(_directory: str, names: list[str]) -> set[str]:
    return {
        name for name in names
        if name in IGNORED_NAMES or name.endswith((".pyc", ".pyo"))
    }


def targets(value: str) -> list[str]:
    return ["codex", "claude"] if value == "both" else [value]


def install_one(source: Path, ecosystem: str, *, force: bool, dry_run: bool) -> dict:
    root = discovery_roots()[ecosystem]
    target = root / SKILL_NAME
    source = source.resolve()
    if source == target.resolve():
        return {"ecosystem": ecosystem, "target": str(target), "status": "already_source"}
    if target.exists() and not force:
        raise FileExistsError(f"{target} 已存在；先审阅差异，再用 --force 备份并替换")
    if dry_run:
        return {"ecosystem": ecosystem, "target": str(target), "status": "would_install"}

    root.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}-", dir=root))
    staging = staging_parent / SKILL_NAME
    backup = None
    try:
        shutil.copytree(source, staging, ignore=ignore_copy)
        if not (staging / "SKILL.md").is_file():
            raise RuntimeError("分发副本缺少 SKILL.md")
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup = backup_root() / ecosystem / stamp / SKILL_NAME
            backup.parent.mkdir(parents=True, exist_ok=False)
            target.replace(backup)
        staging.replace(target)
    except Exception:
        if backup and backup.exists() and not target.exists():
            backup.replace(target)
        raise
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)
    return {
        "ecosystem": ecosystem,
        "target": str(target),
        "backup": str(backup) if backup else None,
        "status": "installed",
    }


def install(source: Path, target_set: str, *, force: bool, dry_run: bool) -> list[dict]:
    if not (source / "SKILL.md").is_file():
        raise FileNotFoundError(f"不是有效 Skill 目录：{source}")
    selected = targets(target_set)
    roots = discovery_roots()
    conflicts = [
        roots[item] / SKILL_NAME for item in selected
        if (roots[item] / SKILL_NAME).exists()
        and source.resolve() != (roots[item] / SKILL_NAME).resolve()
    ]
    if conflicts and not force:
        joined = "、".join(str(path) for path in conflicts)
        raise FileExistsError(f"以下目标已存在：{joined}；未写入任何生态。审阅后用 --force 备份替换")
    results = [install_one(source, item, force=force, dry_run=dry_run) for item in selected]
    for result in results:
        label = "Codex" if result["ecosystem"] == "codex" else "Claude Code"
        print(f"{label}: {result['status']} → {result['target']}")
        if result.get("backup"):
            print(f"  旧版备份：{result['backup']}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="安装科研长 PDF 双语阅读器 Skill")
    parser.add_argument("--targets", choices=("codex", "claude", "both"), default="both")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--force", action="store_true", help="备份并替换已安装版本")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    install(args.source.expanduser(), args.targets, force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
