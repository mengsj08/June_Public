#!/usr/bin/env python3
"""Provision and inspect the independent PaddleOCR runtime.

This module deliberately keeps PaddleOCR out of the translation runtime.  It is
safe to import from the web server because runtime inspection happens in a
separate process and does not import Paddle itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_FILE = ROOT / "references" / "ocr-runtime-lock.json"


def load_lock() -> dict:
    return json.loads(LOCK_FILE.read_text(encoding="utf-8"))


def runtime_root() -> Path:
    configured = os.environ.get("PDF_READER_OCR_RUNTIME_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "Scientific PDF Bilingual Reader" / "ocr-runtime-v1"


def runtime_paths() -> dict[str, Path]:
    base = runtime_root()
    return {
        "root": base,
        "tools": base / "tools",
        "uv": base / "tools" / "uv",
        "python_dir": base / "python",
        "venv": base / "venv",
        "venv_python": base / "venv" / "bin" / "python",
        "cache": base / "cache" / "uv",
        "models": base / "models",
        "manifest": base / "runtime-manifest.json",
        "assets_manifest": base / "model-assets.json",
        "installing": base / "installing.json",
        "install_log": base / "install.log",
    }


def runtime_environment(paths: dict[str, Path]) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "UV_CACHE_DIR": str(paths["cache"]),
        "UV_PYTHON_INSTALL_DIR": str(paths["python_dir"]),
        "UV_PYTHON_INSTALL_BIN": "0",
        "UV_NO_MODIFY_PATH": "1",
        "UV_NO_CONFIG": "1",
        "PADDLE_PDX_CACHE_HOME": str(paths["models"]),
        # Retain the old name for the worker boundary and older PaddleX builds.
        "PADDLEX_HOME": str(paths["models"]),
        "PADDLE_PDX_MODEL_SOURCE": env.get("PADDLE_PDX_MODEL_SOURCE", "BOS"),
        "FLAGS_use_mkldnn": "0",
    })
    return env


def _run(command: list[str], *, env: dict[str, str], dry_run: bool = False) -> None:
    print("+ " + " ".join(command), flush=True)
    if not dry_run:
        subprocess.run(command, check=True, env=env)


def _install_uv(paths: dict[str, Path], lock: dict, dry_run: bool) -> Path:
    if paths["uv"].is_file():
        return paths["uv"]
    existing = shutil.which("uv")
    if existing:
        print(f"使用现有 uv：{existing}")
        return Path(existing)
    url = f"https://astral.sh/uv/{lock['uv_version']}/install.sh"
    print(f"下载官方 uv {lock['uv_version']} 安装器：{url}")
    if dry_run:
        return paths["uv"]
    paths["tools"].mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pdf-reader-ocr-uv-") as temp:
        script = Path(temp) / "install.sh"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"scientific-pdf-bilingual-reader-ocr/{lock['runtime_version']}"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            script.write_bytes(response.read())
        env = os.environ.copy()
        env.update({"UV_UNMANAGED_INSTALL": str(paths["tools"]), "UV_NO_MODIFY_PATH": "1"})
        subprocess.run(["sh", str(script)], check=True, env=env)
    if not paths["uv"].is_file():
        raise RuntimeError(f"uv 安装完成但未找到 {paths['uv']}")
    return paths["uv"]


def probe_runtime(check_assets: bool = False) -> dict:
    paths = runtime_paths()
    lock = load_lock()
    report = {
        "ready": False,
        "runtime_root": str(paths["root"]),
        "platform": sys.platform,
        "architecture": platform.machine(),
        "managed_python": str(paths["venv_python"]) if paths["venv_python"].is_file() else None,
        "python_version": None,
        "imports": {},
        "models": {"ready": False},
        "manifest": str(paths["manifest"]) if paths["manifest"].is_file() else None,
        "lock_match": False,
        "install_incomplete": paths["installing"].is_file(),
        "supported": sys.platform == "darwin" and platform.machine() in {"arm64", "x86_64"},
        "storage_estimate": lock["storage_estimate"],
    }
    manifest = None
    if paths["manifest"].is_file():
        try:
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            report["lock_match"] = manifest.get("lock_sha256") == hashlib.sha256(LOCK_FILE.read_bytes()).hexdigest()
        except (OSError, json.JSONDecodeError):
            pass
    if paths["assets_manifest"].is_file():
        try:
            assets = json.loads(paths["assets_manifest"].read_text(encoding="utf-8"))
            report["models"] = {
                "ready": bool(assets.get("asset_count", 0)),
                "asset_count": assets.get("asset_count", 0),
                "manifest": str(paths["assets_manifest"]),
            }
        except (OSError, json.JSONDecodeError):
            pass
    python = paths["venv_python"]
    if not python.is_file():
        return report
    if not check_assets:
        report["python_version"] = manifest.get("python") if manifest else None
        report["imports"] = {module: True for module in lock["required_imports"]} if manifest else {}
        report["ready"] = (
            report["supported"]
            and bool(report["python_version"] and report["python_version"].startswith("3.12."))
            and report["models"].get("ready", False)
            and report["lock_match"]
            and not report["install_incomplete"]
        )
        return report
    probe_code = """
import importlib
import json
import platform

mods = {}
for name in ['paddle', 'paddleocr', 'paddlex', 'fitz', 'cv2']:
    try:
        importlib.import_module(name)
        mods[name] = True
    except Exception:
        mods[name] = False
print(json.dumps({'python': platform.python_version(), 'imports': mods}))
"""
    try:
        checked = subprocess.run(
            [str(python), "-c", probe_code], capture_output=True, text=True,
            timeout=240, env=runtime_environment(paths),
        )
        if checked.returncode == 0:
            payload = json.loads(checked.stdout.strip().splitlines()[-1])
            report["python_version"] = payload["python"]
            report["imports"] = payload["imports"]
        else:
            report["probe_error"] = (checked.stderr or checked.stdout)[-1000:]
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        report["probe_error"] = str(exc)
    if check_assets and report["models"].get("ready"):
        command = [
            str(python), str(ROOT / "scripts" / "ocr_worker.py"), "check-assets",
            "--manifest", str(paths["assets_manifest"]),
        ]
        checked = subprocess.run(command, capture_output=True, text=True, timeout=180, env=runtime_environment(paths))
        report["models"]["ready"] = checked.returncode == 0
        if checked.returncode:
            report["models"]["error"] = (checked.stderr or checked.stdout)[-1000:]
    report["ready"] = (
        report["supported"]
        and bool(report["python_version"] and report["python_version"].startswith("3.12."))
        and bool(report["imports"] and all(report["imports"].values()))
        and report["models"].get("ready", False)
        and report["lock_match"]
        and not report["install_incomplete"]
    )
    return report


def _build_manifest(paths: dict[str, Path], lock: dict) -> dict:
    names = ["paddlepaddle", "paddleocr", "paddlex", "PyMuPDF"]
    code = f"""
import json
import platform
from importlib.metadata import version

names = {names!r}
payload = {{
    "python": platform.python_version(),
    "packages": {{name: version(name) for name in names}},
}}
print(json.dumps(payload))
"""
    completed = subprocess.run(
        [str(paths["venv_python"]), "-c", code], capture_output=True, text=True,
        check=False, timeout=60, env=runtime_environment(paths),
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout)[-1000:]
        raise RuntimeError(f"OCR 运行时版本清单读取失败（returncode={completed.returncode}）：{detail}")
    return {
        "schema_version": 1,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "runtime_root": str(paths["root"]),
        "platform": sys.platform,
        "architecture": platform.machine(),
        "lock_sha256": hashlib.sha256(LOCK_FILE.read_bytes()).hexdigest(),
        "lock": lock,
        **json.loads(completed.stdout),
    }


def install(*, yes: bool, dry_run: bool = False) -> None:
    lock = load_lock()
    paths = runtime_paths()
    print("PaddleOCR 独立受管运行时安装计划：")
    print(f"  位置：{paths['root']}")
    print(f"  Python：{lock['python']}（与翻译引擎隔离，不使用系统 Python）")
    print("  组件：PaddlePaddle 3.3.1、PaddleOCR 3.7.0、英文 PP-OCRv5 mobile 模型")
    print("  预计长期磁盘占用：约 1–2 GB；安装后缓存会清理。")
    print("  不使用 sudo，不改 shell 配置，不读取模型登录凭据。")
    if not yes and not dry_run:
        if not sys.stdin.isatty() or input("继续安装？[y/N] ").strip().lower() not in {"y", "yes"}:
            raise SystemExit("已取消；未修改 OCR 运行时。")
    if not (sys.platform == "darwin" and platform.machine() in {"arm64", "x86_64"}):
        raise SystemExit("OCR v1 当前只验收 macOS；此平台不会安装。")
    if dry_run:
        print("[dry-run] 不下载、不写入。")
    else:
        paths["root"].mkdir(parents=True, exist_ok=True)
        paths["cache"].mkdir(parents=True, exist_ok=True)
        paths["models"].mkdir(parents=True, exist_ok=True)
        paths["installing"].write_text(json.dumps({
            "started_at": datetime.now(timezone.utc).isoformat(), "lock": lock,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    uv = _install_uv(paths, lock, dry_run)
    env = runtime_environment(paths)
    _run([str(uv), "python", "install", lock["python"], "--install-dir", str(paths["python_dir"]), "--no-bin"], env=env, dry_run=dry_run)
    if not paths["venv_python"].is_file() or dry_run:
        _run([str(uv), "venv", str(paths["venv"]), "--python", lock["python"], "--managed-python"], env=env, dry_run=dry_run)
    _run([str(uv), "pip", "install", "--python", str(paths["venv_python"]), *lock["packages"]], env=env, dry_run=dry_run)
    # Capture pinned package versions before the heavier model initialization.
    manifest_payload = None if dry_run else _build_manifest(paths, lock)
    _run([
        str(paths["venv_python"]), str(ROOT / "scripts" / "ocr_worker.py"), "prefetch",
        "--manifest", str(paths["assets_manifest"]),
    ], env=env, dry_run=dry_run)
    if dry_run:
        _run([str(uv), "cache", "clean"], env=env, dry_run=True)
        print("[dry-run] OCR 安装计划检查完成。")
        return
    temp = paths["manifest"].with_suffix(".tmp")
    temp.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _run([str(uv), "cache", "clean"], env=env)
    temp.replace(paths["manifest"])
    paths["installing"].unlink(missing_ok=True)
    report = probe_runtime(check_assets=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ready"]:
        raise SystemExit("OCR 运行时安装完成，但自检未通过。请保留上面的可核对错误。")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("doctor", "install"))
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-assets", action="store_true")
    args = parser.parse_args()
    if args.command == "doctor":
        print(json.dumps(probe_runtime(args.check_assets), ensure_ascii=False, indent=2))
    else:
        install(yes=args.yes, dry_run=args.dry_run)
