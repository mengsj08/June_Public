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
import tempfile
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
    accept_repair, build_review, candidate_file, create_diagnosis,
    create_human_review, diagnose, diagnose_human_review, decide_escalation,
    DIAGNOSIS_SCHEMA, ensure_repair_model_health, reject_repair, repair_file,
    MODEL_CLI_LOCK, open_attempts, render_page_images, run_model, run_repair,
    start_repair, update_decision,
)
from qa_contract import attention_summary, build_contract, verify_contract  # noqa: E402
from review_cycle import (  # noqa: E402
    active_agent_review_jobs, agent_runner_active, append_comment_decision,
    create_comment, enqueue_agent_review_selection, permanently_delete_task,
    file_sha256,
    queued_agent_review_jobs, restore_trashed_task, review_cycle_projection,
    start_agent_review_runner, trash_task, write_page_manifest,
)
from repair_batch import (  # noqa: E402
    accept_candidate, acquire_task_mutation_lock, active_task_mutation,
    approve_machine_repair, assemble_candidate,
    batch_candidate_file, batch_preview_file, create_one_click_repair_batch,
    create_repair_batch, open_repair_batches, reject_candidate,
    repair_batch_projection, run_candidate_observations,
    run_one_click_repair_batch, run_repair_batch,
    release_task_mutation_lock,
    set_page_patch_decision_and_maybe_reassemble, start_repair_batch,
    task_mutation_lock,
)
from ocr_pipeline import analyze_document, parse_page_selection, process_document, write_plan  # noqa: E402
from ocr_runtime import probe_runtime as probe_ocr_runtime, runtime_paths as ocr_runtime_paths  # noqa: E402
from dual_pdf import merge as merge_dual_pdf  # noqa: E402
from scan_translate_pipeline import (  # noqa: E402
    ScanTranslationError, build_scan_translation_pdf, merge_scan_pages, scan_page_plan,
)
from translation_broker import TranslationBroker  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "assets" / "app"
AGENT_REVIEW_RESULT_SCHEMA = ROOT / "references" / "agent-review-schema.json"
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
PROXY_BEHAVIOR_VERSION = "proxy-v5-toolless-isolation"
ENGINE_TRANSLATION_THREADS = "1"
TRANSLATION_MUTATION_TTL_SECONDS = 26 * 60 * 60
ENGINE_GATEWAY_FAILURE_LIMIT = 12
FATAL_ENGINE_MARKERS = (
    "Not inside a trusted directory",
    "--skip-git-repo-check was not specified",
    "command not found",
    "Failed to authenticate",
    "OAuth session expired",
)
COREML_ORT_FAILURE_MARKERS = (
    "CoreMLExecutionProvider",
    "CoreML EP",
    "coreml execution provider",
)
ONNXRUNTIME_FAILURE_MARKERS = (
    "onnxruntime",
    "ONNXRuntimeError",
    "onnxruntime_pybind11_state.Fail",
    "Error in building plan",
    "Error executing model",
)
CLAUDE_REFUSAL_MARKERS = (
    ("API Error", "Usage Policy"),
    ("unable to respond to this request",),
)


def schedule_created_diagnosis(result: dict, folder: Path, task: dict) -> bool:
    """Start the read-only advisor for a June-approved successor attempt."""
    record = result.get("created_attempt") if isinstance(result, dict) else None
    if not record:
        return False
    threading.Thread(
        target=diagnose,
        args=(
            folder,
            task,
            record["repair_id"],
            int(record["pdf_page"]),
            list(record.get("issue_ids", [])),
            "claude",
            str(record.get("feedback", "")),
        ),
        daemon=True,
    ).start()
    return True


def schedule_agent_review_queue(folder: Path, task: dict) -> bool:
    return start_agent_review_runner(
        folder,
        task,
        render_page_images=render_page_images,
        run_model=run_model,
        diagnosis_schema=AGENT_REVIEW_RESULT_SCHEMA,
    )


def ensure_agent_review_provider(provider: str) -> None:
    if provider == "claude":
        ensure_repair_model_health(require_codex=False, require_claude=True)
    elif provider == "codex":
        ensure_repair_model_health(require_codex=True, require_claude=False)
    else:
        raise ValueError("不支持的审阅提供方")


def resume_agent_review_queue_for_projection(folder: Path, task: dict) -> bool:
    task_id = task.get("id")
    if queued_agent_review_jobs(folder, task_id) and not agent_runner_active(task_id):
        return schedule_agent_review_queue(folder, task)
    return False


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


def task_artifact_if_present(folder: Path, task: dict, field: str, default: str) -> Path | None:
    value = task.get(field) or default
    if not value:
        return None
    path = (folder / Path(value)).resolve()
    try:
        if folder.resolve() not in path.parents and path != folder.resolve():
            return None
    except OSError:
        return None
    return path if path.is_file() else None


def snapshot_before_rerun(folder: Path, task: dict) -> dict:
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    version = folder / "versions" / f"before-rerun-{timestamp}"
    suffix = 1
    while version.exists():
        suffix += 1
        version = folder / "versions" / f"before-rerun-{timestamp}-{suffix}"
    files = {
        "translated-zh.pdf": task_artifact_if_present(folder, task, "translated_file", "translated-zh.pdf"),
        "bilingual-side-by-side.pdf": task_artifact_if_present(folder, task, "dual_file", "bilingual-side-by-side.pdf"),
        "qa-alpha.json": task_artifact_if_present(folder, task, "qa_alpha_file", "qa-alpha.json"),
        "page-plan.json": task_artifact_if_present(folder, task, "page_plan_file", "page-plan.json"),
        "document-plan.json": task_artifact_if_present(folder, task, "document_plan_file", "document-plan.json"),
        "searchable-original.pdf": task_artifact_if_present(folder, task, "searchable_file", "searchable-original.pdf"),
        "ocr-results.json": task_artifact_if_present(folder, task, "ocr_results_file", "ocr-results.json"),
    }
    files = {name: path for name, path in files.items() if path and path.is_file()}
    if not files:
        raise RuntimeError("当前任务没有可快照的正式产物")
    version.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema": "rerun-snapshot-receipt/v1",
        "rerun_at": time.time(),
        "task_id": task.get("id"),
        "backup_dir": str(version),
        "pre_rerun_hashes": {name: file_sha256(path) for name, path in files.items()},
        "pre_rerun_files": {
            name: str(path.relative_to(folder.resolve())) for name, path in files.items()
        },
        "pre_rerun_task": {
            key: task.get(key)
            for key in (
                "status", "message", "translated_file", "dual_file", "qa_alpha_file",
                "page_plan_file", "document_plan_file", "searchable_file", "ocr_results_file",
                "completed_at", "updated_at",
            )
            if key in task
        },
    }
    for name, source in files.items():
        shutil.copy2(source, version / name)
    (version / "task.json").write_text(json.dumps(task, ensure_ascii=False, indent=2))
    (version / "rerun-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    return receipt


def qa_paths(folder: Path, task: dict) -> tuple[Path, Path, Path]:
    original_name = task.get("translation_source_file", task.get("original_file", "original.pdf"))
    return (
        folder / original_name,
        folder / task.get("translated_file", "translated-zh.pdf"),
        folder / task.get("page_plan_file", "page-plan.json"),
    )


def summarize_qa(
    report: dict,
    freshness: dict | None = None,
    decisions: dict | None = None,
) -> dict:
    summary = {
        "status": report.get("status"),
        "summary": report.get("summary", {}),
        "issue_category_summary": report.get("issue_category_summary", {}),
        "flagged_pages": report.get("flagged_pages", []),
        "baseline": report.get("baseline"),
        "quality_gate": report.get("quality_gate"),
        "translation_warnings": report.get("translation_warnings", []),
        "attention": attention_summary(
            report.get("pages", []), report.get("document_issues", []), decisions,
        ),
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
        folder = task_dir(task["id"])
        report = qa_report_with_freshness(folder, task)
        if report:
            review = {}
            review_file = folder / "review-state.json"
            if review_file.is_file():
                try:
                    review = json.loads(review_file.read_text())
                except Exception:
                    review = {}
            decorated["qa_alpha"] = summarize_qa(
                report, report.get("freshness"), review.get("issues", {}),
            )
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
    folder = task_dir(task["id"])
    token = acquire_task_mutation_lock(
        folder, f"translation:{task['id']}", ttl_seconds=TRANSLATION_MUTATION_TTL_SECONDS,
    )
    try:
        if task.pop("rerun_requested", False):
            task["rerun_snapshot"] = snapshot_before_rerun(folder, task)
        with ACTIVE_TASKS_LOCK:
            ACTIVE_TASKS.add(task["id"])
        task.update(status="queued", provider=provider, message="已进入本地文档处理队列")
        write_task(task)
        threading.Thread(
            target=translate, args=(task["id"], provider, port, token), daemon=True,
        ).start()
        return task
    except Exception:
        release_task_mutation_lock(folder, token)
        with ACTIVE_TASKS_LOCK:
            ACTIVE_TASKS.discard(task["id"])
        raise


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
            if len(parts) == 4 and parts[3] == "review-cycle":
                try:
                    folder = task_dir(task["id"])
                    resume_agent_review_queue_for_projection(folder, task)
                    projection = review_cycle_projection(folder, task)
                    projection.update(repair_batch_projection(folder, task))
                    return self.json(projection)
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
            if len(parts) == 7 and parts[3] == "repair-batches" and parts[5] == "file":
                try:
                    target = batch_candidate_file(task_dir(task["id"]), parts[4], parts[6])
                except (ValueError, RuntimeError):
                    target = None
                if not target:
                    return self.json({"error": "批量候选文件不存在"}, 404)
                content_type = "application/json; charset=utf-8" if target.suffix.lower() == ".json" else "application/pdf"
                return self.file(target, content_type)
            if len(parts) == 7 and parts[3] == "repair-batches" and parts[5] == "preview":
                try:
                    target = batch_preview_file(task_dir(task["id"]), parts[4], parts[6])
                except (ValueError, RuntimeError):
                    target = None
                if not target:
                    return self.json({"error": "候选预览图片不存在"}, 404)
                return self.file(target, "image/png")
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
                    human_reviews = item.parent / "human-reviews"
                    for review_file in human_reviews.glob("*/review.json") if human_reviews.is_dir() else []:
                        review = json.loads(review_file.read_text())
                        if review.get("status") == "advising":
                            running.append({
                                "id": review.get("review_id"),
                                "name": f"{task.get('name')} · 第 {review.get('pdf_page')} 页人工复核",
                            })
                    for job in active_agent_review_jobs(item.parent, task.get("id")):
                        running.append({
                            "id": job.get("job_id"),
                            "name": f"{task.get('name')} · AgentReview {job.get('comment_count', 0)} 条 Comment",
                        })
                    for batch in open_repair_batches(item.parent):
                        if batch.get("status") == "repairing":
                            running.append({
                                "id": batch.get("batch_id"),
                                "name": f"{task.get('name')} · RepairBatch 正在生成候选",
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
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "trash"] and parts[3] == "restore":
            try:
                return self.json(restore_trashed_task(DATA, parts[2]))
            except (ValueError, RuntimeError) as exc:
                return self.json({"error": str(exc)}, 409)
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
                if len(parts) == 4 and parts[3] == "comments":
                    payload = self.payload()
                    page = int(payload.get("pdf_page", 0))
                    feedback = str(payload.get("feedback", ""))[:4000]
                    record = create_comment(folder, task, page, feedback)
                    if payload.get("submit") is True:
                        provider = str(payload.get("provider", "claude"))
                        ensure_agent_review_provider(provider)
                        queued = enqueue_agent_review_selection(folder, task, [record["comment_id"]], provider)
                        schedule_agent_review_queue(folder, task)
                        return self.json({"comment": record, **queued}, 202)
                    return self.json(record, 201)
                if len(parts) == 4 and parts[3] == "agent-reviews":
                    payload = self.payload()
                    provider = str(payload.get("provider", "claude"))
                    comment_ids = payload.get("comment_ids") or []
                    ensure_agent_review_provider(provider)
                    queued = enqueue_agent_review_selection(folder, task, list(comment_ids), provider)
                    schedule_agent_review_queue(folder, task)
                    return self.json(queued, 202)
                if len(parts) == 6 and parts[3] == "comments" and parts[5] == "decision":
                    payload = self.payload()
                    result = append_comment_decision(
                        folder,
                        parts[4],
                        str(payload.get("decision", "")),
                        str(payload.get("note", "")),
                        expected_version=payload.get("expected_version"),
                    )
                    return self.json(result)
                if len(parts) == 4 and parts[3] == "human-review":
                    payload = self.payload()
                    page = int(payload.get("pdf_page", 0))
                    feedback = str(payload.get("feedback", ""))[:2000]
                    record = create_human_review(folder, task, page, feedback)
                    if payload.get("save_only") is True:
                        return self.json(record, 201)
                    threading.Thread(
                        target=diagnose_human_review,
                        args=(folder, task, record["review_id"]),
                        daemon=True,
                    ).start()
                    return self.json(record, 202)
                if len(parts) == 6 and parts[3] == "repairs":
                    repair_id, action = parts[4], parts[5]
                    if action == "batch-approve":
                        return self.json(approve_machine_repair(folder, repair_id))
                    if action == "start":
                        if open_repair_batches(folder):
                            return self.json({"error": "已有 open RepairBatch；请先完成或关闭批次"}, 409)
                        if active_task_mutation(folder):
                            return self.json({"error": "任务正在写入，不能同时启动单页修复"}, 409)
                        engine = find_engine()
                        if not engine:
                            return self.json({"error": "PDF 引擎不可用，无法生成候选修复"}, 409)
                        record = start_repair(folder, repair_id)
                        threading.Thread(
                            target=run_single_repair_locked,
                            args=(folder, task, repair_id, self.server.server_port, str(engine_python(engine))),
                            daemon=True,
                        ).start()
                        return self.json(record, 202)
                    if action == "accept":
                        with task_mutation_lock(folder, f"single-repair:{repair_id}:install", ttl_seconds=15 * 60):
                            task = accept_repair(folder, task, repair_id)
                        write_task(task)
                        return self.json(task)
                    if action == "reject":
                        return self.json(reject_repair(folder, repair_id))
                    if action == "decision":
                        result = decide_escalation(folder, task, repair_id, self.payload())
                        schedule_created_diagnosis(result, folder, task)
                        return self.json(result)
                if len(parts) == 4 and parts[3] == "repair-batches":
                    payload = self.payload()
                    result = create_repair_batch(folder, task, list(payload.get("repair_item_keys") or []))
                    return self.json(result, 201)
                if len(parts) == 5 and parts[3] == "repair-batches" and parts[4] == "one-click":
                    if active_task_mutation(folder):
                        return self.json({"error": "任务正在写入，不能同时启动批量修复"}, 409)
                    ensure_repair_model_health(require_codex=True, require_claude=False)
                    payload = self.payload()
                    result = create_one_click_repair_batch(folder, task, list(payload.get("repair_item_keys") or []))
                    if result.get("status") == "repairing":
                        threading.Thread(
                            target=run_one_click_repair_batch,
                            args=(folder, task, result["batch_id"]),
                            kwargs={"workbench_port": self.server.server_port, "python_executable": sys.executable},
                            daemon=True,
                        ).start()
                        return self.json(result, 202)
                    return self.json(result, 201)
                if len(parts) == 6 and parts[3] == "repair-batches":
                    batch_id, action = parts[4], parts[5]
                    if action == "start":
                        if active_task_mutation(folder):
                            return self.json({"error": "任务正在写入，不能同时启动批量修复"}, 409)
                        ensure_repair_model_health(require_codex=True, require_claude=False)
                        result = start_repair_batch(folder, task, batch_id)
                        threading.Thread(
                            target=run_repair_batch,
                            args=(folder, task, batch_id),
                            kwargs={"workbench_port": self.server.server_port, "python_executable": sys.executable},
                            daemon=True,
                        ).start()
                        return self.json(result, 202)
                    if action == "candidate":
                        return self.json(assemble_candidate(folder, task, batch_id))
                    if action == "accept":
                        task = accept_candidate(folder, task, batch_id)
                        write_task(task)
                        return self.json(task)
                    if action == "observations":
                        payload = self.payload()
                        provider = str(payload.get("provider") or task.get("provider") or "claude")
                        threading.Thread(
                            target=run_candidate_observations,
                            args=(folder, task, batch_id),
                            kwargs={"provider": provider},
                            daemon=True,
                        ).start()
                        return self.json({"status": "started", "provider": provider}, 202)
                    if action == "reject":
                        return self.json(reject_candidate(folder, batch_id))
                if (
                    len(parts) == 8 and parts[3] == "repair-batches"
                    and parts[5] == "page-patches" and parts[7] == "decision"
                ):
                    payload = self.payload()
                    return self.json(set_page_patch_decision_and_maybe_reassemble(
                        folder, task, parts[4], parts[6], str(payload.get("decision", "")),
                        expected_version=payload.get("expected_version"),
                    ))
            except (ValueError, RuntimeError) as exc:
                return self.json({"error": str(exc)}, 409)
            except Exception as exc:
                return self.json({"error": str(exc)}, 500)
        if len(parts) == 4 and parts[:2] == ["api", "tasks"] and parts[3] == "start":
            try: task = read_task(parts[2])
            except Exception: return self.json({"error":"任务不存在"}, 404)
            folder = task_dir(task["id"])
            payload = self.payload()
            provider = payload.get("provider", "codex")
            if provider not in ("codex", "claude"): return self.json({"error":"不支持的提供方"}, 400)
            if task["status"] == "running" and not running_task_is_stale(task):
                return self.json(task)
            if running_task_is_stale(task):
                task.update(status="stale", message="检测到前次工作台遗留状态，正在恢复任务")
                write_task(task)
            if payload.get("rerun") is True:
                if task.get("status") in {"queued", "running", "waiting_ocr_install"}:
                    return self.json({"error": "任务仍在运行，不能重跑"}, 409)
                task["rerun_requested"] = True
            if open_repair_batches(folder) or open_attempts(folder):
                return self.json({"error": "当前仍有未关闭的修复或候选，请先完成、接受或关闭后再重跑"}, 409)
            if active_task_mutation(folder):
                return self.json({"error": "任务正在执行其他写入，不能同时开始翻译"}, 409)
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
            try:
                return self.json(queue_translation(task, provider, self.server.server_port), 202)
            except RuntimeError as exc:
                return self.json({"error": str(exc)}, 409)
        return self.json({"error":"未知接口"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
            params = dict(
                item.split("=", 1) if "=" in item else (item, "")
                for item in parsed.query.split("&") if item
            )
            try:
                if params.get("permanent") == "true":
                    return self.json(permanently_delete_task(DATA, parts[2], params.get("confirm_delete")))
                folder = task_dir(parts[2])
                if folder.exists():
                    task = read_task(parts[2])
                    activity = task_background_write(folder, task)
                    if activity:
                        return self.json({
                            "error": "任务仍有后台写入，完成后才能移入废纸篓",
                            "activity": activity,
                        }, 409)
                return self.json(trash_task(DATA, parts[2]))
            except (ValueError, RuntimeError) as exc:
                return self.json({"error": str(exc)}, 409)
        return self.json({"error":"未知接口"}, 404)


TRANSLATION_LOCK = threading.Lock()


def translate(task_id: str, provider: str, port: int, mutation_token: str) -> None:
    try:
        with TRANSLATION_LOCK:
            _translate(task_id, provider, port)
    finally:
        release_task_mutation_lock(task_dir(task_id), mutation_token)
        with ACTIVE_TASKS_LOCK:
            ACTIVE_TASKS.discard(task_id)


def run_single_repair_locked(folder: Path, task: dict, repair_id: str, port: int, python: str) -> None:
    try:
        with task_mutation_lock(folder, f"single-repair:{repair_id}"):
            run_repair(folder, task, repair_id, port, python)
    except Exception as exc:
        record_path = folder / "repairs" / Path(repair_id).name / "repair.json"
        record = json.loads(record_path.read_text()) if record_path.is_file() else {}
        record.update(status="failed", error=str(exc)[:1000], updated_at=time.time())
        temp = record_path.with_suffix(".json.tmp")
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        temp.replace(record_path)


def task_background_write(folder: Path, task: dict) -> dict | None:
    if task_is_active(task.get("id", "")) or task.get("status") in {"queued", "running"}:
        return {"kind": "translation", "status": task.get("status")}
    lock = active_task_mutation(folder)
    if lock:
        return {"kind": "mutation_lock", "status": lock.get("owner")}
    if active_agent_review_jobs(folder, task.get("id")):
        return {"kind": "agent_review", "status": "active"}
    for repair in open_attempts(folder):
        if repair.get("status") in {"advising", "diagnosing", "repairing"}:
            return {"kind": "single_repair", "status": repair.get("status")}
    human_root = folder / "human-reviews"
    for path in human_root.glob("*/review.json") if human_root.is_dir() else []:
        try:
            if json.loads(path.read_text()).get("status") == "advising":
                return {"kind": "human_review", "status": "advising"}
        except Exception:
            continue
    for batch in open_repair_batches(folder):
        if batch.get("status") == "repairing":
            return {"kind": "repair_batch", "status": "repairing"}
    return None


def task_is_active(task_id: str) -> bool:
    with ACTIVE_TASKS_LOCK:
        return task_id in ACTIVE_TASKS


def running_task_is_stale(task: dict) -> bool:
    return task.get("status") == "running" and not task_is_active(task["id"])


def engine_fatal_marker(text: str) -> str | None:
    return next((marker for marker in FATAL_ENGINE_MARKERS if marker in text), None)


def engine_progress(text: str) -> tuple[int, int] | None:
    """Read tqdm progress without mistaking log dates such as 08/12/26."""
    matches = re.findall(r"\|\s*(\d+)\s*/\s*(\d+)\s*\[", text)
    if not matches:
        return None
    done, total = matches[-1]
    return int(done), int(total)


def engine_gateway_failure_count(text: str) -> int:
    """Count standalone gateway-status lines emitted by pdf2zh retries."""
    return len(re.findall(r"^\s*(?:502|503|504)\s*$", text, re.MULTILINE))


def engine_coreml_ort_failure(returncode: int | None, text: str) -> bool:
    if not returncode:
        return False
    folded = text.casefold()
    return (
        any(marker.casefold() in folded for marker in COREML_ORT_FAILURE_MARKERS)
        and any(marker.casefold() in folded for marker in ONNXRUNTIME_FAILURE_MARKERS)
    )


def pdf2zh_cpu_retry_command(command: list[str]) -> list[str]:
    retried = list(command)
    if "--backend" in retried:
        index = retried.index("--backend")
        if index + 1 < len(retried):
            retried[index + 1] = "cpu"
            return retried
    return [*retried, "--backend", "cpu"]


def pdf2zh_cpu_retry_environment(env: dict[str, str]) -> dict[str, str]:
    retried = dict(env)
    shim = ROOT / "scripts" / "pdf2zh_ort_cpu_shim"
    existing = [item for item in str(retried.get("PYTHONPATH", "")).split(os.pathsep) if item]
    retried["PYTHONPATH"] = os.pathsep.join([str(shim), *existing])
    retried["PDF_READER_ORT_CPU_ONLY"] = "1"
    return retried


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


def append_engine_log(folder: Path, message: str) -> None:
    with (folder / "engine.log").open("a", encoding="utf-8") as stream:
        stream.write(message.rstrip() + "\n")


def ensure_localhost_no_proxy(env: dict[str, str]) -> dict[str, str]:
    """Force local Agent traffic to bypass desktop/system HTTP proxies."""
    required = ("127.0.0.1", "localhost", "::1")
    for key in ("NO_PROXY", "no_proxy"):
        existing = [item.strip() for item in str(env.get(key, "")).split(",") if item.strip()]
        folded = {item.casefold() for item in existing}
        env[key] = ",".join([*existing, *(item for item in required if item.casefold() not in folded)])
    return env


def with_temporary_environ(values: dict[str, str]):
    class Guard:
        def __enter__(self):
            self.previous = {key: os.environ.get(key) for key in values}
            os.environ.update(values)
            return self

        def __exit__(self, exc_type, exc, tb):
            for key, value in self.previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            return False

    return Guard()


def scan_route_count(plan: dict) -> int:
    return sum(1 for page in plan.get("pages", []) if page.get("route") == "ocr")


def log_scan_translation_report(folder: Path, report: dict, *, failed: bool = False, report_file: Path | None = None) -> None:
    pages = report.get("pages") or []
    for page in pages:
        layout = page.get("layout") or {}
        validation = layout.get("validation") or {}
        append_engine_log(
            folder,
            "scan page stats: "
            f"page={page.get('page')} status={page.get('status')} route={page.get('route')} "
            f"source={layout.get('source', page.get('layout_source'))} "
            f"model_attempted={layout.get('model_attempted', page.get('model_attempted'))} "
            f"model_error={layout.get('model_error', page.get('model_error'))} "
            f"model_elapsed={layout.get('model_elapsed_seconds')}s "
            f"blocks={page.get('block_count', len(layout.get('blocks') or []))} "
            f"paragraphs={page.get('paragraph_count', 0)} "
            f"mode={page.get('render_mode') or (page.get('render') or {}).get('mode')} "
            f"reason={page.get('render_reason') or (page.get('render') or {}).get('reason')} "
            f"reason_detail={(page.get('render') or {}).get('reason_detail')} "
            f"requests={page.get('translation_request_count', 0)} "
            f"validation_ok={validation.get('ok')} "
            f"errors={json.dumps(validation.get('errors') or [], ensure_ascii=False)} "
            f"elapsed={page.get('elapsed_seconds')}s",
        )
    if failed:
        append_engine_log(
            folder,
            "scan route failed: "
            f"reason={report.get('reason')} report={report_file or report.get('report_file')} "
            f"pages={len(pages)} elapsed={report.get('elapsed_seconds')}s",
        )


def run_scan_translation(folder: Path, original: Path, plan: dict, agent_env: dict[str, str],
                         output: Path, provider: str) -> dict:
    ocr_file = folder / "ocr-results.json"
    if not ocr_file.is_file():
        raise RuntimeError("扫描翻译缺少 ocr-results.json")
    ocr_results = json.loads(ocr_file.read_text(encoding="utf-8"))
    broker = TranslationBroker(folder / "scan-translation-cache.json")
    append_engine_log(folder, f"--- PDF Reader scan route: block paragraph overlay via {provider} ---")
    started = time.monotonic()
    try:
        with with_temporary_environ(agent_env):
            report = build_scan_translation_pdf(original, plan, ocr_results, output, broker)
    except ScanTranslationError as exc:
        report = exc.report or {}
        if exc.report_path:
            report["report_file"] = str(exc.report_path)
        log_scan_translation_report(folder, report, failed=True, report_file=exc.report_path)
        raise
    append_engine_log(
        folder,
        "scan route complete: "
        f"pages={report['page_count']} paragraphs={report['paragraph_count']} "
        f"requests={report['translation_metrics'].get('requests', 0)} "
        f"elapsed={round(time.monotonic() - started, 3)}s",
    )
    report_file = folder / "scan-translation-report.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log_scan_translation_report(folder, report, failed=False, report_file=report_file)
    return report


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
    env = ensure_localhost_no_proxy(os.environ.copy()); env.update(
        OPENAILIKED_BASE_URL=f"http://127.0.0.1:{port}/v1",
        OPENAILIKED_API_KEY=task_id,
        OPENAILIKED_MODEL=f"{provider}+{PROXY_BEHAVIOR_VERSION}",
    )
    document_plan = plan
    scan_pages = scan_route_count(document_plan)
    if scan_pages and int(plan.get("routes", {}).get("text", 0)) == 0:
        process = None
        try:
            task.update(status="running", message=f"正在用扫描段落管线翻译 {scan_pages} 页"); write_task(task)
            final = folder / "translated-zh.pdf"
            scan_report = run_scan_translation(folder, folder / "original.pdf", plan, env, final, provider)
            manifest = folder / "page-plan.json"
            manifest.write_text(json.dumps(scan_page_plan(plan, scan_report), ensure_ascii=False, indent=2), encoding="utf-8")
            dual = folder / "bilingual-side-by-side.pdf"
            merge_dual_pdf(folder / "original.pdf", final, dual)
            qa_alpha_file = folder / "qa-alpha.json"
            qa_source = folder / (task.get("searchable_file") or task.get("original_file", "original.pdf"))
            qa_alpha_cmd = [
                str(engine_python(engine)), str(ROOT / "scripts" / "qa_alpha.py"),
                str(qa_source), str(final), "--plan", str(manifest),
                "--visual-source", str(folder / (task.get("searchable_file") or task.get("original_file", "original.pdf"))),
                "--document-plan", str(folder / task.get("document_plan_file", "document-plan.json")),
                "--translation-warnings", str(folder / "translation-warnings.jsonl"),
                "--task-id", task_id, "--report", str(qa_alpha_file),
            ]
            audited = subprocess.run(qa_alpha_cmd, capture_output=True, text=True, timeout=1800)
            if audited.returncode or not qa_alpha_file.is_file():
                raise RuntimeError(f"Gate 1c-alpha QA 失败：{audited.stderr[-500:]}")
            page_plan = json.loads(manifest.read_text(encoding="utf-8"))
            alpha = json.loads(qa_alpha_file.read_text(encoding="utf-8"))
            translation_warnings = read_translation_warnings(folder)
            alpha["translation_warnings"] = translation_warnings
            final_status = (
                "needs_review" if alpha["status"] == "needs_review" else
                "completed_with_warnings" if alpha["status"] == "passed_with_warnings" or ocr_warnings or translation_warnings else
                "completed"
            )
            flagged = alpha.get("flagged_pages", [])
            final_message = (
                f"扫描段落翻译完成；确定性 QA 标记 {len(flagged)} 个问题页，需要复核"
                if final_status == "needs_review" else
                f"扫描段落翻译完成；确定性 QA/OCR/翻译共标记 {len(flagged) + len(ocr_warnings) + len(translation_warnings)} 个警告"
                if final_status == "completed_with_warnings" else
                "扫描段落翻译、合成与确定性 QA 均已通过"
            )
            task.update(
                status=final_status,
                translation_source_file=qa_source.name,
                translated_file=final.name,
                dual_file=dual.name,
                page_plan_file=manifest.name,
                page_type_counts=page_plan["qa"]["type_counts"],
                qa=page_plan["qa"],
                qa_alpha_file=qa_alpha_file.name,
                ocr_warnings=ocr_warnings,
                translation_warnings=translation_warnings,
                message=final_message,
                completed_at=time.time(),
            )
            alpha["contract"] = build_contract(
                original_path=qa_source, output_path=final, plan_path=manifest, task=task,
            )
            alpha["page_manifest"] = write_page_manifest(folder, task, final, alpha["contract"])
            alpha["freshness"] = verify_contract(
                alpha, original_path=qa_source, output_path=final, plan_path=manifest, task=task,
            )
            qa_alpha_file.write_text(json.dumps(alpha, ensure_ascii=False, indent=2), encoding="utf-8")
            task["page_manifest_file"] = "page-manifest.json"
            task["qa_alpha"] = summarize_qa(alpha, alpha.get("freshness"))
        except Exception as exc:
            task.update(status="failed", message=f"扫描段落翻译失败：{exc}")
        write_task(task)
        return
    cmd = [
        str(engine), str(source), "--service", "openailiked",
        "--thread", ENGINE_TRANSLATION_THREADS, "--output", str(output),
    ]
    log = folder / "engine.log"
    process = None
    try:
        terminate_recorded_engine(folder)
        engine_attempts = [
            {"cmd": cmd, "env": env, "cpu_retry": False},
        ]
        cpu_retry_used = False
        returncode = None
        candidates = []
        for attempt_index, attempt in enumerate(engine_attempts):
            if attempt["cpu_retry"]:
                cpu_retry_used = True
                latest = read_task(task_id)
                latest.update(
                    status="running",
                    message="版面分析 CoreML/ONNX Runtime 失败，正在自动切换 CPU 后端重试一次",
                )
                write_task(latest)
            with log.open("a" if attempt_index else "w") as stream:
                if attempt["cpu_retry"]:
                    stream.write("\n\n--- PDF Reader: retrying pdf2zh with CPU-only ONNX Runtime backend ---\n")
                    stream.flush()
                process = subprocess.Popen(attempt["cmd"], env=attempt["env"], stdout=stream, stderr=subprocess.STDOUT)
                (folder / "engine.pid").write_text(str(process.pid))
                timeout_hours = float(os.environ.get("PDF_READER_JOB_TIMEOUT_HOURS", "12"))
                deadline = time.monotonic() + timeout_hours * 3600
                engine_started_at = time.monotonic()
                while process.poll() is None:
                    if time.monotonic() > deadline:
                        process.terminate()
                        raise TimeoutError(f"超过 {timeout_hours:g} 小时仍未完成，已停止任务")
                    stream.flush()
                    recent = log.read_text(errors="replace")[-12000:]
                    progress = engine_progress(recent)
                    if progress:
                        done, total = progress
                        latest = read_task(task_id)
                        latest.update(
                            status="running",
                            progress_done=done,
                            progress_total=total,
                            message=f"正在通过 {provider} 翻译：{done}/{total} 个处理单元",
                        )
                        write_task(latest)
                    gateway_failures = engine_gateway_failure_count(recent)
                    if gateway_failures and time.monotonic() - engine_started_at >= 10:
                        latest = read_task(task_id)
                        latest.update(
                            status="running",
                            message=(
                                f"本机 Agent 请求暂时失败，正在有限重试 "
                                f"({min(gateway_failures, ENGINE_GATEWAY_FAILURE_LIMIT)}/"
                                f"{ENGINE_GATEWAY_FAILURE_LIMIT})"
                            ),
                        )
                        write_task(latest)
                    if gateway_failures >= ENGINE_GATEWAY_FAILURE_LIMIT:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        if attempt["cpu_retry"]:
                            raise RuntimeError(
                                "CoreML/ONNX Runtime 失败后已自动切换 CPU 后端重试一次；"
                                "CPU 重试期间本机 Agent 连续返回 HTTP 502/503/504，仍未成功。"
                                "请确认本机 Agent 可用后重试任务"
                            )
                        raise RuntimeError(
                            "本机 Agent 连续返回 HTTP 502/503/504；已停止无效重试。"
                            "请确认本机 Agent 可用后重试任务"
                        )
                    marker = engine_fatal_marker(recent)
                    if marker:
                        process.terminate()
                        try: process.wait(timeout=10)
                        except subprocess.TimeoutExpired: process.kill()
                        if attempt["cpu_retry"]:
                            raise RuntimeError(
                                "CoreML/ONNX Runtime 失败后已自动切换 CPU 后端重试一次；"
                                f"CPU 重试仍失败：检测到不可重试错误：{marker}"
                            )
                        raise RuntimeError(f"检测到不可重试错误：{marker}")
                    time.sleep(2)
            returncode = process.returncode
            candidates = sorted(output.glob("*-mono.pdf"), key=lambda p:p.stat().st_mtime, reverse=True)
            full_log = log.read_text(errors="replace")
            if not returncode and candidates:
                break
            if (
                attempt_index == 0
                and engine_coreml_ort_failure(returncode, full_log)
            ):
                engine_attempts.append({
                    "cmd": pdf2zh_cpu_retry_command(cmd),
                    "env": pdf2zh_cpu_retry_environment(env),
                    "cpu_retry": True,
                })
                continue
            if cpu_retry_used:
                raise RuntimeError(
                    f"翻译引擎退出码 {returncode}；已检测到 CoreML/ONNX Runtime "
                    "版面分析失败并自动切换 CPU 后端重试一次，仍未成功。请保留 engine.log 供排查"
                )
            raise RuntimeError(f"翻译引擎退出码 {returncode}")
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
        if scan_pages:
            task.update(status="running", message=f"正在回填 {scan_pages} 个扫描页段落译文"); write_task(task)
            scan_pdf = folder / "scan-translated-pages.pdf"
            scan_report = run_scan_translation(folder, folder / "original.pdf", document_plan, env, scan_pdf, provider)
            merged_final = folder / "translated-zh.scan-merged.pdf"
            merge_scan_pages(final, scan_pdf, document_plan, merged_final)
            merged_final.replace(final)
            ocr_pages = {
                int(item["page"]) for item in document_plan.get("pages", [])
                if item.get("route") == "ocr"
            }
            scan_plan_pages = {
                int(item["pdf_page"]): item
                for item in scan_page_plan(document_plan, scan_report).get("pages", [])
            }
            for page_item in plan.get("pages", []):
                if int(page_item.get("pdf_page", 0)) in ocr_pages:
                    page_item.update(scan_plan_pages[int(page_item["pdf_page"])])
            counts = {}
            for page_item in plan.get("pages", []):
                counts[page_item.get("type", "narrative")] = counts.get(page_item.get("type", "narrative"), 0) + 1
            plan.setdefault("qa", {})["type_counts"] = counts
            manifest.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
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
            completed_at=time.time(),
        )
        alpha["contract"] = build_contract(
            original_path=source, output_path=final, plan_path=manifest, task=task,
        )
        alpha["page_manifest"] = write_page_manifest(folder, task, final, alpha["contract"])
        alpha["freshness"] = verify_contract(
            alpha, original_path=source, output_path=final, plan_path=manifest, task=task,
        )
        qa_alpha_file.write_text(json.dumps(alpha, ensure_ascii=False, indent=2))
        task["page_manifest_file"] = "page-manifest.json"
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
        isolated_workspace = tempfile.TemporaryDirectory(prefix="pdf-reader-codex-")
        cmd = [
            "codex", "exec", "--ephemeral", "--ignore-rules", "--ignore-user-config",
            "--skip-git-repo-check", "-C", isolated_workspace.name, "-s", "read-only",
            "--disable", "shell_tool", "--disable", "unified_exec",
            "--disable", "apps", "--disable", "browser_use",
            "--disable", "in_app_browser", "--disable", "multi_agent", "-",
        ]
        # The paper is untrusted input.  stdin keeps it out of process listings;
        # disabling execution tools and using an empty workspace prevents the
        # translator from following document-borne instructions to read files.
        run_kwargs = {"input": prompt}
    else:
        isolated_workspace = None
        cmd = [
            "claude", "--print", "--safe-mode", "--setting-sources", "",
            "--strict-mcp-config", "--tools", "", "--no-session-persistence",
            "--system-prompt",
            "Translate the supplied source text faithfully into Chinese. Output only the translation, with no commentary or meta text.",
        ]
        # stdin keeps source beginning with '-' from being parsed as an option.
        run_kwargs = {"input": prompt}
    try:
        with MODEL_CLI_LOCK:
            done = runner(cmd, capture_output=True, text=True, timeout=180, **run_kwargs)
    finally:
        if isolated_workspace is not None:
            isolated_workspace.cleanup()
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


def proxy_error_kind(exc: Exception) -> str:
    detail = str(exc).casefold()
    if isinstance(exc, subprocess.TimeoutExpired) or "timed out" in detail or "timeout" in detail:
        return "timeout"
    if "argument list too long" in detail or getattr(exc, "errno", None) == 7:
        return "argument_too_long"
    if any(marker in detail for marker in ("502", "503", "504", "bad gateway")):
        return "upstream_gateway"
    if any(marker.casefold() in detail for marker in FATAL_ENGINE_MARKERS):
        return "authentication_or_cli_fatal"
    return "agent_cli_error"


def record_proxy_failure(task_id: str | None, provider: str, exc: Exception) -> None:
    """Persist failure class only; never persist prompts or source text."""
    if not task_id or not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
        return
    folder = task_dir(task_id)
    if not (folder / "task.json").is_file():
        return
    event = {
        "provider": provider,
        "kind": proxy_error_kind(exc),
        "exception_type": type(exc).__name__,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with PROXY_WARNING_LOCK:
        with (folder / "proxy-failures.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")


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
            record_proxy_failure(_request_task_id(self), provider, exc)
            return self.json({"error":{"message":str(exc)}}, 500)


def serve(host: str, port: int, open_browser: bool):
    DATA.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), ShimHandler)
    url = f"http://{host}:{server.server_port}"
    print(f"长 PDF 双语阅读器：{url}")
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
