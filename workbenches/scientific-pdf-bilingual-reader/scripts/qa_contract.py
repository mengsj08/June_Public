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
QA_RULE_VERSION = "qa-alpha-red-orange-warning/v3"
REGRESSION_RECEIPT_SCHEMA = "pdf-reader-regression-receipt/v1"

PROTECTED_POLICIES = {"protect_table_translate_caption", "preserve_original"}
DETERMINISTIC_VISUAL_GATE_ISSUES = {
    "rendered_text_overlap",
    "rendered_text_clipped",
    "rendered_vertical_cjk_stack",
    "rendered_text_too_small",
    "structured_region_fallback",
}
RED_ISSUES = {
    "page_count_changed",
    "rotation_metadata_mismatch",
    "text_direction_mismatch",
    "unexpected_repetition",
    "page_translation_coverage_low",
    "rendered_page_too_sparse",
    "rendered_regions_crowded",
    "rendered_structure_drift",
    "model_meta_response_leak",
}
ORANGE_ISSUES = {
    "strategy_preserved_source_region",
    "structured_region_fallback",
    "rendered_text_overlap",
    "rendered_text_clipped",
    "rendered_vertical_cjk_stack",
    "rendered_text_too_small",
}
WARNING_ISSUES = {
    "english_region_untranslated",
    "prominent_english_untranslated",
    "rendered_regions_missing",
    "toc_layout_suspect",
    "unexpected_control_characters",
}
ACTIONABLE_USER_IMPACTS = {"hard_blocker", "needs_review"}


def issue_user_impact(issue: dict) -> str:
    """Return the UI attention tier, including compatibility for older reports."""
    explicit = issue.get("user_impact")
    if explicit in {"hard_blocker", "needs_review", "tip"}:
        return explicit
    severity = issue.get("severity")
    if severity in {"red", "critical"}:
        return "hard_blocker"
    if severity == "orange":
        return "needs_review"
    return "tip"


def issue_review_id(pdf_page: int, issue: dict) -> str:
    """Build the stable review key used by both the API summary and review panel."""
    evidence = str(issue.get("evidence", ""))
    region = json.dumps(issue.get("region", []), separators=(",", ":"))
    digest = hashlib.sha1(
        f"{pdf_page}|{issue.get('issue_type')}|{evidence}|{region}".encode()
    ).hexdigest()[:10]
    return f"p{pdf_page}-{issue.get('issue_type', 'issue')}-{digest}"


def attention_summary(
    pages: list[dict],
    document_issues: list[dict] | None = None,
    decisions: dict | None = None,
) -> dict[str, Any]:
    """Summarize human actions separately from optional technical diagnostics."""
    decisions = decisions or {}
    actionable_pages: set[int] = set()
    hard_blocker_pages: set[int] = set()
    needs_review_pages: set[int] = set()
    technical_tip_pages: set[int] = set()
    actionable_issue_count = 0
    hard_blocker_issue_count = 0
    needs_review_issue_count = 0
    technical_tip_issue_count = 0
    ignored_actionable_issue_count = 0

    for page in pages:
        pdf_page = int(page.get("pdf_page", 0))
        seen: set[str] = set()
        for issue in page.get("issues", []):
            issue_id = issue.get("issue_id") or issue_review_id(pdf_page, issue)
            if issue_id in seen:
                continue
            seen.add(issue_id)
            impact = issue_user_impact(issue)
            if impact == "tip":
                technical_tip_pages.add(pdf_page)
                technical_tip_issue_count += 1
                continue
            decision = (
                decisions.get(issue_id, {}).get("decision")
                or issue.get("review", {}).get("decision")
                or "pending"
            )
            if decision == "ignored":
                ignored_actionable_issue_count += 1
                continue
            actionable_pages.add(pdf_page)
            actionable_issue_count += 1
            if impact == "hard_blocker":
                hard_blocker_pages.add(pdf_page)
                hard_blocker_issue_count += 1
            else:
                needs_review_pages.add(pdf_page)
                needs_review_issue_count += 1

    document_actionable_issue_count = 0
    document_technical_tip_count = 0
    for issue in document_issues or []:
        if issue_user_impact(issue) in ACTIONABLE_USER_IMPACTS:
            document_actionable_issue_count += 1
            actionable_issue_count += 1
        else:
            document_technical_tip_count += 1
            technical_tip_issue_count += 1

    return {
        "actionable_pages": sorted(actionable_pages),
        "actionable_page_count": len(actionable_pages),
        "actionable_issue_count": actionable_issue_count,
        "hard_blocker_pages": sorted(hard_blocker_pages),
        "hard_blocker_page_count": len(hard_blocker_pages),
        "hard_blocker_issue_count": hard_blocker_issue_count,
        "needs_review_pages": sorted(needs_review_pages),
        "needs_review_page_count": len(needs_review_pages),
        "needs_review_issue_count": needs_review_issue_count,
        "technical_tip_pages": sorted(technical_tip_pages),
        "technical_tip_page_count": len(technical_tip_pages),
        "technical_tip_issue_count": technical_tip_issue_count,
        "ignored_actionable_issue_count": ignored_actionable_issue_count,
        "document_actionable_issue_count": document_actionable_issue_count,
        "document_technical_tip_count": document_technical_tip_count,
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


def deterministic_visual_issue_signature(pdf_page: int, issue: dict) -> str | None:
    kind = issue.get("issue_type")
    if kind not in DETERMINISTIC_VISUAL_GATE_ISSUES:
        return None
    region = issue.get("region") or []
    quantized_region = []
    if len(region) >= 4:
        quantized_region = [round(float(value) / 8) * 8 for value in region[:4]]
    return json.dumps(
        {"page": int(pdf_page), "type": kind, "region": quantized_region},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def deterministic_visual_issue_signatures(report: dict, pdf_page: int | None = None) -> set[str]:
    signatures = set()
    for page in report.get("pages", []):
        page_number = int(page.get("pdf_page", 0))
        if pdf_page is not None and page_number != int(pdf_page):
            continue
        for issue in page.get("issues", []):
            signature = deterministic_visual_issue_signature(page_number, issue)
            if signature:
                signatures.add(signature)
    return signatures


def new_deterministic_visual_violations(before: dict, after: dict, pdf_page: int | None = None) -> list[dict]:
    before_signatures = deterministic_visual_issue_signatures(before, pdf_page)
    before_counts = Counter()
    after_counts = Counter()
    after_issues: list[tuple[int, dict, str]] = []
    for report, counts in ((before, before_counts), (after, after_counts)):
        for page in report.get("pages", []):
            page_number = int(page.get("pdf_page", 0))
            if pdf_page is not None and page_number != int(pdf_page):
                continue
            for issue in page.get("issues", []):
                if issue.get("issue_type") in DETERMINISTIC_VISUAL_GATE_ISSUES:
                    counts[(page_number, issue.get("issue_type"))] += 1
                    if report is after:
                        signature = deterministic_visual_issue_signature(page_number, issue)
                        if signature:
                            after_issues.append((page_number, issue, signature))
    violations = []
    seen = set()
    surplus_by_type = {
        key: after_counts[key] - before_counts.get(key, 0)
        for key in after_counts
        if after_counts[key] > before_counts.get(key, 0)
    }
    def append_violation(page_number: int, issue: dict, signature: str) -> None:
        seen.add(signature)
        violations.append({
            "pdf_page": page_number,
            "issue_type": issue.get("issue_type"),
            "evidence": issue.get("evidence"),
            "region": issue.get("region"),
            "signature": signature,
        })

    for page_number, issue, signature in after_issues:
        if signature in before_signatures or signature in seen:
            continue
        count_key = (page_number, issue.get("issue_type"))
        if surplus_by_type.get(count_key, 0) > 0:
            surplus_by_type[count_key] -= 1
        append_violation(page_number, issue, signature)

    for page_number, issue, signature in after_issues:
        if signature in seen or signature not in before_signatures:
            continue
        count_key = (page_number, issue.get("issue_type"))
        if surplus_by_type.get(count_key, 0) <= 0:
            continue
        surplus_by_type[count_key] -= 1
        append_violation(page_number, issue, signature)
    return violations


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
