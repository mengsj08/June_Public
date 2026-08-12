#!/usr/bin/env python3
"""Local launcher and HTTP workbench for the trial skill."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
import fitz
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from review_workflow import (  # noqa: E402
    accept_repair, build_review, candidate_file, create_diagnosis, diagnose,
    decide_escalation, ensure_repair_model_health, reject_repair, repair_file,
    run_repair, start_repair, update_decision,
)
from qa_contract import build_contract, verify_contract  # noqa: E402
from ocr_pipeline import analyze_document, parse_page_selection, process_document, write_plan  # noqa: E402
from ocr_runtime import probe_runtime as probe_ocr_runtime, runtime_paths as ocr_runtime_paths  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "assets" / "app"
DATA = Path(os.environ.get("PDF_READER_DATA_DIR", "~/.local/share/scientific-pdf-bilingual-reader/tasks")).expanduser()
MAX_BYTES = 500 * 1024 * 1024
OCR_INSTALL_LOCK = threading.Lock()
OCR_INSTALL_STATE = {"status": "idle", "message": "PaddleOCR 尚未安装；仅扫描页需要它"}
PROXY_WARNING_LOCK = threading.Lock()
ACTIVE_TASKS_LOCK = threading.Lock()
ACTIVE_TASKS: set[str] = set()
# This value participates in pdf2zh's translate_engine_params cache key.
# Increment it whenever CLI isolation flags, system prompts, or fallback
# semantics change so translations produced under old proxy behavior expire.
PROXY_BEHAVIOR_VERSION = "proxy-v2"
FATAL_ENGINE_MARKERS = (
    "Not inside a trusted directory",
    "--skip-git-repo-check was not specified",
    "command not found",
    "Failed to authenticate",
    "OAuth session expired",
)
CLAUDE_REFUSAL_MARKERS = (
    ("API Error", "Usage Policy"),
    ("unable to respond to this request",),
)


def managed_runtime_root() -> Path:
    configured = os.environ.get("PDF_READER_RUNTIME_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "Scientific PDF Bilingual Reader" / "runtime-v1"


def find_engine() -> Path | None:
    configured = os.environ.get("PDF_READER_PDF2ZH")
    candidates = [Path(configured).expanduser()] if configured else []
    candidates += [
        managed_runtime_root() / "venv" / "bin" / "pdf2zh",
    ]
    found = shutil.which("pdf2zh")
    if found:
        candidates.append(Path(found))
    return next((p for p in candidates if p.is_file() and os.access(p, os.X_OK)), None)


def engine_python(engine: Path) -> Path:
    candidate = engine.parent / "python"
    return candidate if candidate.is_file() else Path(sys.executable)


def command_version(command: str) -> dict:
    path = shutil.which(command)
    if not path:
        return {"path": None, "version": None}
    try:
        done = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
        version = (done.stdout or done.stderr).strip().splitlines()[0] if done.returncode == 0 else None
    except Exception:
        version = None
    return {"path": path, "version": version}


def python_probe(python: Path | None) -> dict:
    if not python or not python.is_file():
        return {"path": None, "version": None, "imports": {}}
    imports = {}
    for module in ("fitz", "babeldoc", "onnxruntime", "cv2", "pdf2zh"):
        try:
            checked = subprocess.run([str(python), "-c", f"import {module}"], capture_output=True, text=True, timeout=180)
            imports[module] = checked.returncode == 0
        except subprocess.TimeoutExpired:
            imports[module] = False
    version = subprocess.run(
        [str(python), "-c", "import platform; print(platform.python_version())"],
        capture_output=True, text=True, timeout=30,
    )
    return {
        "path": str(python),
        "version": version.stdout.strip() if version.returncode == 0 else None,
        "imports": imports,
    }


def doctor() -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    engine = find_engine()
    runtime = managed_runtime_root()
    runtime_manifest = runtime / "runtime-manifest.json"
    ocr = probe_ocr_runtime(check_assets=False)
    if ocr.get("ready") and OCR_INSTALL_STATE.get("status") == "idle":
        ocr["install"] = {"status": "ready", "message": "PaddleOCR 已就绪"}
    else:
        ocr["install"] = dict(OCR_INSTALL_STATE)
    return {
        "codex": command_version("codex"),
        "claude": command_version("claude"),
        "pdf2zh": str(engine) if engine else None,
        "engine_python": python_probe(engine_python(engine) if engine else None),
        "server_python": {"path": sys.executable, "version": platform.python_version()},
        "managed_runtime": {
            "root": str(runtime),
            "manifest": str(runtime_manifest) if runtime_manifest.is_file() else None,
            "active": bool(os.environ.get("PDF_READER_MANAGED_LAUNCH")),
        },
        "ocr_runtime": ocr,
        "platform": sys.platform,
        "architecture": platform.machine(),
        "data_dir": str(DATA),
        "data_writable": os.access(DATA, os.W_OK),
    }


def task_dir(task_id: str) -> Path:
    return DATA / task_id


def read_task(task_id: str) -> dict:
    return json.loads((task_dir(task_id) / "task.json").read_text())


def write_task(task: dict) -> None:
    folder = task_dir(task["id"])
    folder.mkdir(parents=True, exist_ok=True)
    temp = folder / "task.json.tmp"
    temp.write_text(json.dumps(task, ensure_ascii=False, indent=2))
    temp.replace(folder / "task.json")


def qa_paths(folder: Path, task: dict) -> tuple[Path, Path, Path]:
    original_name = task.get("translation_source_file", task.get("original_file", "original.pdf"))
    return (
        folder / original_name,
        folder / task.get("translated_file", "translated-zh.pdf"),
        folder / task.get("page_plan_file", "page-plan.json"),
    )


def summarize_qa(report: dict, freshness: dict | None = None) -> dict:
    summary = {
        "status": report.get("status"),
        "summary": report.get("summary", {}),
        "issue_category_summary": report.get("issue_category_summary", {}),
        "flagged_pages": report.get("flagged_pages", []),
        "baseline": report.get("baseline"),
        "quality_gate": report.get("quality_gate"),
        "translation_warnings": report.get("translation_warnings", []),
    }
    if report.get("contract"):
        summary["contract"] = {
            "schema": report["contract"].get("schema"),
            "qa_rule_version": report["contract"].get("qa_rule_version"),
            "contract_sha256": report["contract"].get("contract_sha256"),
        }
    if freshness:
        summary["freshness"] = freshness
    return summary


def qa_report_with_freshness(folder: Path, task: dict) -> dict | None:
    report_file = folder / task.get("qa_alpha_file", "qa-alpha.json")
    if not report_file.is_file():
        return None
    report = json.loads(report_file.read_text())
    original, translated, plan = qa_paths(folder, task)
    report["freshness"] = verify_contract(
        report, original_path=original, output_path=translated, plan_path=plan, task=task,
    )
    return report


def decorate_task(task: dict) -> dict:
    decorated = dict(task)
    if task.get("qa_alpha_file"):
        report = qa_report_with_freshness(task_dir(task["id"]), task)
        if report:
            decorated["qa_alpha"] = summarize_qa(report, report.get("freshness"))
    return decorated


def update_document_plan(task: dict, forced_pages=None, forced_images=None) -> dict:
    folder = task_dir(task["id"])
    source = folder / task.get("original_file", "original.pdf")
    plan = analyze_document(source, parse_page_selection(forced_pages), forced_images)
    plan_file = folder / "document-plan.json"
    write_plan(plan, plan_file)
    task.update(
        document_plan_file=plan_file.name,
        page_route_counts=plan["routes"],
        ocr_required=plan["ocr_required"],
        ocr_pages=plan["ocr_pages"],
        ocr_page_count=len(plan["ocr_pages"]),
        forced_ocr_pages=plan["forced_ocr_pages"],
        forced_ocr_images=plan["forced_ocr_images"],
        ocr_image_count=len(plan["ocr_images"]),
        ocr_unit_count=plan["ocr_unit_count"],
        manual_image_candidates=[
            {"page": page["page"], "image": image["image"], "coverage": image["coverage"]}
            for page in plan["pages"] if page["route"] == "text"
            for image in page["images"] if image["coverage"] >= 0.01
        ],
    )
    return plan


def queue_translation(task: dict, provider: str, port: int) -> dict:
    with ACTIVE_TASKS_LOCK:
        ACTIVE_TASKS.add(task["id"])
    task.update(status="queued", provider=provider, message="已进入本地文档处理队列")
    write_task(task)
    threading.Thread(target=translate, args=(task["id"], provider, port), daemon=True).start()
    return task


def resume_waiting_ocr_tasks(port: int) -> None:
    for item in DATA.glob("*/task.json"):
        try:
            task = json.loads(item.read_text(encoding="utf-8"))
            if task.get("status") == "waiting_ocr_install":
                queue_translation(task, task.get("provider", "codex"), port)
        except Exception:
            continue


def install_ocr_and_resume(port: int) -> None:
    with OCR_INSTALL_LOCK:
        OCR_INSTALL_STATE.update(status="installing", message="正在安装独立 PaddleOCR 运行时与英文模型")
        paths = ocr_runtime_paths()
        paths["root"].mkdir(parents=True, exist_ok=True)
        try:
            command = [sys.executable, str(ROOT / "scripts" / "bootstrap.py"), "ocr-install", "--yes"]
            with paths["install_log"].open("w", encoding="utf-8") as stream:
                completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, text=True)
            report = probe_ocr_runtime(check_assets=True)
            if completed.returncode or not report["ready"]:
                raise RuntimeError(f"安装或自检未通过；日志：{paths['install_log']}")
            OCR_INSTALL_STATE.update(status="ready", message="PaddleOCR 已就绪")
            resume_waiting_ocr_tasks(port)
        except Exception as exc:
            OCR_INSTALL_STATE.update(status="failed", message=str(exc))
            for item in DATA.glob("*/task.json"):
                try:
                    task = json.loads(item.read_text(encoding="utf-8"))
                    if task.get("status") == "waiting_ocr_install":
                        task.update(ocr_install_error=str(exc), message=f"PaddleOCR 安装未完成：{exc}")
                        write_task(task)
                except Exception:
                    continue


class Handler(BaseHTTPRequestHandler):
    server_version = "ScientificPDFReader/0.1"

    def log_message(self, fmt, *args):
        return

    def json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def file(self, path: Path, content_type: str):
        if not path.is_file():
            return self.json({"error": "文件不存在"}, 404)
        size = path.stat().st_size
        start, end = 0, max(0, size - 1)
        status = 200
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match or (not match.group(1) and not match.group(2)):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else end
            else:
                suffix = int(match.group(2))
                start = max(0, size - suffix)
            end = min(end, size - 1)
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            status = 206
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as f:
            f.seek(start)
            remaining = length
            while remaining:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def payload(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self.json(doctor())
        if path == "/api/tasks":
            tasks = []
            DATA.mkdir(parents=True, exist_ok=True)
            for item in DATA.glob("*/task.json"):
                try: tasks.append(decorate_task(json.loads(item.read_text())))
                except Exception: pass
            return self.json(sorted(tasks, key=lambda x: x.get("created_at", 0), reverse=True))
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] == ["api", "tasks"]:
            try: task = read_task(parts[2])
            except Exception: return self.json({"error": "任务不存在"}, 404)
            if len(parts) == 3: return self.json(decorate_task(task))
            if len(parts) == 4 and parts[3] == "qa-alpha":
                report = qa_report_with_freshness(task_dir(task["id"]), task)
                return self.json(report) if report else self.json({"error": "QA 报告未生成"}, 404)
            if len(parts) == 4 and parts[3] == "qa-review":
                try:
                    return self.json(build_review(task_dir(task["id"]), task))
                except Exception as exc:
                    return self.json({"error": str(exc)}, 500)
            if len(parts) == 5 and parts[3] == "file":
                key = parts[4]
                name = task.get(f"{key}_file")
                if not name:
                    return self.json({"error": "文件未生成"}, 404)
                content_type = "application/json; charset=utf-8" if Path(name).suffix.lower() == ".json" else "application/pdf"
                return self.file(task_dir(task["id"]) / name, content_type)
            if len(parts) == 7 and parts[3] == "repairs" and parts[5] == "file":
                target = repair_file(task_dir(task["id"]), parts[4], parts[6])
                if not target:
                    return self.json({"error": "候选或报告文件不存在"}, 404)
                content_type = "text/markdown; charset=utf-8" if parts[6] == "failure-md" else (
                    "application/json; charset=utf-8" if parts[6] == "failure-json" else "application/pdf"
                )
                return self.file(target, content_type)
        asset = "index.html" if path == "/" else path.lstrip("/")
        target = (APP / asset).resolve()
        if APP.resolve() not in target.parents and target != APP.resolve():
            return self.json({"error": "非法路径"}, 400)
        types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".mjs": "application/javascript; charset=utf-8",
            ".wasm": "application/wasm",
        }
        return self.file(target, types.get(target.suffix, "application/octet-stream"))

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/ocr/install":
            payload = self.payload()
            if payload.get("confirmed") is not True:
                return self.json({"error": "需要明确确认约 1–2 GB 下载和长期磁盘占用"}, 400)
            if OCR_INSTALL_LOCK.locked() or OCR_INSTALL_STATE.get("status") == "installing":
                return self.json({"status": "installing", "message": OCR_INSTALL_STATE["message"]}, 202)
            report = probe_ocr_runtime(check_assets=False)
            if report["ready"]:
                OCR_INSTALL_STATE.update(status="ready", message="PaddleOCR 已就绪")
                resume_waiting_ocr_tasks(self.server.server_port)
                return self.json(report)
            OCR_INSTALL_STATE.update(status="installing", message="正在安装独立 PaddleOCR 运行时与英文模型")
            threading.Thread(target=install_ocr_and_resume, args=(self.server.server_port,), daemon=True).start()
            return self.json({"status": "installing", "message": "已确认，开始安装 PaddleOCR"}, 202)
        if path == "/api/shutdown":
            running = []
            DATA.mkdir(parents=True, exist_ok=True)
            for item in DATA.glob("*/task.json"):
                try:
                    task = json.loads(item.read_text())
                    if task.get("status") in {"queued", "running"}:
                        running.append({"id": task.get("id"), "name": task.get("name")})
                    repairs = item.parent / "repairs"
                    for repair_file in repairs.glob("*/repair.json") if repairs.is_dir() else []:
                        repair = json.loads(repair_file.read_text())
                        if repair.get("status") in {"advising", "diagnosing", "repairing"}:
                            running.append({
                                "id": repair.get("repair_id"),
                                "name": f"{task.get('name')} · 第 {repair.get('pdf_page')} 页复核",
                            })
                except Exception:
                    pass
            if running:
                return self.json({"error": "仍有翻译或页面修复任务运行，完成后才能退出程序", "running": running}, 409)
            if OCR_INSTALL_LOCK.locked() or OCR_INSTALL_STATE.get("status") == "installing":
                return self.json({"error": "PaddleOCR 仍在安装，完成后才能退出程序"}, 409)
            self.json({"ok": True, "message": "本地程序正在退出"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == "/api/tasks":
            size = int(self.headers.get("Content-Length", "0"))
            filename = Path(unquote(self.headers.get("X-Filename", "upload.pdf"))).name
            if size <= 0 or size > MAX_BYTES: return self.json({"error": "文件为空或超过 500 MB"}, 413)
            task_id = uuid.uuid4().hex[:12]
            folder = task_dir(task_id); folder.mkdir(parents=True)
            original = folder / "original.pdf"
            remaining = size
            with original.open("wb") as out:
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk: break
                    out.write(chunk); remaining -= len(chunk)
            if original.read_bytes()[:5] != b"%PDF-":
                shutil.rmtree(folder)
                return self.json({"error": "只接受 PDF 文件"}, 415)
            task = {"id":task_id, "name":filename, "status":"uploaded", "created_at":time.time(), "original_file":"original.pdf", "translated_file":None, "message":"正在分析页面文本层", "data_dir":str(folder)}
            try:
                plan = update_document_plan(task, [], [])
            except Exception as exc:
                shutil.rmtree(folder)
                return self.json({"error": f"PDF 页面分析失败：{exc}"}, 415)
            task["message"] = (
                f"检测到 {len(plan['ocr_pages'])} 个扫描/稀疏文本页；开始时将调用 PaddleOCR"
                if plan["ocr_required"] else
                "文本层可直接使用；无需 OCR"
            )
            write_task(task)
            return self.json(task, 201)
        parts = path.strip("/").split("/")
        if len(parts) >= 4 and parts[:2] == ["api", "tasks"]:
            try:
                task = read_task(parts[2])
            except Exception:
                return self.json({"error": "任务不存在"}, 404)
            folder = task_dir(task["id"])
            try:
                if len(parts) == 6 and parts[3] == "issues" and parts[5] == "decision":
                    result = update_decision(folder, parts[4], self.payload().get("decision", "pending"))
                    return self.json(result)
                if len(parts) == 4 and parts[3] == "diagnose":
                    payload = self.payload()
                    page = int(payload.get("pdf_page", 0))
                    issue_ids = payload.get("issue_ids") or []
                    ensure_repair_model_health(require_codex=True, require_claude=True)
                    record = create_diagnosis(folder, task, page, issue_ids, "claude", str(payload.get("feedback", ""))[:2000])
                    threading.Thread(
                        target=diagnose,
                        args=(folder, task, record["repair_id"], page, issue_ids, "claude", record["feedback"]),
                        daemon=True,
                    ).start()
                    return self.json(record, 202)
                if len(parts) == 6 and parts[3] == "repairs":
                    repair_id, action = parts[4], parts[5]
                    if action == "start":
                        engine = find_engine()
                        if not engine:
                            return self.json({"error": "PDF 引擎不可用，无法生成候选修复"}, 409)
                        record = start_repair(folder, repair_id)
                        threading.Thread(
                            target=run_repair,
                            args=(folder, task, repair_id, self.server.server_port, str(engine_python(engine))),
                            daemon=True,
                        ).start()
                        return self.json(record, 202)
                    if action == "accept":
                        task = accept_repair(folder, task, repair_id)
                        write_task(task)
                        return self.json(task)
                    if action == "reject":
                        return self.json(reject_repair(folder, repair_id))
                    if action == "decision":
                        return self.json(decide_escalation(folder, task, repair_id, self.payload()))
            except (ValueError, RuntimeError) as exc:
                return self.json({"error": str(exc)}, 409)
            except Exception as exc:
                return self.json({"error": str(exc)}, 500)
        if len(parts) == 4 and parts[:2] == ["api", "tasks"] and parts[3] == "start":
            try: task = read_task(parts[2])
            except Exception: return self.json({"error":"任务不存在"}, 404)
            payload = self.payload()
            provider = payload.get("provider", "codex")
            if provider not in ("codex", "claude"): return self.json({"error":"不支持的提供方"}, 400)
            if task["status"] == "running" and not running_task_is_stale(task):
                return self.json(task)
            if running_task_is_stale(task):
                task.update(status="stale", message="检测到前次工作台遗留状态，正在恢复任务")
                write_task(task)
            try:
                force_pages = payload.get("force_ocr_pages", task.get("forced_ocr_pages", []))
                force_images = payload.get("force_ocr_images", task.get("forced_ocr_images", []))
                plan = update_document_plan(task, force_pages, force_images)
            except ValueError as exc:
                return self.json({"error": str(exc)}, 400)
            task["provider"] = provider
            if plan["ocr_required"] and not probe_ocr_runtime(check_assets=False)["ready"]:
                task.update(
                    status="waiting_ocr_install",
                    message=f"{plan['ocr_unit_count']} 个页面/图片单元需要 OCR；等待你确认安装约 1–2 GB 的独立 PaddleOCR 运行时",
                )
                write_task(task)
                return self.json(task, 202)
            return self.json(queue_translation(task, provider, self.server.server_port), 202)
        return self.json({"error":"未知接口"}, 404)

    def do_DELETE(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
            folder = task_dir(parts[2])
            if folder.exists(): shutil.rmtree(folder)
            return self.json({"ok": True})
        return self.json({"error":"未知接口"}, 404)


TRANSLATION_LOCK = threading.Lock()


def translate(task_id: str, provider: str, port: int) -> None:
    try:
        with TRANSLATION_LOCK:
            _translate(task_id, provider, port)
    finally:
        with ACTIVE_TASKS_LOCK:
            ACTIVE_TASKS.discard(task_id)


def task_is_active(task_id: str) -> bool:
    with ACTIVE_TASKS_LOCK:
        return task_id in ACTIVE_TASKS


def running_task_is_stale(task: dict) -> bool:
    return task.get("status") == "running" and not task_is_active(task["id"])


def engine_fatal_marker(text: str) -> str | None:
    return next((marker for marker in FATAL_ENGINE_MARKERS if marker in text), None)


def proxy_provider(model: str) -> str:
    return str(model).split("+", 1)[0]


def terminate_recorded_engine(folder: Path) -> bool:
    pid_file = folder / "engine.pid"
    if not pid_file.is_file():
        return False
    try:
        pid = int(pid_file.read_text().strip())
        checked = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5,
        )
        command = checked.stdout.strip()
        if checked.returncode or "pdf2zh" not in command or str(folder) not in command:
            return False
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            os.kill(pid, signal.SIGKILL)
        return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    finally:
        pid_file.unlink(missing_ok=True)


def reset_translation_warnings(folder: Path) -> None:
    """Start each translation run with an empty refusal-warning journal."""
    warning_file = folder / "translation-warnings.jsonl"
    temp = warning_file.with_suffix(".jsonl.tmp")
    temp.write_text("", encoding="utf-8")
    temp.replace(warning_file)


def _translate(task_id: str, provider: str, port: int) -> None:
    task = read_task(task_id); engine = find_engine(); cli = shutil.which(provider)
    if not engine or not cli:
        task.update(status="failed", message=f"环境缺失：{provider} 或 pdf2zh 不可用"); write_task(task); return
    folder = task_dir(task_id); output = folder / "output"; output.mkdir(exist_ok=True)
    reset_translation_warnings(folder)
    source = folder / task.get("original_file", "original.pdf")
    ocr_warnings = []
    try:
        task.update(status="running", message="正在按页面检查文本层与 OCR 路由"); write_task(task)
        plan = update_document_plan(task, task.get("forced_ocr_pages", []), task.get("forced_ocr_images", []))
        if plan["ocr_required"]:
            ocr_report = probe_ocr_runtime(check_assets=False)
            if not ocr_report["ready"]:
                task.update(status="waiting_ocr_install", message="扫描页需要 PaddleOCR；等待安装确认")
                write_task(task)
                return
            task.update(status="running", message=f"正在用 PaddleOCR 识别 {plan['ocr_unit_count']} 个页面/图片单元"); write_task(task)
            processed = process_document(
                source, folder, ocr_runtime_paths()["venv_python"], task.get("forced_ocr_pages", []),
                task.get("forced_ocr_images", []),
            )
            source = processed["translation_source"]
            ocr_warnings = processed["warnings"]
            task.update(
                translation_source_file=source.name,
                searchable_file=processed["searchable"].name if processed["searchable"] else None,
                ocr_results_file=processed["ocr_results"].name if processed["ocr_results"] else None,
                ocr_summary={
                    "pages": plan["ocr_pages"],
                    "page_count": len(plan["ocr_pages"]),
                    "images": plan["ocr_images"],
                    "image_count": len(plan["ocr_images"]),
                    "warning_count": len(ocr_warnings),
                },
                ocr_warnings=ocr_warnings,
            )
        else:
            task.update(translation_source_file=source.name, searchable_file=None, ocr_results_file=None, ocr_summary={"pages": [], "page_count": 0, "images": [], "image_count": 0, "warning_count": 0}, ocr_warnings=[])
        task.update(status="running", message=f"页面准备完成，正在通过 {provider} 翻译；请保持本机唤醒")
        write_task(task)
    except Exception as exc:
        task.update(status="failed", message=f"OCR/页面准备失败：{exc}")
        write_task(task)
        return
    env = os.environ.copy(); env.update(
        OPENAILIKED_BASE_URL=f"http://127.0.0.1:{port}/v1",
        OPENAILIKED_API_KEY=task_id,
        OPENAILIKED_MODEL=f"{provider}+{PROXY_BEHAVIOR_VERSION}",
    )
    cmd = [str(engine), str(source), "--service", "openailiked", "--thread", "4", "--output", str(output)]
    log = folder / "engine.log"
    process = None
    try:
        terminate_recorded_engine(folder)
        with log.open("w") as stream:
            process = subprocess.Popen(cmd, env=env, stdout=stream, stderr=subprocess.STDOUT)
            (folder / "engine.pid").write_text(str(process.pid))
            timeout_hours = float(os.environ.get("PDF_READER_JOB_TIMEOUT_HOURS", "12"))
            deadline = time.monotonic() + timeout_hours * 3600
            while process.poll() is None:
                if time.monotonic() > deadline:
                    process.terminate()
                    raise TimeoutError(f"超过 {timeout_hours:g} 小时仍未完成，已停止任务")
                stream.flush()
                recent = log.read_text(errors="replace")[-12000:]
                progress = re.findall(r"(\d+)\s*/\s*(\d+)", recent)
                if progress:
                    done, total = progress[-1]
                    latest = read_task(task_id)
                    latest.update(
                        status="running",
                        progress_done=int(done),
                        progress_total=int(total),
                        message=f"正在通过 {provider} 翻译：{done}/{total} 个处理单元",
                    )
                    write_task(latest)
                marker = engine_fatal_marker(recent)
                if marker:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill()
                    raise RuntimeError(f"检测到不可重试错误：{marker}")
                time.sleep(2)
        returncode = process.returncode
        candidates = sorted(output.glob("*-mono.pdf"), key=lambda p:p.stat().st_mtime, reverse=True)
        if returncode or not candidates: raise RuntimeError(f"翻译引擎退出码 {returncode}")
        final = folder / "translated-zh.pdf"
        manifest = folder / "page-plan.json"
        router = ROOT / "scripts" / "page_router.py"
        routed = subprocess.run(
            [str(engine_python(engine)), str(router), str(source),
             str(candidates[0]), str(final), "--manifest", str(manifest)],
            capture_output=True, text=True, timeout=3600, env=env,
        )
        if routed.returncode:
            raise RuntimeError(f"页面策略处理失败：{routed.stderr[-500:]}")
        plan = json.loads(manifest.read_text())
        dual = folder / "bilingual-side-by-side.pdf"
        merged = subprocess.run(
            [str(engine_python(engine)), str(ROOT / "scripts" / "dual_pdf.py"), str(folder / "original.pdf"), str(final), str(dual)],
            capture_output=True, text=True, timeout=600,
        )
        if merged.returncode or not dual.is_file():
            raise RuntimeError(f"双语 PDF 生成失败：{merged.stderr[-500:]}")
        qa_alpha_file = folder / "qa-alpha.json"
        qa_alpha_cmd = [
            str(engine_python(engine)), str(ROOT / "scripts" / "qa_alpha.py"),
            str(source), str(final), "--plan", str(manifest),
            "--visual-source", str(folder / (task.get("searchable_file") or task.get("original_file", "original.pdf"))),
            "--document-plan", str(folder / task.get("document_plan_file", "document-plan.json")),
            "--translation-warnings", str(folder / "translation-warnings.jsonl"),
            "--task-id", task_id, "--report", str(qa_alpha_file),
        ]
        baseline = os.environ.get("PDF_READER_QA_BASELINE")
        if baseline and Path(baseline).is_file():
            qa_alpha_cmd += ["--baseline", baseline]
        audited = subprocess.run(qa_alpha_cmd, capture_output=True, text=True, timeout=1800)
        if audited.returncode or not qa_alpha_file.is_file():
            raise RuntimeError(f"Gate 1c-alpha QA 失败：{audited.stderr[-500:]}")
        alpha = json.loads(qa_alpha_file.read_text())
        translation_warnings = read_translation_warnings(folder)
        alpha["translation_warnings"] = translation_warnings
        final_status = (
            "needs_review" if alpha["status"] == "needs_review" else
            "completed_with_warnings" if alpha["status"] == "passed_with_warnings" or ocr_warnings or translation_warnings else
            "completed"
        )
        flagged = alpha.get("flagged_pages", [])
        final_message = (
            f"翻译与合成完成；确定性 QA 标记 {len(flagged)} 个问题页，需要复核"
            if final_status == "needs_review" else
            f"翻译与合成完成；确定性 QA/OCR/翻译共标记 {len(flagged) + len(ocr_warnings) + len(translation_warnings)} 个警告"
            if final_status == "completed_with_warnings" else
            "翻译、合成与确定性 QA 均已通过"
        )
        task.update(
            status=final_status,
            translated_file=final.name,
            dual_file=dual.name,
            page_plan_file=manifest.name,
            page_type_counts=plan["qa"]["type_counts"],
            qa=plan["qa"],
            qa_alpha_file=qa_alpha_file.name,
            ocr_warnings=ocr_warnings,
            translation_warnings=translation_warnings,
            message=final_message,
        )
        alpha["contract"] = build_contract(
            original_path=source, output_path=final, plan_path=manifest, task=task,
        )
        alpha["freshness"] = verify_contract(
            alpha, original_path=source, output_path=final, plan_path=manifest, task=task,
        )
        qa_alpha_file.write_text(json.dumps(alpha, ensure_ascii=False, indent=2))
        task["qa_alpha"] = summarize_qa(alpha, alpha.get("freshness"))
    except Exception as exc:
        task.update(status="failed", message=f"翻译失败：{exc}")
    finally:
        pid_file = folder / "engine.pid"
        if process is not None and pid_file.is_file() and pid_file.read_text().strip() == str(process.pid):
            pid_file.unlink(missing_ok=True)
    write_task(task)


def source_text_from_translation_prompt(prompt: str) -> str | None:
    match = re.search(r"Source Text:\s*(.*?)\s*\n\s*Translated Text:", prompt, re.S)
    return match.group(1) if match else None


def is_claude_policy_refusal(detail: str) -> bool:
    return any(all(marker.casefold() in detail.casefold() for marker in group) for group in CLAUDE_REFUSAL_MARKERS)


def run_proxy_cli(provider: str, prompt: str, runner=subprocess.run, on_refusal=None) -> str:
    if provider == "codex":
        cmd = ["codex", "exec", "--ephemeral", "--ignore-rules", "--ignore-user-config", "--skip-git-repo-check", "-s", "read-only", prompt]
        run_kwargs = {}
    else:
        cmd = [
            "claude", "--print", "--safe-mode", "--setting-sources", "",
            "--strict-mcp-config", "--tools", "", "--no-session-persistence",
            "--system-prompt",
            "Translate the supplied source text faithfully into Chinese. Output only the translation, with no commentary or meta text.",
        ]
        # stdin keeps source beginning with '-' from being parsed as an option.
        run_kwargs = {"input": prompt}
    done = runner(cmd, capture_output=True, text=True, timeout=180, **run_kwargs)
    if done.returncode:
        detail = "\n".join(part.strip() for part in (done.stderr, done.stdout) if part.strip())
        source_text = source_text_from_translation_prompt(prompt)
        if provider == "claude" and is_claude_policy_refusal(detail) and source_text is not None:
            if on_refusal:
                on_refusal(source_text)
            return source_text
        raise RuntimeError(detail[-1000:] or f"CLI exited with status {done.returncode}")
    return done.stdout.strip()


def _request_task_id(handler: BaseHTTPRequestHandler) -> str | None:
    match = re.fullmatch(r"Bearer\s+([A-Za-z0-9_-]+)", handler.headers.get("Authorization", ""), re.I)
    return match.group(1) if match else None


def _locate_source_pages(folder: Path, task: dict, source_text: str) -> list[int]:
    source = folder / task.get("translation_source_file", task.get("original_file", "original.pdf"))
    if not source.is_file():
        return []
    needle = re.sub(r"\s+", " ", source_text).strip()
    if not needle:
        return []
    needle_folded = needle.casefold()
    needle_tokens = set(re.findall(r"[A-Za-z0-9]{2,}", needle_folded))
    exact_pages = []
    scored_pages = []
    document = fitz.open(source)
    try:
        for index, page in enumerate(document, start=1):
            page_text = re.sub(r"\s+", " ", page.get_text("text") or "").strip().casefold()
            if needle_folded in page_text:
                exact_pages.append(index)
                continue
            if needle_tokens:
                page_tokens = set(re.findall(r"[A-Za-z0-9]{2,}", page_text))
                overlap = len(needle_tokens & page_tokens) / len(needle_tokens)
                if overlap >= 0.5:
                    scored_pages.append((overlap, index))
        if exact_pages:
            return exact_pages
        if not scored_pages:
            return []
        best = max(score for score, _ in scored_pages)
        return [index for score, index in scored_pages if score == best]
    finally:
        document.close()


def record_translation_refusal(task_id: str | None, source_text: str) -> None:
    if not task_id or not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
        return
    folder = task_dir(task_id)
    task_file = folder / "task.json"
    if not task_file.is_file():
        return
    with PROXY_WARNING_LOCK:
        task = json.loads(task_file.read_text())
        event = {
            "code": "translation_refusal_kept_source",
            "provider": "claude",
            "pages": _locate_source_pages(folder, task, source_text),
            "source_length": len(source_text),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "message": "Claude 拒绝翻译该文本段；已保留原文，请人工复核标记页。",
        }
        warning_file = folder / "translation-warnings.jsonl"
        with warning_file.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_translation_warnings(folder: Path) -> list[dict]:
    warning_file = folder / "translation-warnings.jsonl"
    if not warning_file.is_file():
        return []
    warnings = []
    for line in warning_file.read_text(encoding="utf-8").splitlines():
        try:
            warnings.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return warnings


class ShimHandler(Handler):
    def do_POST(self):
        if urlparse(self.path).path != "/v1/chat/completions": return super().do_POST()
        length = int(self.headers.get("Content-Length", "0")); payload = json.loads(self.rfile.read(length))
        provider = proxy_provider(payload.get("model", "codex"))
        if provider not in {"codex", "claude"}:
            return self.json({"error": {"message": "不支持的提供方"}}, 400)
        messages = payload.get("messages", [])
        prompt = "\n".join(str(m.get("content", "")) for m in messages)
        try:
            task_id = _request_task_id(self)
            answer = run_proxy_cli(
                provider, prompt,
                on_refusal=lambda source: record_translation_refusal(task_id, source),
            )
            return self.json({"id":"local","object":"chat.completion","choices":[{"index":0,"message":{"role":"assistant","content":answer},"finish_reason":"stop"}]})
        except Exception as exc:
            return self.json({"error":{"message":str(exc)}}, 500)


def serve(host: str, port: int, open_browser: bool):
    DATA.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), ShimHandler)
    url = f"http://{host}:{server.server_port}"
    print(f"科研长 PDF 双语阅读器：{url}")
    print(f"任务目录：{DATA}")
    if open_browser: threading.Timer(.5, lambda:webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    start = sub.add_parser("start"); start.add_argument("--host", default="127.0.0.1"); start.add_argument("--port", type=int, default=8765); start.add_argument("--open", action="store_true")
    args = parser.parse_args()
    if args.command == "doctor":
        print(json.dumps(doctor(), ensure_ascii=False, indent=2)); return
    if args.host not in ("127.0.0.1", "localhost"): raise SystemExit("试用版只允许监听本机地址")
    engine = find_engine()
    preferred_python = engine_python(engine).resolve() if engine else None
    current_python = Path(sys.executable).resolve()
    if (
        preferred_python
        and preferred_python != current_python
        and not os.environ.get("PDF_READER_WORKBENCH_REEXEC")
    ):
        env = os.environ.copy()
        env["PDF_READER_WORKBENCH_REEXEC"] = "1"
        env["PDF_READER_PDF2ZH"] = str(engine)
        os.execve(str(preferred_python), [str(preferred_python), __file__, *sys.argv[1:]], env)
    serve(args.host, args.port, args.open)


if __name__ == "__main__": main()
