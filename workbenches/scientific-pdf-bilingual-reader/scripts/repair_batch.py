#!/usr/bin/env python3
"""Document-level approved repair batches with page-by-page human gates."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import fitz

from artifact_transaction import install_artifact_set, next_version_dir
from dual_pdf import merge as merge_dual_pdf
from qa_alpha import audit
from qa_contract import (
    QA_RULE_VERSION, attention_summary, build_contract, new_deterministic_visual_violations,
    sha256_file, sha256_payload, verify_contract,
)
from review_cycle import (
    atomic_write_json,
    current_output_sha256,
    current_page_manifest,
    file_sha256,
    list_agent_reviews,
    list_comments,
    load_comment,
    page_contract,
    write_comment_object,
    write_page_manifest,
    write_versioned_object,
)
from review_workflow import (
    ALLOWED_FAMILIES, ensure_localhost_no_proxy, list_repairs,
    repair_record_path, run_model as run_review_model, task_artifact_path,
)


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_OBSERVATION_SCHEMA = ROOT / "references" / "candidate-observation-schema.json"
REPAIR_BATCH_SCHEMA = "repair-batch/v1"
PAGE_PATCH_SCHEMA = "page-patch/v1"
REPAIR_ITEM_SCHEMA = "repair-item-ref/v1"
OBSERVATION_SCHEMA = "candidate-page-observation/v1"
OPEN_BATCH_STATUSES = {
    "preflight_ready", "preflight_blocked", "repairing",
    "awaiting_page_decisions", "candidate_ready",
}
TERMINAL_BATCH_STATUSES = {"accepted", "rejected", "failed", "stale"}
PATCH_DECISIONS = {"include", "exclude", "defer"}
MUTATION_LOCK_TTL_SECONDS = 2 * 60 * 60
CANDIDATE_OBSERVATION_STALE_SECONDS = 420


def now() -> float:
    return time.time()


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text()) if path.is_file() else default
    except Exception:
        return default


def batch_root(folder: Path) -> Path:
    return folder / "review-cycle" / "repair-batches"


def batch_dir(folder: Path, batch_id: str) -> Path:
    return batch_root(folder) / Path(batch_id).name


def batch_path(folder: Path, batch_id: str) -> Path:
    return batch_dir(folder, batch_id) / "batch.json"


def mutation_lock_path(folder: Path) -> Path:
    return folder / "review-cycle" / "task-mutation-lock.json"


def page_patches_root(folder: Path, batch_id: str) -> Path:
    return batch_dir(folder, batch_id) / "page-patches"


def page_patch_path(folder: Path, batch_id: str, page_patch_id: str) -> Path:
    return page_patches_root(folder, batch_id) / f"{Path(page_patch_id).name}.json"


def list_repair_batches(folder: Path) -> list[dict]:
    records = []
    for path in sorted(batch_root(folder).glob("*/batch.json")) if batch_root(folder).is_dir() else []:
        record = read_json(path, {})
        if record.get("schema") == REPAIR_BATCH_SCHEMA:
            records.append(record)
    return sorted(records, key=lambda item: item.get("created_at", 0), reverse=True)


def load_repair_batch(folder: Path, batch_id: str) -> dict:
    record = read_json(batch_path(folder, batch_id), {})
    if record.get("schema") != REPAIR_BATCH_SCHEMA:
        raise ValueError("RepairBatch 不存在")
    return record


def list_page_patches(folder: Path, batch_id: str) -> list[dict]:
    records = []
    root = page_patches_root(folder, batch_id)
    for path in sorted(root.glob("*.json")) if root.is_dir() else []:
        record = read_json(path, {})
        if record.get("schema") == PAGE_PATCH_SCHEMA:
            records.append(record)
    return sorted(records, key=lambda item: int(item.get("pdf_page", 0)))


def open_repair_batches(folder: Path) -> list[dict]:
    return [item for item in list_repair_batches(folder) if item.get("status") in OPEN_BATCH_STATUSES]


def require_no_open_batch(folder: Path) -> None:
    active = open_repair_batches(folder)
    if active:
        current = active[0]
        raise RuntimeError(
            f"已有未关闭 RepairBatch：{current.get('batch_id')}（{current.get('status')}），请先继续或关闭它"
        )


def _pid_alive(pid: int | None) -> bool:
    if not pid or int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _active_lock(record: dict, now_value: float) -> bool:
    if not record:
        return False
    if float(record.get("expires_at") or 0) <= now_value:
        return False
    return _pid_alive(record.get("pid"))


def active_task_mutation(folder: Path) -> dict | None:
    record = read_json(mutation_lock_path(folder), {})
    return record if _active_lock(record, now()) else None


def acquire_task_mutation_lock(
    folder: Path, owner: str, *, ttl_seconds: int = MUTATION_LOCK_TTL_SECONDS,
) -> str:
    """Acquire the task write window and return its owner token."""
    path = mutation_lock_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    while True:
        now_value = now()
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            current = read_json(path, {})
            if _active_lock(current, now_value):
                raise RuntimeError(
                    f"任务正在执行写入窗口：{current.get('owner') or 'unknown'}，请稍后重试"
                )
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w") as stream:
            json.dump({
                "schema": "task-mutation-lock/v1",
                "owner": owner,
                "pid": os.getpid(),
                "token": token,
                "created_at": now_value,
                "expires_at": now_value + ttl_seconds,
            }, stream, ensure_ascii=False, indent=2)
        break
    return token


def release_task_mutation_lock(folder: Path, token: str) -> None:
    path = mutation_lock_path(folder)
    current = read_json(path, {})
    if current.get("token") == token:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def task_mutation_lock(folder: Path, owner: str, *, ttl_seconds: int = MUTATION_LOCK_TTL_SECONDS):
    """Short task-level write-window lock with stale PID/TTL release."""
    token = acquire_task_mutation_lock(folder, owner, ttl_seconds=ttl_seconds)
    try:
        yield
    finally:
        release_task_mutation_lock(folder, token)


def _same_page_fingerprint(left: dict | None, right: dict | None) -> bool:
    if not left or not right:
        return False
    return all(left.get(key) == right.get(key) for key in ("render_sha256", "text_sha256", "rect", "rotation"))


def _manifest_page(manifest: dict, pdf_page: int) -> dict | None:
    return next(
        (item for item in manifest.get("pages", []) if int(item.get("pdf_page", 0)) == int(pdf_page)),
        None,
    )


def _latest_review_for_comment(reviews: list[dict], comment_id: str) -> dict | None:
    matches = [item for item in reviews if item.get("comment_id") == comment_id and item.get("status") == "completed"]
    return max(matches, key=lambda item: item.get("created_at", 0), default=None)


def _comment_pool_item(comment: dict, review: dict | None, current_manifest: dict, output_sha: str | None) -> dict:
    page = int(comment.get("pdf_page", 0))
    page_review = (review or {}).get("result", {}).get("page_review", {})
    family = page_review.get("repair_family")
    current_page = _manifest_page(current_manifest, page)
    reasons = []
    if comment.get("latest_decision") != "agree_needs_change":
        reasons.append("尚未由使用者裁定为同意需修改")
    if not review:
        reasons.append("尚无完成的 AgentReview")
    elif page_review.get("is_real_problem") is False:
        reasons.append("最新 AgentReview 未确认需要修改")
    if family not in ALLOWED_FAMILIES:
        reasons.append("最新 AgentReview 没有可执行的问题族")
    if comment.get("current_output_sha256") != output_sha:
        reasons.append("Comment 绑定的正式译文版本已变化")
    if not _same_page_fingerprint(comment.get("page_fingerprint"), current_page):
        reasons.append("目标页已变化，需要重新核对")
    return {
        "schema": REPAIR_ITEM_SCHEMA,
        "key": f"comment:{comment.get('comment_id')}",
        "source_type": "comment",
        "source_id": comment.get("comment_id"),
        "source_version": comment.get("object_version"),
        "review_id": (review or {}).get("review_id"),
        "pdf_page": page,
        "family": family,
        "summary": comment.get("feedback", "")[:400],
        "protected_content": page_review.get("protected_content") or [],
        "success_type": "visual_only",
        "eligible": not reasons,
        "blocked_reasons": reasons,
        "page_fingerprint": current_page,
    }


def _machine_pool_item(record: dict, current_manifest: dict, output_sha: str | None) -> dict:
    page = int(record.get("pdf_page", 0))
    family = (record.get("execution_strategy") or {}).get("family") or (record.get("diagnosis") or {}).get("repair_family")
    current_page = _manifest_page(current_manifest, page)
    reasons = []
    if record.get("status") != "approved_for_batch":
        reasons.append("机器问题尚未批准进入整篇修复批次")
    if family not in ALLOWED_FAMILIES:
        reasons.append("诊断没有可执行的问题族")
    if (record.get("current_qa_contract") or {}).get("output_sha256") != output_sha:
        reasons.append("机器诊断绑定的正式译文版本已变化")
    return {
        "schema": REPAIR_ITEM_SCHEMA,
        "key": f"machine_issue:{record.get('repair_id')}",
        "source_type": "machine_issue",
        "source_id": record.get("repair_id"),
        "source_version": record.get("attempt_key_sha256"),
        "pdf_page": page,
        "family": family,
        "summary": (record.get("diagnosis") or {}).get("recommended_action", "")[:400],
        "protected_content": (record.get("claude_advice") or {}).get("protected_content") or [],
        "success_type": "machine_verifiable",
        "eligible": not reasons,
        "blocked_reasons": reasons,
        "page_fingerprint": current_page,
        "issue_ids": record.get("issue_ids") or [],
    }


def _progress(step: str, message: str, *, result_state: str | None = None) -> dict:
    payload = {"step": step, "message": message, "updated_at": now()}
    if result_state:
        payload["result_state"] = result_state
    return payload


def _write_batch_progress(folder: Path, batch_id: str, step: str, message: str, *, result_state: str | None = None) -> dict:
    path = batch_path(folder, batch_id)
    batch = load_repair_batch(folder, batch_id)
    batch["progress"] = _progress(step, message, result_state=result_state)
    if result_state:
        one_click = dict(batch.get("one_click") or {})
        one_click.update(result_state=result_state, updated_at=now())
        batch["one_click"] = one_click
    return write_versioned_object(path, batch)


def approved_repair_pool(folder: Path, task: dict) -> list[dict]:
    manifest = current_page_manifest(folder, task)
    output_sha = current_output_sha256(folder, task)
    reviews = list_agent_reviews(folder)
    pool = []
    for comment in list_comments(folder):
        if comment.get("latest_decision") == "agree_needs_change":
            pool.append(_comment_pool_item(
                comment, _latest_review_for_comment(reviews, comment.get("comment_id")), manifest, output_sha,
            ))
    for repair in list_repairs(folder):
        if repair.get("status") == "approved_for_batch":
            pool.append(_machine_pool_item(repair, manifest, output_sha))
    return sorted(pool, key=lambda item: (int(item.get("pdf_page", 0)), item.get("key", "")))


def approve_machine_repair(folder: Path, repair_id: str) -> dict:
    path = repair_record_path(folder, repair_id)
    record = read_json(path, {})
    if record.get("status") != "diagnosed":
        raise ValueError("只有已完成只读诊断的机器问题才能加入修复批次")
    if not (record.get("diagnosis") or {}).get("is_real_problem"):
        raise ValueError("只读诊断没有确认需要修复")
    if record.get("strategy_attempted_at"):
        raise RuntimeError("该单页策略已经执行，不能重复加入批次")
    record.update(status="approved_for_batch", approved_for_batch_at=now(), approved_by="june", updated_at=now())
    atomic_write_json(path, record)
    return record


def _preflight(items: list[dict]) -> dict:
    grouped: dict[int, list[dict]] = defaultdict(list)
    for item in items:
        grouped[int(item["pdf_page"])].append(item)
    page_plans = []
    conflicts = []
    for page, page_items in sorted(grouped.items()):
        families = sorted({item.get("family") for item in page_items})
        blocked = [reason for item in page_items for reason in item.get("blocked_reasons", [])]
        if len(families) > 1:
            blocked.append(f"同页存在多个不兼容问题族：{', '.join(families)}")
        if blocked:
            conflicts.append({"pdf_page": page, "reasons": list(dict.fromkeys(blocked))})
        page_plans.append({
            "pdf_page": page,
            "family": families[0] if len(families) == 1 else None,
            "repair_item_keys": [item["key"] for item in page_items],
            "source_count": len(page_items),
            "status": "blocked" if blocked else "ready",
            "blocked_reasons": list(dict.fromkeys(blocked)),
        })
    ready_pages = [item for item in page_plans if item["status"] == "ready"]
    return {
        "page_plans": page_plans,
        "conflicts": conflicts,
        "ready_page_count": len(ready_pages),
        "blocked_page_count": len(page_plans) - len(ready_pages),
        "estimated_ai_requests": len(ready_pages),
        "request_budget": 12,
        "budget_ok": len(ready_pages) <= 12,
    }


def create_repair_batch(folder: Path, task: dict, repair_item_keys: list[str]) -> dict:
    require_no_open_batch(folder)
    selected_keys = list(dict.fromkeys(str(item) for item in repair_item_keys if str(item)))
    if not selected_keys:
        raise ValueError("请至少选择一项已批准修复内容")
    pool = {item["key"]: item for item in approved_repair_pool(folder, task)}
    missing = [key for key in selected_keys if key not in pool]
    if missing:
        raise ValueError(f"修复项不存在或尚未批准：{', '.join(missing)}")
    selected = [pool[key] for key in selected_keys]
    ineligible = [item for item in selected if not item.get("eligible")]
    if ineligible:
        detail = "；".join(f"第 {item['pdf_page']} 页：{'、'.join(item['blocked_reasons'])}" for item in ineligible)
        raise RuntimeError(detail)
    base_sha = current_output_sha256(folder, task)
    manifest = current_page_manifest(folder, task)
    created_at = now()
    batch_id = "repair-batch-" + sha256_payload({
        "task_id": task.get("id"), "keys": selected_keys, "base_sha": base_sha, "created_at": created_at,
    })[:16]
    preflight = _preflight(selected)
    if not preflight["budget_ok"]:
        preflight["conflicts"].append({
            "pdf_page": None,
            "reasons": [f"预计 {preflight['estimated_ai_requests']} 次页面请求，超过每批 12 次上限；请拆批"],
        })
    record = {
        "schema": REPAIR_BATCH_SCHEMA,
        "batch_id": batch_id,
        "task_id": task.get("id"),
        "status": "preflight_ready" if not preflight["conflicts"] else "preflight_blocked",
        "base_output_sha256": base_sha,
        "base_manifest_id": manifest.get("manifest_id"),
        "base_manifest_sha256": manifest.get("manifest_sha256"),
        "repair_items": selected,
        "preflight": preflight,
        "page_patch_ids": [],
        "progress": _progress(
            "preflight",
            "预检通过，等待生成候选" if not preflight["conflicts"] else "预检需要补充要求或拆批",
            result_state="needs_more_info" if preflight["conflicts"] else None,
        ),
        "created_at": created_at,
    }
    return write_versioned_object(batch_path(folder, batch_id), record, expected_version=0)


def create_one_click_repair_batch(folder: Path, task: dict, repair_item_keys: list[str] | None = None) -> dict:
    keys = list(repair_item_keys or [])
    if not keys:
        keys = [item["key"] for item in approved_repair_pool(folder, task) if item.get("eligible")]
    batch = create_repair_batch(folder, task, keys)
    batch["one_click"] = {
        "enabled": True,
        "created_at": now(),
        "result_state": "needs_more_info" if batch.get("status") == "preflight_blocked" else None,
    }
    batch["progress"] = _progress(
        "preflight",
        "预检需要补充要求或拆批" if batch.get("status") == "preflight_blocked" else "预检通过，开始生成候选",
        result_state=batch["one_click"]["result_state"],
    )
    batch = write_versioned_object(batch_path(folder, batch["batch_id"]), batch)
    if batch.get("status") == "preflight_ready":
        batch = start_repair_batch(folder, task, batch["batch_id"])
        batch["one_click"] = {**(batch.get("one_click") or {}), "enabled": True}
        batch["progress"] = _progress("executing", "正在执行页面修复并运行机器门")
        batch = write_versioned_object(batch_path(folder, batch["batch_id"]), batch)
    return batch


def start_repair_batch(folder: Path, task: dict, batch_id: str) -> dict:
    record = load_repair_batch(folder, batch_id)
    if record.get("status") != "preflight_ready":
        raise ValueError("RepairBatch 预检尚未通过")
    if current_output_sha256(folder, task) != record.get("base_output_sha256"):
        record.update(status="stale", error="正式译文已变化，请重新建立 RepairBatch")
        write_versioned_object(batch_path(folder, batch_id), record)
        raise RuntimeError(record["error"])
    record.update(status="repairing", started_at=now(), error=None)
    record["progress"] = _progress("executing", "正在执行页面修复并运行机器门")
    return write_versioned_object(batch_path(folder, batch_id), record)


def execute_batch_harness(
    folder: Path,
    task: dict,
    batch: dict,
    output: Path,
    *,
    workbench_port: int,
    python_executable: str | None = None,
) -> tuple[dict, dict[str, Path]]:
    output.mkdir(parents=True, exist_ok=True)
    cases = [
        {"pdf_page": plan["pdf_page"], "family": plan["family"]}
        for plan in batch.get("preflight", {}).get("page_plans", []) if plan.get("status") == "ready"
    ]
    cases_path = output.parent / "cases.json"
    atomic_write_json(cases_path, {"cases": cases})
    env = ensure_localhost_no_proxy(os.environ.copy())
    env.update(
        OPENAILIKED_BASE_URL=f"http://127.0.0.1:{workbench_port}/v1",
        OPENAILIKED_API_KEY=str(task["id"]),
        OPENAILIKED_MODEL="codex",
    )
    python = python_executable or sys.executable
    cmd = [
        python, str(ROOT / "scripts" / "qa_repair_harness.py"), str(folder),
        "--cases", str(cases_path), "--output", str(output), "--full", "--task-id", str(task["id"]),
    ]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, env=env)
    if done.returncode:
        raise RuntimeError((done.stderr or done.stdout)[-1200:])
    result = read_json(output / "full-repair-result.json", {})
    files = {
        "translated": output / result.get("repaired_file", "translated-zh.repaired.pdf"),
        "qa": output / result.get("qa_file", "qa-repaired.json"),
        "plan": output / result.get("repaired_plan", "page-plan.repaired.json"),
    }
    if not all(path.is_file() for path in files.values()):
        raise RuntimeError("批量修复候选文件不完整")
    dual = output / "bilingual-side-by-side.repaired.pdf"
    merge_dual_pdf(task_artifact_path(folder, task, "original_file", "original.pdf"), files["translated"], dual)
    files["dual"] = dual
    return result, files


def _red_pages(report: dict) -> set[int]:
    return {int(item.get("pdf_page", 0)) for item in report.get("pages", []) if item.get("status") == "red"}


def _report_rule_version(report: dict) -> str | None:
    return (report.get("contract") or {}).get("qa_rule_version")


def _audit_current_output(folder: Path, task: dict) -> dict:
    return audit(
        task_artifact_path(folder, task, "translation_source_file", task.get("original_file", "original.pdf")),
        task_artifact_path(folder, task, "translated_file", "translated-zh.pdf"),
        task_artifact_path(folder, task, "page_plan_file", "page-plan.json"),
        task_id=str(task.get("id")),
        task_json_path=folder / "task.json",
        visual_source_path=(folder / task.get("original_file", "original.pdf")),
        document_plan_path=(folder / task.get("document_plan_file", "document-plan.json")) if task.get("document_plan_file") else None,
        translation_warnings_path=(folder / "translation-warnings.jsonl"),
    )


def _comparison_before_qa(folder: Path, task: dict, report: dict) -> dict:
    if _report_rule_version(report) == QA_RULE_VERSION:
        return report
    return _audit_current_output(folder, task)


def _protected_tokens_preserved(current_page: fitz.Page, candidate_page: fitz.Page, tokens: list[str]) -> tuple[bool, list[str]]:
    before = current_page.get_text("text") or ""
    after = candidate_page.get_text("text") or ""
    lost = [str(token) for token in tokens if str(token) and str(token) in before and str(token) not in after]
    return not lost, lost


def run_repair_batch(
    folder: Path,
    task: dict,
    batch_id: str,
    *,
    workbench_port: int = 8765,
    python_executable: str | None = None,
    repair_executor: Callable | None = None,
) -> dict:
    path = batch_path(folder, batch_id)
    batch = load_repair_batch(folder, batch_id)
    try:
        with task_mutation_lock(folder, f"repair-batch:{batch_id}:execute"):
            batch = _write_batch_progress(folder, batch_id, "executing", "正在执行页面修复并运行机器门")
            if batch.get("status") != "repairing":
                raise ValueError("RepairBatch 尚未获准生成候选")
            if current_output_sha256(folder, task) != batch.get("base_output_sha256"):
                raise RuntimeError("正式译文已变化，RepairBatch 已失效")
            output = batch_dir(folder, batch_id) / "execution"
            if repair_executor:
                result, files = repair_executor(folder, task, batch, output)
            else:
                result, files = execute_batch_harness(
                    folder, task, batch, output,
                    workbench_port=workbench_port, python_executable=python_executable,
                )
            if not all(Path(value).is_file() for value in files.values()):
                raise RuntimeError("批量修复执行结果不完整")
            integrity = result.get("non_target_integrity") or {}
            if integrity.get("mismatched_pages") or "checked_pages" not in integrity:
                raise RuntimeError("候选缺少非目标页不变证据")
            before_qa = _comparison_before_qa(
                folder,
                task,
                read_json(task_artifact_path(folder, task, "qa_alpha_file", "qa-alpha.json"), {}),
            )
            after_qa = read_json(Path(files["qa"]), {})
            before_red, after_red = _red_pages(before_qa), _red_pages(after_qa)
            new_red = sorted(after_red - before_red)
            current_doc = fitz.open(task_artifact_path(folder, task, "translated_file", "translated-zh.pdf"))
            candidate_doc = fitz.open(Path(files["translated"]))
            items_by_page: dict[int, list[dict]] = defaultdict(list)
            for item in batch.get("repair_items", []):
                items_by_page[int(item["pdf_page"])].append(item)
            patch_ids = []
            for plan in batch.get("preflight", {}).get("page_plans", []):
                if plan.get("status") != "ready":
                    continue
                page = int(plan["pdf_page"])
                items = items_by_page[page]
                current_contract = page_contract(current_doc[page - 1])
                candidate_contract = page_contract(candidate_doc[page - 1])
                changed = not _same_page_fingerprint(current_contract, candidate_contract)
                protected = list(dict.fromkeys(
                    token for item in items for token in (item.get("protected_content") or []) if str(token)
                ))
                protected_ok, lost_tokens = _protected_tokens_preserved(
                    current_doc[page - 1], candidate_doc[page - 1], protected,
                )
                has_machine = any(item.get("source_type") == "machine_issue" for item in items)
                reasons = []
                if not changed:
                    reasons.append("候选页与当前页没有可见或文本变化")
                if has_machine and page in after_red:
                    reasons.append("目标 red hard blocker 未消除")
                if page in new_red:
                    reasons.append("该页新增 red hard blocker")
                new_visual = new_deterministic_visual_violations(before_qa, after_qa, page)
                if new_visual:
                    kinds = sorted({item.get("issue_type") for item in new_visual})
                    reasons.append(f"候选页新增确定性视觉违规：{', '.join(kinds)}")
                if not protected_ok:
                    reasons.append(f"保护内容丢失：{', '.join(lost_tokens[:8])}")
                patch_id = "page-patch-" + sha256_payload({"batch_id": batch_id, "pdf_page": page})[:16]
                patch = {
                    "schema": PAGE_PATCH_SCHEMA,
                    "page_patch_id": patch_id,
                    "batch_id": batch_id,
                    "task_id": task.get("id"),
                    "pdf_page": page,
                    "family": plan.get("family"),
                    "repair_item_keys": plan.get("repair_item_keys") or [],
                    "status": "awaiting_decision" if not reasons else "failed",
                    "decision": "defer",
                    "decision_events": [],
                    "machine_gate": "pass" if not reasons else "blocked",
                    "machine_gate_reasons": reasons,
                    "new_deterministic_visual_violations": new_visual,
                    "current_page_fingerprint": current_contract,
                    "candidate_page_fingerprint": candidate_contract,
                    "protected_content": protected,
                    "lost_protected_content": lost_tokens,
                    "created_at": now(),
                }
                write_versioned_object(page_patch_path(folder, batch_id, patch_id), patch, expected_version=0)
                patch_ids.append(patch_id)
            current_doc.close()
            candidate_doc.close()
            pass_count = sum(
                read_json(page_patch_path(folder, batch_id, item), {}).get("status") == "awaiting_decision"
                for item in patch_ids
            )
            batch.update(
                status="awaiting_page_decisions" if pass_count else "failed",
                page_patch_ids=patch_ids,
                execution={
                    "translated": str(Path(files["translated"]).relative_to(folder)),
                    "dual": str(Path(files["dual"]).relative_to(folder)),
                    "qa": str(Path(files["qa"]).relative_to(folder)),
                    "plan": str(Path(files["plan"]).relative_to(folder)),
                    "non_target_integrity": integrity,
                    "new_red_pages": new_red,
                    "translation_metrics": result.get("translation_metrics") or {},
                },
                progress=_progress(
                    "page_gate",
                    f"机器门通过 {pass_count} 页；拦截 {len(patch_ids) - pass_count} 页",
                    result_state=None if pass_count else "blocked",
                ),
                completed_at=now(),
                error=None,
            )
            if batch.get("one_click") and not pass_count:
                batch["one_click"] = {**batch["one_click"], "result_state": "blocked", "updated_at": now()}
    except Exception as exc:
        batch.update(
            status="failed",
            error=str(exc)[:1200],
            progress=_progress("failed", str(exc)[:300], result_state="needs_more_info"),
            failed_at=now(),
        )
        if batch.get("one_click"):
            batch["one_click"] = {**batch["one_click"], "result_state": "needs_more_info", "updated_at": now()}
    return write_versioned_object(path, batch)


def set_page_patch_decision(
    folder: Path,
    batch_id: str,
    page_patch_id: str,
    decision: str,
    *,
    expected_version: int | None = None,
) -> dict:
    if decision not in PATCH_DECISIONS:
        raise ValueError("不支持的 PagePatch 决定")
    path = page_patch_path(folder, batch_id, page_patch_id)
    record = read_json(path, {})
    if record.get("schema") != PAGE_PATCH_SCHEMA:
        raise ValueError("PagePatch 不存在")
    if decision == "include" and record.get("machine_gate") != "pass":
        raise RuntimeError("该页未通过机器门，不能纳入最终候选")
    if record.get("decision") == decision:
        return record
    if expected_version is None:
        raise RuntimeError("缺少对象版本，请刷新后重试")
    event = {"decision": decision, "created_at": now()}
    record["decision"] = decision
    record["status"] = "included" if decision == "include" else "excluded" if decision == "exclude" else "awaiting_decision"
    record["decision_events"] = [*(record.get("decision_events") or []), event]
    return write_versioned_object(path, record, expected_version=expected_version)


def set_page_patch_decision_and_maybe_reassemble(
    folder: Path,
    task: dict,
    batch_id: str,
    page_patch_id: str,
    decision: str,
    *,
    expected_version: int | None = None,
) -> dict:
    batch_before = load_repair_batch(folder, batch_id)
    patch = set_page_patch_decision(
        folder, batch_id, page_patch_id, decision, expected_version=expected_version,
    )
    response = {"page_patch": patch}
    if batch_before.get("status") == "candidate_ready":
        included = [item for item in list_page_patches(folder, batch_id) if item.get("decision") == "include"]
        if included:
            response["batch"] = assemble_candidate(folder, task, batch_id)
        else:
            batch = load_repair_batch(folder, batch_id)
            batch.update(
                status="awaiting_page_decisions",
                candidate=None,
                progress=_progress("page_gate", "所有页面已剔除；请重新选择纳入页", result_state="needs_more_info"),
            )
            response["batch"] = write_versioned_object(batch_path(folder, batch_id), batch)
    return response


def run_one_click_repair_batch(
    folder: Path,
    task: dict,
    batch_id: str,
    *,
    workbench_port: int = 8765,
    python_executable: str | None = None,
    repair_executor: Callable | None = None,
) -> dict:
    batch = load_repair_batch(folder, batch_id)
    if batch.get("status") == "preflight_blocked":
        batch["one_click"] = {**(batch.get("one_click") or {}), "result_state": "needs_more_info", "updated_at": now()}
        batch["progress"] = _progress("needs_more_info", "预检被阻止，请补充要求或拆批", result_state="needs_more_info")
        return write_versioned_object(batch_path(folder, batch_id), batch)
    if batch.get("status") == "preflight_ready":
        start_repair_batch(folder, task, batch_id)
    completed = run_repair_batch(
        folder,
        task,
        batch_id,
        workbench_port=workbench_port,
        python_executable=python_executable,
        repair_executor=repair_executor,
    )
    if completed.get("status") != "awaiting_page_decisions":
        return completed
    _write_batch_progress(folder, batch_id, "including", "正在纳入所有 machine gate 通过页")
    pass_patches = [item for item in list_page_patches(folder, batch_id) if item.get("machine_gate") == "pass"]
    for patch in pass_patches:
        set_page_patch_decision(
            folder,
            batch_id,
            patch["page_patch_id"],
            "include",
            expected_version=patch.get("object_version"),
        )
    if not pass_patches:
        batch = load_repair_batch(folder, batch_id)
        batch["one_click"] = {**(batch.get("one_click") or {}), "result_state": "blocked", "updated_at": now()}
        batch["progress"] = _progress("blocked", "没有 machine gate 通过页可纳入", result_state="blocked")
        return write_versioned_object(batch_path(folder, batch_id), batch)
    try:
        return assemble_candidate(folder, task, batch_id)
    except Exception as exc:
        batch = load_repair_batch(folder, batch_id)
        batch["one_click"] = {**(batch.get("one_click") or {}), "result_state": "blocked", "updated_at": now()}
        batch["progress"] = _progress("blocked", str(exc)[:300], result_state="blocked")
        return write_versioned_object(batch_path(folder, batch_id), batch)


def _assemble_pages(current_path: Path, repaired_path: Path, output_path: Path, included_pages: set[int]) -> None:
    current, repaired = fitz.open(current_path), fitz.open(repaired_path)
    if len(current) != len(repaired):
        raise RuntimeError("修复候选页数与当前 PDF 不一致")
    result = fitz.open()
    for index in range(len(current)):
        source = repaired if index + 1 in included_pages else current
        result.insert_pdf(source, from_page=index, to_page=index)
    result.save(output_path, garbage=4, deflate=True)
    result.close()
    current.close()
    repaired.close()


def _assemble_plan(current_path: Path, repaired_path: Path, output_path: Path, included_pages: set[int]) -> None:
    current = read_json(current_path, {"version": 2, "pages": []})
    repaired = read_json(repaired_path, {"version": 2, "pages": []})
    current_pages = {int(item.get("pdf_page", 0)): item for item in current.get("pages", [])}
    repaired_pages = {int(item.get("pdf_page", 0)): item for item in repaired.get("pages", [])}
    pages = []
    for page in sorted(set(current_pages) | set(repaired_pages)):
        pages.append((repaired_pages if page in included_pages else current_pages).get(page, {}))
    payload = dict(current)
    payload["pages"] = pages
    atomic_write_json(output_path, payload)


def _page_record(report: dict, pdf_page: int) -> dict:
    return next(
        (item for item in report.get("pages", []) if int(item.get("pdf_page", 0)) == int(pdf_page)),
        {},
    )


def _plan_page(plan: dict, pdf_page: int) -> dict:
    return next(
        (item for item in plan.get("pages", []) if int(item.get("pdf_page", 0)) == int(pdf_page)),
        {},
    )


def _issue_rect(issue: dict) -> fitz.Rect | None:
    box = issue.get("bbox") or issue.get("rect") or issue.get("region")
    if isinstance(box, dict):
        values = [box.get(key) for key in ("x0", "y0", "x1", "y1")]
    elif isinstance(box, (list, tuple)) and len(box) >= 4:
        values = list(box[:4])
    else:
        return None
    try:
        rect = fitz.Rect(*(float(value) for value in values))
    except (TypeError, ValueError):
        return None
    return rect if not rect.is_empty and rect.is_valid else None


def _preview_clip(page: fitz.Page, issues: list[dict]) -> fitz.Rect:
    rects = [rect for issue in issues for rect in [_issue_rect(issue)] if rect]
    if not rects:
        return page.rect
    clip = rects[0]
    for rect in rects[1:]:
        clip |= rect
    clip = fitz.Rect(clip.x0 - 12, clip.y0 - 12, clip.x1 + 12, clip.y1 + 12)
    clip &= page.rect
    if clip.width < 48 or clip.height < 48:
        center = clip.tl + (clip.br - clip.tl) * 0.5
        clip = fitz.Rect(center.x - 72, center.y - 72, center.x + 72, center.y + 72) & page.rect
    return clip


def _render_clip(page: fitz.Page, clip: fitz.Rect, output: Path) -> None:
    zoom = min(2.0, max(1.0, 900 / max(clip.width, clip.height, 1)))
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
    pix.save(output)


def _fallbacks_from_plan(page_plan: dict) -> list[str]:
    candidates = []
    for key in ("fallbacks", "companion_fallbacks", "structured_fallbacks", "page_fallbacks"):
        value = page_plan.get(key)
        if isinstance(value, list):
            candidates.extend(str(item) for item in value if str(item))
        elif isinstance(value, dict):
            candidates.extend(f"{name}: {detail}" for name, detail in value.items())
    return list(dict.fromkeys(candidates))


def build_candidate_preview(
    folder: Path,
    task: dict,
    batch_id: str,
    candidate_pdf: Path,
    candidate_qa: dict,
    candidate_plan: dict,
    included_pages: set[int],
) -> dict:
    preview_dir = batch_dir(folder, batch_id) / "candidate" / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    current_pdf = task_artifact_path(folder, task, "translated_file", "translated-zh.pdf")
    before_doc = fitz.open(current_pdf)
    after_doc = fitz.open(candidate_pdf)
    execution = load_repair_batch(folder, batch_id).get("execution") or {}
    execution_qa = read_json(folder / execution.get("qa", ""), {})
    execution_plan = read_json(folder / execution.get("plan", ""), {})
    pages = []
    for patch in list_page_patches(folder, batch_id):
        pdf_page = int(patch.get("pdf_page", 0))
        if pdf_page not in included_pages:
            continue
        new_violations = patch.get("new_deterministic_visual_violations") or []
        qa_page = _page_record(candidate_qa, pdf_page)
        execution_page = _page_record(execution_qa, pdf_page)
        plan_page = _plan_page(candidate_plan, pdf_page) or _plan_page(execution_plan, pdf_page)
        issues_for_clip = new_violations or qa_page.get("issues") or execution_page.get("issues") or []
        clip = _preview_clip(after_doc[pdf_page - 1], issues_for_clip)
        before_name = f"page-{pdf_page:04d}-before.png"
        after_name = f"page-{pdf_page:04d}-after.png"
        _render_clip(before_doc[pdf_page - 1], clip, preview_dir / before_name)
        _render_clip(after_doc[pdf_page - 1], clip, preview_dir / after_name)
        pages.append({
            "pdf_page": pdf_page,
            "page_patch_id": patch.get("page_patch_id"),
            "clip": [round(value, 2) for value in (clip.x0, clip.y0, clip.x1, clip.y1)],
            "before_image": before_name,
            "after_image": after_name,
            "gate": {
                "machine_gate": patch.get("machine_gate"),
                "reasons": patch.get("machine_gate_reasons") or [],
                "metrics": qa_page.get("metrics") or execution_page.get("metrics") or {},
                "qa_status": qa_page.get("status") or execution_page.get("status"),
            },
            "fallbacks": _fallbacks_from_plan(plan_page),
            "new_violations": new_violations,
        })
    before_doc.close()
    after_doc.close()
    return {"changed_pages": pages, "created_at": now()}


def assemble_candidate(folder: Path, task: dict, batch_id: str) -> dict:
    path = batch_path(folder, batch_id)
    batch = load_repair_batch(folder, batch_id)
    try:
        with task_mutation_lock(folder, f"repair-batch:{batch_id}:assemble", ttl_seconds=15 * 60):
            batch = _write_batch_progress(folder, batch_id, "assembling", "正在组装整本候选并运行全篇检查")
            if batch.get("status") not in {"awaiting_page_decisions", "candidate_ready"}:
                raise ValueError("RepairBatch 尚未生成可选择的 PagePatch")
            if current_output_sha256(folder, task) != batch.get("base_output_sha256"):
                batch.update(status="stale", error="正式译文已变化，不能组装旧批次")
                write_versioned_object(path, batch)
                raise RuntimeError(batch["error"])
            included = {
                int(item["pdf_page"]) for item in list_page_patches(folder, batch_id)
                if item.get("decision") == "include"
            }
            if not included:
                raise ValueError("请先确认至少一个页面纳入最终候选")
            target = batch_dir(folder, batch_id) / "candidate"
            target.mkdir(parents=True, exist_ok=True)
            translated = target / "translated-zh.candidate.pdf"
            plan = target / "page-plan.candidate.json"
            execution = batch.get("execution") or {}
            _assemble_pages(
                task_artifact_path(folder, task, "translated_file", "translated-zh.pdf"),
                folder / execution["translated"], translated, included,
            )
            _assemble_plan(
                task_artifact_path(folder, task, "page_plan_file", "page-plan.json"),
                folder / execution["plan"], plan, included,
            )
            qa = audit(
                task_artifact_path(folder, task, "translation_source_file", task.get("original_file", "original.pdf")),
                translated,
                plan,
                task_id=str(task.get("id")),
                task_json_path=folder / "task.json",
                visual_source_path=(folder / task.get("original_file", "original.pdf")),
                document_plan_path=(folder / task.get("document_plan_file", "document-plan.json")) if task.get("document_plan_file") else None,
                translation_warnings_path=(folder / "translation-warnings.jsonl"),
            )
            qa_path = target / "qa-alpha.candidate.json"
            atomic_write_json(qa_path, qa)
            before = _comparison_before_qa(
                folder,
                task,
                read_json(task_artifact_path(folder, task, "qa_alpha_file", "qa-alpha.json"), {}),
            )
            new_red = sorted(_red_pages(qa) - _red_pages(before))
            if new_red:
                raise RuntimeError(f"最终候选新增 red 页面：{new_red}")
            dual = target / "bilingual-side-by-side.candidate.pdf"
            merge_dual_pdf(task_artifact_path(folder, task, "original_file", "original.pdf"), translated, dual)
            preview = build_candidate_preview(folder, task, batch_id, translated, qa, read_json(plan, {}), included)
            batch.update(
                status="candidate_ready",
                candidate={
                    "translated": str(translated.relative_to(folder)),
                    "dual": str(dual.relative_to(folder)),
                    "qa": str(qa_path.relative_to(folder)),
                    "plan": str(plan.relative_to(folder)),
                    "included_pages": sorted(included),
                    "qa_summary": qa.get("summary") or {},
                    "new_red_pages": new_red,
                    "preview": preview,
                },
                progress=_progress("ready", "候选已通过全篇检查，等待人工验收", result_state="acceptable"),
                candidate_created_at=now(),
            )
            if batch.get("one_click"):
                batch["one_click"] = {**batch["one_click"], "result_state": "acceptable", "updated_at": now()}
            return write_versioned_object(path, batch)
    except Exception as exc:
        batch = load_repair_batch(folder, batch_id)
        if batch.get("one_click"):
            batch["one_click"] = {**(batch.get("one_click") or {}), "result_state": "blocked", "updated_at": now()}
            batch["progress"] = _progress("blocked", str(exc)[:300], result_state="blocked")
            write_versioned_object(path, batch)
        raise


def batch_candidate_file(folder: Path, batch_id: str, kind: str) -> Path | None:
    batch = load_repair_batch(folder, batch_id)
    relative = (batch.get("candidate") or {}).get(kind) or (batch.get("execution") or {}).get(kind)
    if not relative:
        return None
    target = (folder / relative).resolve()
    return target if folder.resolve() in target.parents and target.is_file() else None


def batch_preview_file(folder: Path, batch_id: str, filename: str) -> Path | None:
    name = Path(filename).name
    target = (batch_dir(folder, batch_id) / "candidate" / "preview" / name).resolve()
    return target if folder.resolve() in target.parents and target.is_file() else None


def observations_root(folder: Path, batch_id: str) -> Path:
    return batch_dir(folder, batch_id) / "candidate" / "observations"


def candidate_observation_path(folder: Path, batch_id: str, pdf_page: int) -> Path:
    return observations_root(folder, batch_id) / f"page-{int(pdf_page):04d}-observation.json"


def candidate_observation_output(folder: Path, batch_id: str, pdf_page: int) -> Path:
    return observations_root(folder, batch_id) / f"page-{int(pdf_page):04d}-model-output.json"


def _candidate_observation_prompt(task: dict, batch: dict, preview_page: dict, patch: dict) -> str:
    keys = set(patch.get("repair_item_keys") or [])
    items = [item for item in batch.get("repair_items", []) if item.get("key") in keys]
    compact_items = [
        {
            "source_type": item.get("source_type"),
            "pdf_page": item.get("pdf_page"),
            "family": item.get("family"),
            "summary": item.get("summary"),
            "protected_content": item.get("protected_content") or [],
        }
        for item in items
    ]
    return f"""你是科研 PDF 双语阅读器的验收预览观察员。只看图、只给建议，不做门禁决定，不要求修改文件。

文档：{task.get('name')}
候选批次：{batch.get('batch_id')}
页码：{preview_page.get('pdf_page')}
修复项：{json.dumps(compact_items, ensure_ascii=False)}
机器门：{json.dumps(preview_page.get('gate') or {}, ensure_ascii=False)}
Fallbacks：{json.dumps(preview_page.get('fallbacks') or [], ensure_ascii=False)}
新增违规：{json.dumps(preview_page.get('new_violations') or [], ensure_ascii=False)}

请比较两张图片：第一张是修复前裁剪图，第二张是修复后裁剪图。必须覆盖：
1. 阅读顺序是否被破坏。
2. 图表、数字、公式、参考编号和 protected_content 是否完整。
3. Comment 或机器修复项指向的问题是否真的改善。

只输出符合 schema 的 JSON。repair_family 按最接近的修复类型填写，若只是一般视觉观察填 layout。"""


def _observation_public(record: dict) -> dict:
    if not record:
        return {"status": "pending"}
    payload = {
        "status": record.get("status") or "pending",
        "provider": record.get("provider"),
        "created_at": record.get("created_at"),
        "completed_at": record.get("completed_at"),
    }
    if record.get("status") == "ready":
        payload["result"] = record.get("result") or {}
    elif record.get("status") == "unavailable":
        payload["message"] = record.get("message") or "标注不可用"
    return payload


def _observation_cache_reusable(record: dict, now_value: float) -> bool:
    if record.get("schema") != OBSERVATION_SCHEMA:
        return False
    status = record.get("status")
    if status in {"ready", "unavailable"}:
        return True
    if status == "running":
        return now_value - float(record.get("created_at") or 0) <= CANDIDATE_OBSERVATION_STALE_SECONDS
    return False


def hydrate_candidate_observations(folder: Path, batch: dict) -> dict:
    candidate = batch.get("candidate") or {}
    preview = candidate.get("preview") or {}
    changed_pages = []
    for page in preview.get("changed_pages") or []:
        pdf_page = int(page.get("pdf_page", 0))
        record = read_json(candidate_observation_path(folder, batch["batch_id"], pdf_page), {})
        changed_pages.append({**page, "model_observation": _observation_public(record)})
    if not changed_pages:
        return batch
    hydrated = dict(batch)
    hydrated["candidate"] = {
        **candidate,
        "preview": {**preview, "changed_pages": changed_pages},
    }
    return hydrated


def run_candidate_observations(
    folder: Path,
    task: dict,
    batch_id: str,
    *,
    provider: str = "claude",
    observation_provider: Callable | None = None,
) -> list[dict]:
    batch = load_repair_batch(folder, batch_id)
    if batch.get("status") != "candidate_ready":
        raise ValueError("只有最终候选可生成模型观察")
    if provider not in {"claude", "codex"}:
        raise ValueError("不支持的审阅提供方")
    root = observations_root(folder, batch_id)
    root.mkdir(parents=True, exist_ok=True)
    outputs = []
    pages = ((batch.get("candidate") or {}).get("preview") or {}).get("changed_pages") or []
    patches = {int(item.get("pdf_page", 0)): item for item in list_page_patches(folder, batch_id)}
    for preview_page in pages:
        pdf_page = int(preview_page.get("pdf_page", 0))
        path = candidate_observation_path(folder, batch_id, pdf_page)
        existing = read_json(path, {})
        if _observation_cache_reusable(existing, now()):
            outputs.append(existing)
            continue
        started = {
            "schema": OBSERVATION_SCHEMA,
            "status": "running",
            "provider": provider,
            "pdf_page": pdf_page,
            "created_at": now(),
        }
        atomic_write_json(path, started)
        try:
            before = batch_preview_file(folder, batch_id, str(preview_page.get("before_image") or ""))
            after = batch_preview_file(folder, batch_id, str(preview_page.get("after_image") or ""))
            if not before or not after:
                raise RuntimeError("候选页预览图缺失")
            patch = patches.get(pdf_page, {})
            if observation_provider:
                result = observation_provider(batch, preview_page, patch)
            else:
                result = run_review_model(
                    provider,
                    _candidate_observation_prompt(task, batch, preview_page, patch),
                    before,
                    after,
                    candidate_observation_output(folder, batch_id, pdf_page),
                    CANDIDATE_OBSERVATION_SCHEMA,
                )
            record = {
                **started,
                "status": "ready",
                "result": result,
                "completed_at": now(),
            }
        except Exception as exc:
            record = {
                **started,
                "status": "unavailable",
                "message": "标注不可用",
                "error": str(exc)[:1000],
                "completed_at": now(),
            }
        atomic_write_json(path, record)
        outputs.append(record)
    return outputs


def _qa_projection(report: dict, freshness: dict) -> dict:
    return {
        "status": report.get("status"),
        "summary": report.get("summary", {}),
        "issue_category_summary": report.get("issue_category_summary", {}),
        "flagged_pages": report.get("flagged_pages", []),
        "baseline": report.get("baseline"),
        "quality_gate": report.get("quality_gate"),
        "attention": attention_summary(report.get("pages", []), report.get("document_issues", [])),
        "contract": {
            "schema": report.get("contract", {}).get("schema"),
            "qa_rule_version": report.get("contract", {}).get("qa_rule_version"),
            "contract_sha256": report.get("contract", {}).get("contract_sha256"),
        },
        "freshness": freshness,
    }


def _accept_candidate_unlocked(folder: Path, task: dict, batch_id: str) -> dict:
    path = batch_path(folder, batch_id)
    batch = load_repair_batch(folder, batch_id)
    if batch.get("status") != "candidate_ready":
        raise ValueError("没有等待验收的 RepairBatch 最终候选")
    if current_output_sha256(folder, task) != batch.get("base_output_sha256"):
        raise RuntimeError("正式译文已变化，不能安装旧候选")
    files = {
        "translated-zh.pdf": batch_candidate_file(folder, batch_id, "translated"),
        "bilingual-side-by-side.pdf": batch_candidate_file(folder, batch_id, "dual"),
        "qa-alpha.json": batch_candidate_file(folder, batch_id, "qa"),
        "page-plan.json": batch_candidate_file(folder, batch_id, "plan"),
    }
    if not all(files.values()):
        raise RuntimeError("最终候选文件不完整")
    current_files = {
        "translated-zh.pdf": task_artifact_path(folder, task, "translated_file", "translated-zh.pdf"),
        "bilingual-side-by-side.pdf": task_artifact_path(folder, task, "dual_file", "bilingual-side-by-side.pdf"),
        "qa-alpha.json": task_artifact_path(folder, task, "qa_alpha_file", "qa-alpha.json"),
        "page-plan.json": task_artifact_path(folder, task, "page_plan_file", "page-plan.json"),
    }
    final_task = dict(task)
    final_task.update(
        translated_file="translated-zh.pdf", dual_file="bilingual-side-by-side.pdf",
        qa_alpha_file="qa-alpha.json", page_plan_file="page-plan.json",
    )
    qa = read_json(files["qa-alpha.json"], {})
    qa["contract"] = build_contract(
        original_path=folder / task.get("translation_source_file", task.get("original_file", "original.pdf")),
        output_path=files["translated-zh.pdf"], plan_path=files["page-plan.json"], task=final_task,
    )
    version = next_version_dir(folder, batch_id)
    receipt = {
        "schema": "repair-batch-acceptance-receipt/v1",
        "batch_id": batch_id,
        "accepted_at": now(),
        "included_pages": (batch.get("candidate") or {}).get("included_pages") or [],
        "pre_accept_hashes": {name: sha256_file(source) for name, source in current_files.items()},
        "candidate_hashes": {name: sha256_file(source) for name, source in files.items()},
    }
    for name, source in current_files.items():
        shutil.copy2(source, version / name)
    prepared = dict(files)
    qa_candidate = version / "qa-alpha.candidate.json"
    qa_candidate.write_text(json.dumps(qa, ensure_ascii=False, indent=2))
    prepared["qa-alpha.json"] = qa_candidate
    install_artifact_set(folder, prepared, version)
    manifest_ref = write_page_manifest(folder, final_task, folder / "translated-zh.pdf", qa.get("contract"))
    installed_qa = read_json(folder / "qa-alpha.json", {})
    installed_qa["page_manifest"] = manifest_ref
    atomic_write_json(folder / "qa-alpha.json", installed_qa)
    freshness = verify_contract(
        installed_qa,
        original_path=folder / task.get("translation_source_file", task.get("original_file", "original.pdf")),
        output_path=folder / "translated-zh.pdf", plan_path=folder / "page-plan.json", task=final_task,
    )
    receipt.update(page_manifest=manifest_ref, freshness_after_install=freshness)
    atomic_write_json(version / "acceptance-receipt.json", receipt)
    included_keys = {
        key for patch in list_page_patches(folder, batch_id) if patch.get("decision") == "include"
        for key in patch.get("repair_item_keys", [])
    }
    accepted_comment_ids = set()
    for item in batch.get("repair_items", []):
        if item.get("key") not in included_keys:
            continue
        if item.get("source_type") == "comment":
            accepted_comment_ids.add(item["source_id"])
            comment = load_comment(folder, item["source_id"])
            comment["candidate_results"] = [*(comment.get("candidate_results") or []), {
                "batch_id": batch_id, "status": "accepted", "accepted_at": now(),
            }]
            comment["status"] = "repair_applied"
            write_comment_object(folder, comment["comment_id"], comment)
        elif item.get("source_type") == "machine_issue":
            repair_path = repair_record_path(folder, item["source_id"])
            repair = read_json(repair_path, {})
            repair.update(status="batch_accepted", batch_id=batch_id, accepted_at=now(), updated_at=now())
            atomic_write_json(repair_path, repair)
    installed_manifest = current_page_manifest(folder, final_task)
    for comment in list_comments(folder):
        if comment.get("comment_id") in accepted_comment_ids:
            continue
        current_page = _manifest_page(installed_manifest, int(comment.get("pdf_page", 0)))
        if not current_page:
            comment["status"] = "stale_anchor"
        elif not _same_page_fingerprint(comment.get("page_fingerprint"), current_page):
            comment["status"] = "needs_recheck"
        comment["version_recheck"] = {
            "batch_id": batch_id,
            "checked_at": now(),
            "page_unchanged": _same_page_fingerprint(comment.get("page_fingerprint"), current_page),
            "installed_manifest_id": installed_manifest.get("manifest_id"),
        }
        write_comment_object(folder, comment["comment_id"], comment)
    status_map = {"needs_review": "needs_review", "passed_with_warnings": "completed_with_warnings", "passed": "completed"}
    task.update(
        status=status_map.get(installed_qa.get("status"), "needs_review"),
        translated_file="translated-zh.pdf", dual_file="bilingual-side-by-side.pdf",
        qa_alpha_file="qa-alpha.json", page_plan_file="page-plan.json", page_manifest_file="page-manifest.json",
        qa_alpha=_qa_projection(installed_qa, freshness),
        contract_warning=None if freshness.get("status") == "fresh" else {
            "status": freshness.get("status"),
            "message": freshness.get("message") or "安装后的 QA contract 需要重审",
        },
        message=f"已接受 RepairBatch 的 {len(receipt['included_pages'])} 个页面；旧版本已备份",
    )
    batch.update(status="accepted", accepted_at=now(), accepted_by="june", receipt=str((version / "acceptance-receipt.json").relative_to(folder)))
    write_versioned_object(path, batch)
    return task


def accept_candidate(folder: Path, task: dict, batch_id: str) -> dict:
    with task_mutation_lock(folder, f"repair-batch:{batch_id}:install", ttl_seconds=15 * 60):
        return _accept_candidate_unlocked(folder, task, batch_id)


def reject_candidate(folder: Path, batch_id: str) -> dict:
    path = batch_path(folder, batch_id)
    batch = load_repair_batch(folder, batch_id)
    if batch.get("status") not in {"candidate_ready", "awaiting_page_decisions", "preflight_blocked", "failed"}:
        raise ValueError("当前 RepairBatch 不能关闭")
    batch.update(status="rejected", rejected_at=now())
    return write_versioned_object(path, batch)


def formal_output_status(folder: Path, task: dict, batches: list[dict]) -> dict:
    output_sha = current_output_sha256(folder, task)
    manifest = read_json(folder / (task.get("page_manifest_file") or "page-manifest.json"), {})
    accepted = next(
        (
            item for item in sorted(batches, key=lambda entry: entry.get("accepted_at", 0), reverse=True)
            if item.get("status") == "accepted"
        ),
        None,
    )
    source_kind = "initial_translation"
    source_batch_id = None
    translated_path = task_artifact_path(folder, task, "translated_file", "translated-zh.pdf")
    installed_at = (
        translated_path.stat().st_mtime if translated_path.is_file() else None
    ) or task.get("completed_at") or task.get("updated_at") or task.get("created_at")
    receipt_path = None
    if accepted:
        source_kind = "repair_batch"
        source_batch_id = accepted.get("batch_id")
        installed_at = accepted.get("accepted_at")
        receipt_path = accepted.get("receipt")
    freshness = None
    warning = None
    report = read_json(task_artifact_path(folder, task, "qa_alpha_file", "qa-alpha.json"), {})
    if report.get("contract"):
        try:
            freshness = verify_contract(
                report,
                original_path=folder / task.get("translation_source_file", task.get("original_file", "original.pdf")),
                output_path=task_artifact_path(folder, task, "translated_file", "translated-zh.pdf"),
                plan_path=task_artifact_path(folder, task, "page_plan_file", "page-plan.json"),
                task=task,
            )
        except Exception as exc:
            freshness = {"status": "stale", "message": str(exc)[:300]}
        if freshness.get("status") != "fresh":
            warning = {
                "status": freshness.get("status"),
                "message": freshness.get("message") or "QA contract 与当前正式稿不一致",
            }
    return {
        "current_output_sha256": output_sha,
        "page_manifest_id": manifest.get("manifest_id"),
        "page_manifest_sha256": manifest.get("manifest_sha256"),
        "source_kind": source_kind,
        "source_batch_id": source_batch_id,
        "installed_at": installed_at,
        "receipt": receipt_path,
        "contract_freshness": freshness,
        "contract_warning": warning,
    }


def repair_batch_projection(folder: Path, task: dict) -> dict:
    batches = [
        hydrate_candidate_observations(folder, item) if item.get("status") == "candidate_ready" else item
        for item in list_repair_batches(folder)
    ]
    patches = {item["batch_id"]: list_page_patches(folder, item["batch_id"]) for item in batches}
    pool = approved_repair_pool(folder, task)
    open_batch = next((item for item in batches if item.get("status") in OPEN_BATCH_STATUSES), None)
    ready_candidate = next(
        (item for item in batches if item.get("status") == "candidate_ready"), None,
    )
    return {
        "formal_output": formal_output_status(folder, task, batches),
        "approved_repair_items": pool,
        "approved_repair_item_count": sum(1 for item in pool if item.get("eligible")),
        "blocked_repair_item_count": sum(1 for item in pool if not item.get("eligible")),
        "repair_batches": batches,
        "page_patches": patches,
        "open_repair_batch_id": (open_batch or {}).get("batch_id"),
        "open_repair_batch_status": (open_batch or {}).get("status"),
        "ready_candidate_id": (ready_candidate or {}).get("batch_id"),
        "ready_candidate_status": (ready_candidate or {}).get("status"),
        "has_uninstalled_candidate": bool(ready_candidate),
    }
