#!/usr/bin/env python3
"""All-or-rollback installation for the four official PDF task artifacts."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Callable


def content_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace_path(source: Path, destination: Path) -> None:
    source.replace(destination)


def next_version_dir(folder: Path, identity: str) -> Path:
    base = folder / "versions" / f"before-{Path(identity).name}"
    candidate = base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = base.with_name(f"{base.name}-{suffix}")
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def install_artifact_set(
    folder: Path,
    prepared: dict[str, Path],
    backup_dir: Path,
    *,
    replacer: Callable[[Path, Path], None] = replace_path,
) -> None:
    """Install every prepared file; restore the whole old set on any failure."""
    staging = Path(tempfile.mkdtemp(prefix=".repair-install-", dir=folder))
    try:
        staged = {}
        for name, source in prepared.items():
            target = staging / name
            shutil.copy2(source, target)
            if content_sha256(target) != content_sha256(source):
                raise RuntimeError(f"候选安装暂存校验失败：{name}")
            staged[name] = target
        try:
            for name in prepared:
                replacer(staged[name], folder / name)
        except Exception as install_error:
            rollback_errors = []
            for name in prepared:
                try:
                    restore = staging / f"rollback-{name}"
                    shutil.copy2(backup_dir / name, restore)
                    replace_path(restore, folder / name)
                except Exception as rollback_error:
                    rollback_errors.append(f"{name}: {rollback_error}")
            if rollback_errors:
                raise RuntimeError(
                    "候选安装失败且回滚不完整：" + "；".join(rollback_errors)
                ) from install_error
            raise RuntimeError("候选安装失败，已恢复全部旧正式文件") from install_error
    finally:
        shutil.rmtree(staging, ignore_errors=True)
