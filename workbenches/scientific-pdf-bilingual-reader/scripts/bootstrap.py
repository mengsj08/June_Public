#!/usr/bin/env python3
"""Provision and inspect the shared managed Python 3.12 runtime."""

from __future__ import annotations

import argparse
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
LOCK_FILE = ROOT / "references" / "runtime-lock.json"


def load_lock() -> dict:
    return json.loads(LOCK_FILE.read_text(encoding="utf-8"))


def runtime_root() -> Path:
    configured = os.environ.get("PDF_READER_RUNTIME_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "Scientific PDF Bilingual Reader" / "runtime-v1"


def runtime_paths() -> dict[str, Path]:
    base = runtime_root()
    return {
        "root": base,
        "tools": base / "tools",
        "uv": base / "tools" / "uv",
        "python_dir": base / "python",
        "venv": base / "venv",
        "venv_python": base / "venv" / "bin" / "python",
        "pdf2zh": base / "venv" / "bin" / "pdf2zh",
        "cache": base / "cache" / "uv",
        "manifest": base / "runtime-manifest.json",
        "installing": base / "installing.json",
    }


def uv_environment(paths: dict[str, Path]) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "UV_CACHE_DIR": str(paths["cache"]),
        "UV_PYTHON_INSTALL_DIR": str(paths["python_dir"]),
        "UV_PYTHON_INSTALL_BIN": "0",
        "UV_NO_MODIFY_PATH": "1",
        "UV_NO_CONFIG": "1",
    })
    return env


def run(command: list[str], *, env: dict[str, str] | None = None, dry_run: bool = False) -> None:
    print("+ " + " ".join(command), flush=True)
    if dry_run:
        return
    subprocess.run(command, check=True, env=env)


def install_uv(paths: dict[str, Path], lock: dict, dry_run: bool) -> Path:
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
    with tempfile.TemporaryDirectory(prefix="pdf-reader-uv-") as temp:
        script = Path(temp) / "install.sh"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"scientific-pdf-bilingual-reader-bootstrap/{lock['runtime_version']}"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            script.write_bytes(response.read())
        env = os.environ.copy()
        env.update({
            "UV_UNMANAGED_INSTALL": str(paths["tools"]),
            "UV_NO_MODIFY_PATH": "1",
        })
        run(["sh", str(script)], env=env)
    if not paths["uv"].is_file():
        raise RuntimeError(f"uv 安装完成但未找到 {paths['uv']}")
    return paths["uv"]


def probe_runtime(paths: dict[str, Path], lock: dict, check_assets: bool = True) -> dict:
    engine = paths["pdf2zh"]
    python = paths["venv_python"]
    report = {
        "ready": False,
        "runtime_root": str(paths["root"]),
        "platform": sys.platform,
        "architecture": platform.machine(),
        "managed_python": str(python) if python.is_file() else None,
        "pdf2zh": str(engine) if engine.is_file() else None,
        "python_version": None,
        "imports": {},
        "assets": {"ready": False, "skipped": not check_assets},
        "manifest": str(paths["manifest"]) if paths["manifest"].is_file() else None,
        "lock_match": False,
        "install_incomplete": paths["installing"].is_file(),
    }
    if paths["manifest"].is_file():
        try:
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
            report["lock_match"] = manifest.get("lock_sha256") == hashlib.sha256(LOCK_FILE.read_bytes()).hexdigest()
        except (OSError, json.JSONDecodeError):
            report["lock_match"] = False
    if not python.is_file() or not engine.is_file():
        return report
    version = subprocess.run(
        [str(python), "-c", "import platform; print(platform.python_version())"],
        capture_output=True, text=True, timeout=30,
    )
    report["python_version"] = version.stdout.strip() if version.returncode == 0 else None
    for module in lock["required_imports"]:
        try:
            checked = subprocess.run(
                [str(python), "-c", f"import {module}"],
                capture_output=True, text=True, timeout=180,
            )
            report["imports"][module] = checked.returncode == 0
        except subprocess.TimeoutExpired:
            report["imports"][module] = False
            report.setdefault("import_errors", {})[module] = "首次加载超过 180 秒"
    if check_assets:
        checked = subprocess.run(
            [str(python), str(ROOT / "scripts" / "prefetch_assets.py"), "--check", "--summary-json"],
            capture_output=True, text=True, timeout=120,
        )
        try:
            start = checked.stdout.find("{")
            report["assets"] = json.loads(checked.stdout[start:])
        except json.JSONDecodeError:
            report["assets"] = {"ready": False, "error": checked.stderr[-500:] or checked.stdout[-500:]}
    report["ready"] = (
        bool(report["python_version"] and report["python_version"].startswith("3.12."))
        and all(report["imports"].values())
        and (report["assets"].get("ready", False) or not check_assets)
        and paths["manifest"].is_file()
        and report["lock_match"]
        and not report["install_incomplete"]
    )
    return report


def build_manifest(paths: dict[str, Path], lock: dict) -> dict:
    code = (
        "import json, platform; from importlib.metadata import version; "
        "names=['pdf2zh','babeldoc','PyMuPDF','onnxruntime','opencv-python-headless','numpy','tencentcloud-sdk-python-tmt']; "
        "print(json.dumps({'python':platform.python_version(),'packages':{n:version(n) for n in names}}))"
    )
    completed = subprocess.run(
        [str(paths["venv_python"]), "-c", code], capture_output=True, text=True, check=True, timeout=60,
    )
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


def install(*, yes: bool, dry_run: bool, skip_assets: bool) -> None:
    lock = load_lock()
    paths = runtime_paths()
    print("受管运行时安装计划：")
    print(f"  位置：{paths['root']}")
    print(f"  Python：{lock['python']}（uv 管理，不使用系统 Python）")
    print(f"  引擎：pdf2zh {lock['pdf2zh']['version']} @ {lock['pdf2zh']['commit'][:12]}")
    print("  预计长期磁盘占用：约 1.0–1.3 GB（运行时和预下载资产；临时安装缓存完成后清理）")
    print("  不使用 sudo，不改 shell 配置，不读取模型登录凭据。")
    if not yes and not dry_run:
        if not sys.stdin.isatty() or input("继续安装？[y/N] ").strip().lower() not in {"y", "yes"}:
            raise SystemExit("已取消；未修改运行时。")

    if dry_run:
        print("[dry-run] 不下载、不写入。")
    else:
        paths["root"].mkdir(parents=True, exist_ok=True)
        paths["cache"].mkdir(parents=True, exist_ok=True)
        paths["installing"].write_text(json.dumps({
            "started_at": datetime.now(timezone.utc).isoformat(), "lock": lock,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    uv = install_uv(paths, lock, dry_run)
    env = uv_environment(paths)
    run([str(uv), "python", "install", lock["python"], "--install-dir", str(paths["python_dir"]), "--no-bin"], env=env, dry_run=dry_run)
    if not paths["venv_python"].is_file() or dry_run:
        run([str(uv), "venv", str(paths["venv"]), "--python", lock["python"], "--managed-python"], env=env, dry_run=dry_run)
    requirements = [
        *lock["constraints"],
        f"pdf2zh @ {lock['pdf2zh']['archive']}",
    ]
    run([str(uv), "pip", "install", "--python", str(paths["venv_python"]), *requirements], env=env, dry_run=dry_run)
    if not skip_assets:
        run([str(paths["venv_python"]), str(ROOT / "scripts" / "prefetch_assets.py")], env=os.environ.copy(), dry_run=dry_run)
    run([str(uv), "cache", "clean"], env=env, dry_run=dry_run)
    if dry_run:
        print("[dry-run] 安装计划检查完成。")
        return
    manifest = build_manifest(paths, lock)
    temp = paths["manifest"].with_suffix(".tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(paths["manifest"])
    paths["installing"].unlink(missing_ok=True)
    report = probe_runtime(paths, lock, check_assets=not skip_assets)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ready"]:
        raise SystemExit("运行时安装完成，但自检未通过。请保留上面的可核对错误。")
    print("受管 Python 3.12、PDF 引擎和模型资产均已就绪。")


def main() -> None:
    parser = argparse.ArgumentParser(description="长 PDF 双语阅读器受管运行时")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="检查受管运行时")
    doctor.add_argument("--skip-assets", action="store_true")
    install_parser = sub.add_parser("install", help="安装或修复受管运行时")
    install_parser.add_argument("--yes", action="store_true", help="确认约 1.0–1.5 GB 下载和安装")
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.add_argument("--skip-assets", action="store_true")
    ocr_doctor = sub.add_parser("ocr-doctor", help="检查独立 PaddleOCR 运行时")
    ocr_doctor.add_argument("--check-assets", action="store_true")
    ocr_install = sub.add_parser("ocr-install", help="按需安装或修复独立 PaddleOCR 运行时")
    ocr_install.add_argument("--yes", action="store_true", help="确认约 1–2 GB 下载和安装")
    ocr_install.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.command == "doctor":
        print(json.dumps(probe_runtime(runtime_paths(), load_lock(), not args.skip_assets), ensure_ascii=False, indent=2))
        return
    if args.command == "install":
        install(yes=args.yes, dry_run=args.dry_run, skip_assets=args.skip_assets)
        return
    # Keep the heavyweight OCR dependency behind a lazy import and an explicit
    # command, so normal text-PDF setup never downloads PaddleOCR.
    from ocr_runtime import install as install_ocr, probe_runtime as probe_ocr
    if args.command == "ocr-doctor":
        print(json.dumps(probe_ocr(args.check_assets), ensure_ascii=False, indent=2))
        return
    install_ocr(yes=args.yes, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
