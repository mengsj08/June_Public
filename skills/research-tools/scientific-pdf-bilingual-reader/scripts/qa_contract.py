#!/usr/bin/env python3
"""Hash-bound QA contracts and severity accounting for local regression runs."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import time
from collections import Counter
from pathlib import Path
from typing import Any


QA_CONTRACT_SCHEMA = "qa-contract/v1"
QA_RULE_VERSION = "qa-alpha-red-orange-warning/v2"
REGRESSION_RECEIPT_SCHEMA = "pdf-reader-regression-receipt/v1"

PROTECTED_POLICIES = {"protect_table_translate_caption", "preserve_original"}
RED_ISSUES = {
    "page_count_changed",
    "rotation_metadata_mismatch",
    "text_direction_mismatch",
    "unexpected_repetition",
    "page_translation_coverage_low",
    "rendered_page_too_sparse",
    "rendered_regions_crowded",
    "rendered_structure_drift",
    "rendered_text_too_small",
    "model_meta_response_leak",
}
ORANGE_ISSUES = {
    "strategy_preserved_source_region",
    "structured_region_fallback",
}
WARNING_ISSUES = {
    "english_region_untranslated",
    "prominent_english_untranslated",
    "rendered_regions_missing",
    "toc_layout_suspect",
    "unexpected_control_characters",
}


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path | None) -> dict[str, Any] | None:
    if not path or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return {"sha256": digest.hexdigest(), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def sha256_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def dependency_versions() -> dict[str, Any]:
    packages = {}
    for package in ("PyMuPDF", "opencv-python", "numpy"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    return {"python": platform.python_version(), "packages": packages}


def task_projection(task: dict | None) -> dict:
    if not task:
        return {}
    keys = (
        "id", "name", "original_file", "translation_source_file",
        "translated_file", "dual_file", "page_plan_file", "qa_alpha_file",
        "provider", "page_type_counts", "page_route_counts", "ocr_summary",
        "forced_ocr_pages", "forced_ocr_images",
    )
    return {key: task.get(key) for key in keys if key in task}


def build_contract(
    *,
    original_path: Path | None,
    output_path: Path | None,
    plan_path: Path | None = None,
    task: dict | None = None,
    evaluated_at: float | None = None,
) -> dict[str, Any]:
    projection = task_projection(task)
    plan_hash = sha256_file(plan_path)
    contract = {
        "schema": QA_CONTRACT_SCHEMA,
        "qa_rule_version": QA_RULE_VERSION,
        "evaluated_at": evaluated_at or time.time(),
        "inputs": {"original_pdf": sha256_file(original_path)},
        "outputs": {"translated_pdf": sha256_file(output_path)},
        "plan": {"page_plan": plan_hash},
        "task_projection": {
            "payload": projection,
            "sha256": sha256_payload(projection) if projection else None,
        },
        "dependencies": dependency_versions(),
    }
    contract["contract_sha256"] = sha256_payload({
        key: value for key, value in contract.items() if key != "contract_sha256"
    })
    return contract


def compare_file_hash(label: str, expected: dict | None, actual: dict | None) -> list[str]:
    if not expected:
        return [f"{label}:missing_expected_hash"]
    if not actual:
        return [f"{label}:missing_current_file"]
    mismatches = []
    for key in ("sha256", "size_bytes"):
        if expected.get(key) != actual.get(key):
            mismatches.append(f"{label}:{key}_mismatch")
    return mismatches


def verify_contract(
    report: dict,
    *,
    original_path: Path | None,
    output_path: Path | None,
    plan_path: Path | None = None,
    task: dict | None = None,
) -> dict[str, Any]:
    contract = report.get("contract")
    if not contract:
        return {
            "status": "stale",
            "reason": "missing_contract",
            "message": "旧 QA 报告缺少哈希合同，不可沿用旧红色数量",
        }
    mismatches = []
    mismatches += compare_file_hash("original_pdf", contract.get("inputs", {}).get("original_pdf"), sha256_file(original_path))
    mismatches += compare_file_hash("translated_pdf", contract.get("outputs", {}).get("translated_pdf"), sha256_file(output_path))
    mismatches += compare_file_hash("page_plan", contract.get("plan", {}).get("page_plan"), sha256_file(plan_path))
    expected_rule = contract.get("qa_rule_version")
    if expected_rule != QA_RULE_VERSION:
        mismatches.append("qa_rule_version_mismatch")
    if task is not None:
        expected_task_hash = contract.get("task_projection", {}).get("sha256")
        current_projection = task_projection(task)
        current_hash = sha256_payload(current_projection) if current_projection else None
        if expected_task_hash and expected_task_hash != current_hash:
            mismatches.append("task_projection:sha256_mismatch")
    if mismatches:
        return {
            "status": "stale",
            "reason": "contract_mismatch",
            "mismatches": mismatches,
            "message": "当前文件或规则与 QA 合同不匹配，不可沿用旧红色数量",
        }
    return {"status": "fresh", "reason": "contract_match", "message": "QA 合同与当前文件匹配"}


def classify_issue(issue: dict, plan: dict | None = None) -> dict:
    kind = issue.get("issue_type", "")
    policy = (plan or {}).get("policy")
    category = "qa_suspect"
    severity = "warning"
    user_impact = "tip"
    if kind == "page_translation_coverage_low" and issue.get("designed_fallback"):
        category, severity, user_impact = "qa_suspect", "warning", "tip"
    elif kind == "page_translation_coverage_low" and policy in PROTECTED_POLICIES:
        category, severity, user_impact = "protected_by_policy", "orange", "needs_review"
    elif kind in RED_ISSUES:
        category, severity, user_impact = "translation_failed", "red", "hard_blocker"
    elif kind in ORANGE_ISSUES:
        category = "protected_by_policy" if kind == "strategy_preserved_source_region" else "translation_failed"
        severity, user_impact = "orange", "needs_review"
    elif kind in WARNING_ISSUES:
        category, severity, user_impact = "qa_suspect", "warning", "tip"
    elif "ocr" in kind:
        category, severity, user_impact = "ocr_low_confidence", "orange", "needs_review"
    result = dict(issue)
    result["legacy_severity"] = issue.get("severity")
    result["severity"] = severity
    result["issue_category"] = category
    result["user_impact"] = user_impact
    return result


def page_status(issues: list[dict]) -> str:
    severities = {issue.get("severity") for issue in issues}
    if "red" in severities:
        return "red"
    if "orange" in severities:
        return "orange"
    if "warning" in severities:
        return "warning"
    return "pass"


def severity_summary(pages: list[dict], document_issues: list[dict] | None = None) -> dict[str, int]:
    counts = Counter(page.get("status", "pass") for page in pages)
    for issue in document_issues or []:
        counts[issue.get("severity", "red")] += 1
    return {key: counts.get(key, 0) for key in ("red", "orange", "warning", "pass")}


def category_summary(pages: list[dict], document_issues: list[dict] | None = None) -> dict[str, int]:
    counts = Counter()
    for issue in document_issues or []:
        counts[issue.get("issue_category", "qa_suspect")] += 1
    for page in pages:
        for issue in page.get("issues", []):
            counts[issue.get("issue_category", "qa_suspect")] += 1
    return {key: counts.get(key, 0) for key in (
        "protected_by_policy", "translation_failed", "qa_suspect", "ocr_low_confidence",
    )}


def gate_status(summary: dict[str, int]) -> str:
    if summary.get("red", 0) or summary.get("orange", 0):
        return "needs_review"
    if summary.get("warning", 0):
        return "passed_with_warnings"
    return "passed"


def score_key(page: dict, default_task_id: str | None = None) -> str:
    task_id = page.get("task_id") or (page.get("task_pointer") or {}).get("task_id") or default_task_id
    if task_id:
        return f"{task_id}:{int(page['pdf_page'])}"
    if page.get("fixture_page_id"):
        return str(page["fixture_page_id"])
    return f"page:{int(page['pdf_page'])}"


def score_label(page: dict) -> str:
    if page.get("fixture_page_id"):
        return str(page["fixture_page_id"])
    task_id = page.get("task_id") or (page.get("task_pointer") or {}).get("task_id")
    if task_id:
        return f"{task_id}:{int(page['pdf_page'])}"
    return f"page:{int(page['pdf_page'])}"


def score_precision_recall(report: dict, fixture_pages: list[dict]) -> dict[str, Any]:
    confirmed = [
        page for page in fixture_pages
        if page.get("labels", {}).get("status") == "june-confirmed"
    ]
    default_task_id = report.get("task_id")
    page_by_key = {score_key(page, default_task_id): page for page in report.get("pages", [])}
    fixture_by_key = {score_key(page): page for page in confirmed}
    denominator = {
        "confirmed_pages": len(confirmed),
        "draft_pages": len(fixture_pages) - len(confirmed),
    }
    if not confirmed:
        return {
            "status": "blocked",
            "message": "不可签发 PASS：没有 june-confirmed 页，draft 标签不能进入质量门分母",
            **denominator,
            "hard_blocker_recall": None,
            "red_precision": None,
        }
    expected_red = {
        score_key(page) for page in confirmed
        if page.get("expected_result", {}).get("expected_severity") == "red"
    }
    actual_red = {key for key, page in page_by_key.items() if page.get("status") == "red"}
    confirmed_pages = set(fixture_by_key)
    actual_red_confirmed = actual_red & confirmed_pages
    true_red = actual_red_confirmed & expected_red
    false_red = actual_red_confirmed - expected_red
    missed_red = expected_red - actual_red_confirmed
    recall = len(true_red) / len(expected_red) if expected_red else 1.0
    precision = len(true_red) / len(actual_red_confirmed) if actual_red_confirmed else 1.0
    passed = recall == 1.0 and precision >= 0.9
    def labels(keys: set[str]) -> list[str]:
        return sorted(score_label(fixture_by_key.get(key) or page_by_key.get(key, {"fixture_page_id": key})) for key in keys)
    return {
        "status": "pass" if passed else "fail",
        "message": "质量门达标" if passed else "质量门未达标",
        **denominator,
        "known_hard_blocker_pages": labels(expected_red),
        "actual_red_pages": labels(actual_red_confirmed),
        "true_red_pages": labels(true_red),
        "false_red_pages": labels(false_red),
        "missed_red_pages": labels(missed_red),
        "hard_blocker_recall": round(recall, 4),
        "red_precision": round(precision, 4),
    }
