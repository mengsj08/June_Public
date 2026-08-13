#!/usr/bin/env python3
"""Review-cycle storage for page manifests, comments, and agent review jobs."""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable


PAGE_MANIFEST_SCHEMA = "page-manifest/v1"
COMMENT_SCHEMA = "review-comment/v1"
AGENT_REVIEW_SCHEMA = "agent-review/v1"
AGENT_REVIEW_JOB_SCHEMA = "agent-review-job/v1"
TRASH_RECEIPT_SCHEMA = "task-trash-receipt/v1"
ALLOWED_COMMENT_DECISIONS = {
    "agree_needs_change",
    "agree_no_change",
    "not_adopted",
    "deferred",
    "needs_more_info",
}

RUNNERS_LOCK = threading.Lock()
RUNNERS: set[str] = set()
COMMENT_LOCKS_LOCK = threading.Lock()
COMMENT_LOCKS: dict[str, threading.RLock] = {}


def now() -> float:
    return time.time()


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text()) if path.is_file() else default
    except Exception:
        return default


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def file_sha256(path: Path | None) -> dict[str, Any] | None:
    if not path or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return {"sha256": digest.hexdigest(), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    temp.replace(path)


def write_versioned_object(path: Path, payload: dict, *, expected_version: int | None = None) -> dict:
    current = read_json(path, {}) if path.is_file() else {}
    if expected_version is not None and int(current.get("object_version", 0)) != int(expected_version):
        raise RuntimeError("对象版本已变化，请刷新后重试")
    payload = dict(payload)
    payload["object_version"] = int(current.get("object_version", 0)) + 1
    payload["updated_at"] = now()
    atomic_write_json(path, payload)
    return payload


def comment_object_lock(comment_id: str) -> threading.RLock:
    with COMMENT_LOCKS_LOCK:
        lock = COMMENT_LOCKS.get(comment_id)
        if lock is None:
            lock = threading.RLock()
            COMMENT_LOCKS[comment_id] = lock
        return lock


def write_comment_object(
    folder: Path,
    comment_id: str,
    payload: dict,
    *,
    expected_version: int | None = None,
) -> dict:
    with comment_object_lock(comment_id):
        return write_versioned_object(comment_path(folder, comment_id), payload, expected_version=expected_version)


def review_cycle_root(folder: Path) -> Path:
    return folder / "review-cycle"


def comments_root(folder: Path) -> Path:
    return review_cycle_root(folder) / "comments"


def agent_reviews_root(folder: Path) -> Path:
    return review_cycle_root(folder) / "agent-reviews"


def agent_jobs_root(folder: Path) -> Path:
    return review_cycle_root(folder) / "agent-review-jobs"


def comment_path(folder: Path, comment_id: str) -> Path:
    return comments_root(folder) / f"{comment_id}.json"


def agent_review_path(folder: Path, review_id: str) -> Path:
    return agent_reviews_root(folder) / f"{review_id}.json"


def agent_job_path(folder: Path, job_id: str) -> Path:
    return agent_jobs_root(folder) / f"{job_id}.json"


def manifest_root(folder: Path) -> Path:
    return folder / "page-manifests"


def manifest_path(folder: Path, manifest_id: str) -> Path:
    return manifest_root(folder) / f"{manifest_id}.json"


def page_contract(page) -> dict:
    import fitz

    pixmap = page.get_pixmap(matrix=fitz.Matrix(96 / 72, 96 / 72), alpha=False)
    text = page.get_text("text").encode("utf-8")
    rect = [round(value, 4) for value in page.rect]
    return {
        "render_sha256": hashlib.sha256(pixmap.samples).hexdigest(),
        "text_sha256": hashlib.sha256(text).hexdigest(),
        "rect": rect,
        "width": rect[2] - rect[0],
        "height": rect[3] - rect[1],
        "rotation": page.rotation,
    }


def build_page_manifest(folder: Path, task: dict, translated_pdf: Path, qa_contract: dict | None = None) -> dict:
    import fitz

    document = fitz.open(translated_pdf)
    output_hash = file_sha256(translated_pdf)
    manifest_seed = {
        "task_id": task.get("id"),
        "translated_pdf": output_hash,
        "qa_contract_sha256": (qa_contract or {}).get("contract_sha256"),
    }
    manifest_id = "page-manifest-" + sha256_payload(manifest_seed)[:16]
    pages = []
    for index, page in enumerate(document):
        pages.append({"pdf_page": index + 1, **page_contract(page)})
    payload = {
        "schema": PAGE_MANIFEST_SCHEMA,
        "manifest_id": manifest_id,
        "task_id": task.get("id"),
        "created_at": now(),
        "translated_file": translated_pdf.name,
        "translated_pdf": output_hash,
        "qa_contract": {
            "schema": (qa_contract or {}).get("schema"),
            "qa_rule_version": (qa_contract or {}).get("qa_rule_version"),
            "contract_sha256": (qa_contract or {}).get("contract_sha256"),
        } if qa_contract else None,
        "page_count": len(pages),
        "pages": pages,
    }
    payload["manifest_sha256"] = sha256_payload({
        key: value for key, value in payload.items() if key != "manifest_sha256"
    })
    return payload


def write_page_manifest(folder: Path, task: dict, translated_pdf: Path, qa_contract: dict | None = None) -> dict:
    manifest = build_page_manifest(folder, task, translated_pdf, qa_contract)
    path = manifest_path(folder, manifest["manifest_id"])
    manifest = write_versioned_object(path, manifest, expected_version=0 if not path.exists() else None)
    current = folder / "page-manifest.json"
    atomic_write_json(current, manifest)
    return {
        "schema": PAGE_MANIFEST_SCHEMA,
        "manifest_id": manifest["manifest_id"],
        "path": str(path.relative_to(folder)),
        "current_path": current.name,
        "sha256": file_sha256(path)["sha256"],
        "page_count": manifest["page_count"],
    }


def current_page_manifest(folder: Path, task: dict) -> dict:
    ref = task.get("page_manifest_file") or "page-manifest.json"
    manifest = read_json(folder / ref, {})
    if manifest.get("schema") == PAGE_MANIFEST_SCHEMA:
        return manifest
    translated = folder / task.get("translated_file", "translated-zh.pdf")
    if not translated.is_file():
        raise RuntimeError("当前译文缺少 PageManifest，且译文文件不存在")
    written = write_page_manifest(folder, task, translated)
    return read_json(folder / written["current_path"], {})


def page_fingerprint(folder: Path, task: dict, pdf_page: int) -> tuple[dict, dict]:
    manifest = current_page_manifest(folder, task)
    page = next((item for item in manifest.get("pages", []) if int(item.get("pdf_page", 0)) == int(pdf_page)), None)
    if not page:
        raise ValueError("页码超出当前 PDF 范围")
    return manifest, page


def current_output_sha256(folder: Path, task: dict) -> str | None:
    translated = folder / task.get("translated_file", "translated-zh.pdf")
    hashed = file_sha256(translated)
    return hashed.get("sha256") if hashed else None


def create_comment(folder: Path, task: dict, pdf_page: int, feedback: str) -> dict:
    feedback = str(feedback).strip()
    if not feedback:
        raise ValueError("请先填写 Comment")
    manifest, page = page_fingerprint(folder, task, pdf_page)
    created_at = now()
    comment_id = "comment-" + sha256_payload({
        "task_id": task.get("id"),
        "pdf_page": int(pdf_page),
        "feedback": feedback,
        "created_at": created_at,
    })[:16]
    record = {
        "schema": COMMENT_SCHEMA,
        "comment_id": comment_id,
        "task_id": task.get("id"),
        "pdf_page": int(pdf_page),
        "feedback": feedback[:4000],
        "status": "saved",
        "current_output_sha256": current_output_sha256(folder, task),
        "page_manifest_id": manifest.get("manifest_id"),
        "page_manifest_sha256": manifest.get("manifest_sha256"),
        "page_fingerprint": page,
        "agent_review_ids": [],
        "decision_events": [],
        "candidate_results": [],
        "created_at": created_at,
    }
    return write_comment_object(folder, comment_id, record, expected_version=0)


def load_comment(folder: Path, comment_id: str) -> dict:
    record = read_json(comment_path(folder, comment_id), {})
    if not record:
        raise ValueError("Comment 不存在")
    return record


def list_comments(folder: Path) -> list[dict]:
    records = []
    for path in sorted(comments_root(folder).glob("*.json")) if comments_root(folder).is_dir() else []:
        record = read_json(path, {})
        if record.get("schema") == COMMENT_SCHEMA:
            records.append(record)
    return sorted(records, key=lambda item: item.get("created_at", 0), reverse=True)


def append_comment_decision(
    folder: Path,
    comment_id: str,
    decision: str,
    note: str = "",
    *,
    expected_version: int | None = None,
) -> dict:
    if decision not in ALLOWED_COMMENT_DECISIONS:
        raise ValueError("不支持的 Comment 裁定")
    with comment_object_lock(comment_id):
        record = load_comment(folder, comment_id)
        if record.get("latest_decision") == decision:
            return record
        if expected_version is None:
            raise RuntimeError("缺少对象版本，请刷新后重试")
        if int(record.get("object_version", 0)) != int(expected_version):
            raise RuntimeError("对象版本已变化，请刷新后重试")
        event = {
            "event_id": "decision-" + sha256_payload({
                "comment_id": comment_id,
                "decision": decision,
                "note": note,
                "created_at": now(),
            })[:16],
            "decision": decision,
            "note": str(note)[:2000],
            "created_at": now(),
        }
        record["decision_events"] = [*(record.get("decision_events") or []), event]
        record["latest_decision"] = decision
        record["status"] = "approved_for_repair" if decision == "agree_needs_change" else "decided"
        return write_versioned_object(comment_path(folder, comment_id), record, expected_version=expected_version)


def page_groups_for_comments(comments: list[dict]) -> list[dict]:
    grouped: dict[int, list[dict]] = defaultdict(list)
    for comment in comments:
        grouped[int(comment["pdf_page"])].append(comment)
    return [
        {"pdf_page": page, "comment_ids": [item["comment_id"] for item in items], "comment_count": len(items)}
        for page, items in sorted(grouped.items())
    ]


def enqueue_agent_review(folder: Path, task: dict, comment_ids: list[str], provider: str = "claude") -> dict:
    if provider not in {"claude", "codex"}:
        raise ValueError("不支持的审阅提供方")
    unique_ids = list(dict.fromkeys(comment_ids))
    if not unique_ids:
        raise ValueError("请选择至少一条 Comment")
    task_id = task.get("id")
    with ExitStack() as stack:
        for comment_id in sorted(unique_ids):
            stack.enter_context(comment_object_lock(comment_id))
        comments = [load_comment(folder, item) for item in unique_ids]
        if any(item.get("task_id") != task_id for item in comments):
            raise ValueError("Comment 不属于当前任务")
        unavailable = [
            item.get("comment_id") for item in comments
            if item.get("status") not in {"saved", "review_failed"}
        ]
        if unavailable:
            raise RuntimeError(f"Comment 当前不可重复提交：{', '.join(unavailable)}")
        created_at = now()
        job_id = "agent-job-" + sha256_payload({
            "task_id": task_id,
            "comment_ids": [item["comment_id"] for item in comments],
            "created_at": created_at,
        })[:16]
        page_groups = page_groups_for_comments(comments)
        job = {
            "schema": AGENT_REVIEW_JOB_SCHEMA,
            "job_id": job_id,
            "task_id": task_id,
            "provider": provider,
            "status": "queued",
            "comment_ids": [item["comment_id"] for item in comments],
            "page_groups": page_groups,
            "page_group_count": len(page_groups),
            "comment_count": len(comments),
            "created_at": created_at,
        }
        saved = write_versioned_object(agent_job_path(folder, job_id), job, expected_version=0)
        for comment in comments:
            if comment.get("status") in {"saved", "review_failed"}:
                comment["status"] = "queued"
                comment["queued_job_ids"] = [*(comment.get("queued_job_ids") or []), job_id]
                write_versioned_object(comment_path(folder, comment["comment_id"]), comment)
        return saved


def enqueue_agent_review_selection(
    folder: Path,
    task: dict,
    comment_ids: list[str],
    provider: str = "claude",
) -> dict:
    """Queue the eligible subset and report skipped items without hiding partial success."""
    unique_ids = list(dict.fromkeys(str(item) for item in comment_ids if str(item)))
    if not unique_ids:
        raise ValueError("请选择至少一条 Comment")
    accepted, rejected = [], []
    for comment_id in unique_ids:
        try:
            comment = load_comment(folder, comment_id)
            if comment.get("task_id") != task.get("id"):
                rejected.append({"comment_id": comment_id, "reason": "Comment 不属于当前任务"})
            elif comment.get("status") not in {"saved", "review_failed"}:
                rejected.append({"comment_id": comment_id, "reason": f"当前状态为 {comment.get('status')}，不可重复提交"})
            else:
                accepted.append(comment_id)
        except ValueError as exc:
            rejected.append({"comment_id": comment_id, "reason": str(exc)})
    if not accepted:
        raise RuntimeError("所选 Comment 均不可提交；请刷新整篇审校状态")
    job = enqueue_agent_review(folder, task, accepted, provider)
    return {"job": job, "accepted": accepted, "rejected": rejected}


def list_agent_jobs(folder: Path) -> list[dict]:
    records = []
    for path in sorted(agent_jobs_root(folder).glob("*.json")) if agent_jobs_root(folder).is_dir() else []:
        record = read_json(path, {})
        if record.get("schema") == AGENT_REVIEW_JOB_SCHEMA:
            records.append(record)
    return sorted(records, key=lambda item: item.get("created_at", 0), reverse=True)


def list_agent_reviews(folder: Path) -> list[dict]:
    records = []
    for path in sorted(agent_reviews_root(folder).glob("*.json")) if agent_reviews_root(folder).is_dir() else []:
        record = read_json(path, {})
        if record.get("schema") == AGENT_REVIEW_SCHEMA:
            records.append(record)
    return sorted(records, key=lambda item: item.get("created_at", 0), reverse=True)


def recover_interrupted_agent_jobs(folder: Path, task_id: str) -> list[dict]:
    with RUNNERS_LOCK:
        local_active = task_id in RUNNERS
    if local_active:
        return []
    recovered = []
    for job in list_agent_jobs(folder):
        if job.get("task_id") == task_id and job.get("status") == "active":
            job.update(status="failed", error="工作台中断，AgentReview 调用未完成；请重新提交", failed_at=now())
            recovered.append(write_versioned_object(agent_job_path(folder, job["job_id"]), job))
    return recovered


def active_agent_review_jobs(folder: Path, task_id: str) -> list[dict]:
    recover_interrupted_agent_jobs(folder, task_id)
    return [
        job for job in list_agent_jobs(folder)
        if job.get("task_id") == task_id and job.get("status") == "active"
    ]


def agent_runner_active(task_id: str) -> bool:
    with RUNNERS_LOCK:
        return task_id in RUNNERS


def queued_agent_review_jobs(folder: Path, task_id: str) -> list[dict]:
    return [
        job for job in list_agent_jobs(folder)
        if job.get("task_id") == task_id and job.get("status") == "queued"
    ]


def claim_next_agent_job(folder: Path, task_id: str) -> dict | None:
    if [
        job for job in list_agent_jobs(folder)
        if job.get("task_id") == task_id and job.get("status") == "active"
    ]:
        return None
    queued = [
        job for job in list_agent_jobs(folder)
        if job.get("task_id") == task_id and job.get("status") == "queued"
    ]
    if not queued:
        return None
    job = sorted(queued, key=lambda item: item.get("created_at", 0))[0]
    job.update(status="active", started_at=now())
    return write_versioned_object(agent_job_path(folder, job["job_id"]), job)


def agent_review_prompt(task: dict, pdf_page: int, comments: list[dict]) -> str:
    compact = [
        {
            "comment_id": item.get("comment_id"),
            "comment_version": item.get("object_version"),
            "feedback": item.get("feedback"),
        }
        for item in comments
    ]
    return f"""你是科研 PDF 翻译质量复核员。只读审阅第 {pdf_page} 页的人工 Comment，不修改 PDF，也不要生成候选文件。

文档：{task.get('name')}
Comment：{json.dumps(compact, ensure_ascii=False)}

请分别判断每条 Comment 是否成立、建议关注范围、保护项、风险和是否需要后续人工确认。
返回 reviews 数组；每个输入 comment_id 必须且只能出现一次，不能用一份页面级结论代替逐条判断。只输出结构化 JSON。"""


def split_agent_review_results(page_result: dict, comments: list[dict]) -> dict[str, dict]:
    reviews = page_result.get("reviews") if isinstance(page_result, dict) else None
    if not isinstance(reviews, list):
        raise RuntimeError("AgentReview 缺少逐条 reviews 数组")
    expected = {str(item.get("comment_id")) for item in comments}
    indexed: dict[str, dict] = {}
    for item in reviews:
        if not isinstance(item, dict) or not item.get("comment_id"):
            raise RuntimeError("AgentReview 含有无效的逐条结果")
        comment_id = str(item["comment_id"])
        if comment_id in indexed:
            raise RuntimeError(f"AgentReview 重复返回 Comment：{comment_id}")
        if comment_id not in expected:
            raise RuntimeError(f"AgentReview 返回了未提交的 Comment：{comment_id}")
        indexed[comment_id] = {key: value for key, value in item.items() if key != "comment_id"}
    missing = sorted(expected - set(indexed))
    if missing:
        raise RuntimeError("AgentReview 漏掉 Comment：" + "、".join(missing))
    return indexed


def append_agent_review(folder: Path, job: dict, comment: dict, result: dict) -> dict:
    created_at = now()
    review_id = "agent-review-" + sha256_payload({
        "job_id": job["job_id"],
        "comment_id": comment["comment_id"],
        "comment_version": comment.get("object_version"),
        "created_at": created_at,
    })[:16]
    review = {
        "schema": AGENT_REVIEW_SCHEMA,
        "review_id": review_id,
        "job_id": job["job_id"],
        "task_id": job.get("task_id"),
        "comment_id": comment["comment_id"],
        "comment_version": comment.get("object_version"),
        "provider": job.get("provider"),
        "status": "completed",
        "result": result,
        "created_at": created_at,
    }
    saved_review = write_versioned_object(agent_review_path(folder, review_id), review, expected_version=0)
    with comment_object_lock(comment["comment_id"]):
        fresh_comment = load_comment(folder, comment["comment_id"])
        fresh_comment["agent_review_ids"] = [*(fresh_comment.get("agent_review_ids") or []), review_id]
        fresh_comment["status"] = "reviewed"
        write_versioned_object(comment_path(folder, comment["comment_id"]), fresh_comment)
    return saved_review


def run_agent_review_job(
    folder: Path,
    task: dict,
    job: dict,
    *,
    render_page_images: Callable | None = None,
    run_model: Callable | None = None,
    diagnosis_schema: Path | None = None,
    review_provider: Callable[[dict, int, list[dict]], dict] | None = None,
) -> dict:
    path = agent_job_path(folder, job["job_id"])
    try:
        if job.get("status") != "active":
            raise ValueError("AgentReview job 尚未激活")
        outputs = []
        for group in job.get("page_groups", []):
            pdf_page = int(group["pdf_page"])
            comments = [load_comment(folder, cid) for cid in group.get("comment_ids", [])]
            if review_provider:
                page_result = review_provider(job, pdf_page, comments)
            else:
                if not render_page_images or not run_model or not diagnosis_schema:
                    raise RuntimeError("AgentReview 缺少模型执行器")
                source_image, translated_image = render_page_images(
                    folder, task, pdf_page, job["job_id"], artifact_root=agent_jobs_root(folder),
                )
                output = agent_job_path(folder, job["job_id"]).parent / job["job_id"] / f"page-{pdf_page}-review.json"
                page_result = run_model(
                    job.get("provider", "claude"),
                    agent_review_prompt(task, pdf_page, comments),
                    source_image,
                    translated_image,
                    output,
                    diagnosis_schema,
                )
            per_comment = split_agent_review_results(page_result, comments)
            for comment in comments:
                outputs.append(append_agent_review(folder, job, comment, {
                    "page_review": per_comment[comment["comment_id"]],
                    "comment_feedback": comment.get("feedback"),
                }))
        job.update(status="completed", completed_at=now(), agent_review_ids=[item["review_id"] for item in outputs])
    except Exception as exc:
        job.update(status="failed", error=str(exc)[:1000], failed_at=now())
        for cid in job.get("comment_ids", []):
            try:
                comment = load_comment(folder, cid)
                if comment.get("status") in {"queued", "reviewing"}:
                    comment["status"] = "review_failed"
                    comment["last_error"] = str(exc)[:1000]
                    write_comment_object(folder, cid, comment)
            except Exception:
                pass
    return write_versioned_object(path, job)


def start_agent_review_runner(folder: Path, task: dict, **runner_kwargs) -> bool:
    task_id = task.get("id")
    recover_interrupted_agent_jobs(folder, task_id)
    with RUNNERS_LOCK:
        if task_id in RUNNERS:
            return False
        RUNNERS.add(task_id)

    def loop() -> None:
        try:
            while True:
                job = claim_next_agent_job(folder, task_id)
                if not job:
                    return
                run_agent_review_job(folder, task, job, **runner_kwargs)
        finally:
            with RUNNERS_LOCK:
                RUNNERS.discard(task_id)

    threading.Thread(target=loop, daemon=True).start()
    return True


def review_cycle_projection(folder: Path, task: dict) -> dict:
    recover_interrupted_agent_jobs(folder, task.get("id"))
    comments = list_comments(folder)
    jobs = list_agent_jobs(folder)
    reviews = list_agent_reviews(folder)
    pending = [item for item in comments if item.get("status") in {"saved", "review_failed"}]
    awaiting_decision = [
        item for item in comments
        if item.get("status") == "reviewed" and not item.get("latest_decision")
    ]
    approved = [item for item in comments if item.get("latest_decision") == "agree_needs_change"]
    active_jobs = [item for item in jobs if item.get("status") == "active"]
    queued_jobs = [item for item in jobs if item.get("status") == "queued"]
    failed_jobs = [item for item in jobs if item.get("status") == "failed"]
    return {
        "schema": "review-cycle-projection/v1",
        "task_id": task.get("id"),
        "comments": comments,
        "agent_reviews": reviews,
        "agent_review_jobs": jobs,
        "pending_comment_count": len(pending),
        "pending_comment_page_count": len({int(item.get("pdf_page", 0)) for item in pending}),
        "awaiting_decision_count": len(awaiting_decision),
        "approved_comment_count": len(approved),
        "active_job_count": len(active_jobs),
        "queued_job_count": len(queued_jobs),
        "failed_job_count": len(failed_jobs),
        "active_review_count": sum(int(item.get("comment_count", 0)) for item in active_jobs),
        "queued_review_count": sum(int(item.get("comment_count", 0)) for item in queued_jobs),
        "failed_review_count": len([item for item in comments if item.get("status") == "review_failed"]),
    }


def object_counts(folder: Path) -> dict:
    return {
        "comments": len(list_comments(folder)),
        "agent_reviews": len(list_agent_reviews(folder)),
        "agent_review_jobs": len(list_agent_jobs(folder)),
        "repair_batches": len(list((review_cycle_root(folder) / "repair-batches").glob("*/batch.json"))) if (review_cycle_root(folder) / "repair-batches").is_dir() else 0,
        "human_reviews": len(list((folder / "human-reviews").glob("*/review.json"))) if (folder / "human-reviews").is_dir() else 0,
        "repairs": len(list((folder / "repairs").glob("*/repair.json"))) if (folder / "repairs").is_dir() else 0,
        "page_manifests": len(list(manifest_root(folder).glob("*.json"))) if manifest_root(folder).is_dir() else 0,
    }


def trash_task(data_dir: Path, task_id: str) -> dict:
    folder = data_dir / task_id
    if not folder.exists():
        return {"ok": True, "already_missing": True}
    trash = data_dir / ".trash"
    trash.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": TRASH_RECEIPT_SCHEMA,
        "task_id": task_id,
        "trashed_at": now(),
        "source": str(folder),
        "object_counts": object_counts(folder),
    }
    trash_id = f"{task_id}-{int(receipt['trashed_at'])}"
    target = trash / trash_id
    suffix = 1
    while target.exists():
        suffix += 1
        target = trash / f"{trash_id}-{suffix}"
    receipt["trash_id"] = target.name
    receipt["trash_path"] = str(target)
    shutil.move(str(folder), str(target))
    atomic_write_json(target / "trash-receipt.json", receipt)
    return {"ok": True, "trashed": True, "trash_id": target.name, "summary": receipt}


def permanently_delete_task(data_dir: Path, task_id: str, confirm_delete: str | None) -> dict:
    if confirm_delete != task_id:
        raise ValueError("永久删除需要 confirm_delete 等于任务 ID")
    folder = data_dir / task_id
    if folder.exists():
        shutil.rmtree(folder)
        return {"ok": True, "permanent": True, "task_id": task_id}
    trash = data_dir / ".trash"
    removed = []
    for item in trash.glob(f"{task_id}-*") if trash.is_dir() else []:
        shutil.rmtree(item)
        removed.append(item.name)
    return {"ok": True, "permanent": True, "task_id": task_id, "removed_trash": removed}


def restore_trashed_task(data_dir: Path, trash_id: str) -> dict:
    source = data_dir / ".trash" / Path(trash_id).name
    receipt = read_json(source / "trash-receipt.json", {})
    task_id = receipt.get("task_id") or str(trash_id).split("-", 1)[0]
    target = data_dir / task_id
    if not source.is_dir():
        raise ValueError("废纸篓任务不存在")
    if target.exists():
        raise RuntimeError("同名任务已存在，不能自动恢复")
    shutil.move(str(source), str(target))
    return {"ok": True, "restored": True, "task_id": task_id}
