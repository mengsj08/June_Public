#!/usr/bin/env python3
"""Local-only regression receipts for the private PDF fixture tiers."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from pathlib import Path

from qa_alpha import audit
from qa_contract import (
    QA_RULE_VERSION, REGRESSION_RECEIPT_SCHEMA, dependency_versions, score_precision_recall,
    sha256_file,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path(
    os.environ.get(
        "PDF_READER_PRIVATE_REGRESSION_DIR",
        ROOT / "references" / "regression",
    )
).expanduser() / "fixture-manifest.json"
DEFAULT_DATA = Path("~/.local/share/scientific-pdf-bilingual-reader").expanduser()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def code_hashes() -> dict:
    return {
        relative: sha256_file(ROOT / relative)
        for relative in ("scripts/qa_alpha.py", "scripts/qa_contract.py", "scripts/regression_runner.py")
    }


def task_root(manifest: dict) -> Path:
    return Path(manifest.get("task_root") or (DEFAULT_DATA / "tasks")).expanduser()


def receipt_path(tier: str, output: Path | None) -> Path:
    if output:
        return output
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return DEFAULT_DATA / "regression" / "receipts" / f"{tier}-{stamp}.json"


def pages_for_task(manifest: dict) -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    for page in manifest.get("pages", []):
        pointer = page.get("task_pointer")
        if pointer and pointer.get("task_id"):
            grouped[pointer["task_id"]].append(page)
    return dict(grouped)


def sanitized_report(report: dict) -> dict:
    pages = []
    for page in report.get("pages", []):
        pages.append({
            "pdf_page": page.get("pdf_page"),
            "status": page.get("status"),
            "metrics": page.get("metrics", {}),
            "issues": [
                {
                    "issue_type": issue.get("issue_type"),
                    "severity": issue.get("severity"),
                    "issue_category": issue.get("issue_category"),
                    "user_impact": issue.get("user_impact"),
                    "legacy_severity": issue.get("legacy_severity"),
                }
                for issue in page.get("issues", [])
            ],
        })
    return {
        "version": report.get("version"),
        "gate": report.get("gate"),
        "status": report.get("status"),
        "page_count": report.get("page_count"),
        "summary": report.get("summary", {}),
        "issue_category_summary": report.get("issue_category_summary", {}),
        "flagged_pages": report.get("flagged_pages", []),
        "baseline": report.get("baseline"),
        "quality_gate": report.get("quality_gate"),
        "contract": report.get("contract"),
        "pages": pages,
    }


def runnable_paths(root: Path, page: dict) -> tuple[Path, Path, Path]:
    pointer = page["task_pointer"]
    folder = root / pointer["task_id"]
    return (
        folder / pointer.get("original_file", "original.pdf"),
        folder / pointer.get("output_file", "translated-zh.pdf"),
        folder / pointer.get("plan_file", "page-plan.json"),
    )


def run_short_sprint(manifest_path: Path, output: Path | None) -> dict:
    manifest = read_json(manifest_path)
    root = task_root(manifest)
    grouped = pages_for_task(manifest)
    task_reports = []
    covered_pages = [page["fixture_page_id"] for page in manifest.get("pages", [])]
    evaluated_pages = []
    skipped_pages = []
    merged_pages = []
    target = receipt_path("short-sprint", output)
    reports_dir = target.parent.parent / "task-reports" / target.stem
    for task_id, pages in sorted(grouped.items()):
        original, translated, plan = runnable_paths(root, pages[0])
        missing = [str(path) for path in (original, translated, plan) if not path.is_file()]
        if missing:
            skipped_pages.extend({"fixture_page_id": page["fixture_page_id"], "reason": "missing_task_artifact", "missing": missing} for page in pages)
            continue
        report = audit(
            original, translated, plan,
            task_id=task_id, fixture_manifest_path=manifest_path,
        )
        report_file = reports_dir / f"{task_id}-qa.json"
        write_json(report_file, sanitized_report(report))
        fixture_by_page = {int(page["pdf_page"]): page for page in pages}
        selected = []
        for raw_page in report.get("pages", []):
            fixture = fixture_by_page.get(int(raw_page.get("pdf_page", 0)))
            if not fixture:
                continue
            selected_page = dict(raw_page)
            selected_page["task_id"] = task_id
            selected_page["fixture_page_id"] = fixture["fixture_page_id"]
            selected.append(selected_page)
        merged_pages.extend(selected)
        evaluated_pages.extend(page["fixture_page_id"] for page in pages)
        task_reports.append({
            "task_id": task_id,
            "status": report.get("status"),
            "summary": report.get("summary", {}),
            "issue_category_summary": report.get("issue_category_summary", {}),
            "fixture_pages": [page["fixture_page_id"] for page in pages],
            "report": str(report_file),
        })
    source_only = [page for page in manifest.get("pages", []) if not page.get("task_pointer")]
    skipped_pages.extend({"fixture_page_id": page["fixture_page_id"], "reason": "source_only_no_historical_output"} for page in source_only)
    gate = score_precision_recall({"pages": merged_pages}, manifest.get("pages", []))
    receipt = {
        "schema": REGRESSION_RECEIPT_SCHEMA,
        "tier": "short_sprint",
        "status": "blocked" if gate.get("status") == "blocked" else gate.get("status"),
        "generated_at": time.time(),
        "manifest": {"path": str(manifest_path), "hash": sha256_file(manifest_path)},
        "qa_rule_version": QA_RULE_VERSION,
        "dependencies": dependency_versions(),
        "code_hashes": code_hashes(),
        "model_calls": {"translation": False, "diagnosis": False, "repair": False},
        "covered_pages": covered_pages,
        "covered_page_count": len(covered_pages),
        "evaluated_pages": evaluated_pages,
        "evaluated_page_count": len(evaluated_pages),
        "skipped_pages": skipped_pages,
        "task_reports": task_reports,
        "quality_gate": gate,
        "higher_tiers": {
            "release_long_run_98_pages": {"status": "not_run", "reason": "SKL-167 phase 1 dispatch forbids real model calls"},
            "full_healthcheck_715_pages": {"status": "not_run", "reason": "SKL-167 phase 1 dispatch scope"},
        },
    }
    write_json(target, receipt)
    receipt["receipt"] = str(target)
    return receipt


def not_run_receipt(tier: str, manifest_path: Path, output: Path | None) -> dict:
    manifest = read_json(manifest_path)
    receipt = {
        "schema": REGRESSION_RECEIPT_SCHEMA,
        "tier": tier,
        "status": "not_run",
        "generated_at": time.time(),
        "manifest": {"path": str(manifest_path), "hash": sha256_file(manifest_path)},
        "qa_rule_version": QA_RULE_VERSION,
        "dependencies": dependency_versions(),
        "code_hashes": code_hashes(),
        "model_calls": {
            "translation": tier == "release_long_run",
            "diagnosis": False,
            "repair": False,
            "actual_calls_made": False,
        },
        "coverage_plan": manifest.get("tiers", {}).get("release_long_run" if tier == "release_long_run" else "full_healthcheck", {}),
        "reason": "SKL-167 phase 1 records the receipt contract but does not execute this tier",
    }
    target = receipt_path(tier, output)
    write_json(target, receipt)
    receipt["receipt"] = str(target)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tier", choices=("short-sprint", "release-long-run", "full-healthcheck"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.tier == "short-sprint":
        receipt = run_short_sprint(args.manifest, args.receipt)
    else:
        receipt = not_run_receipt(args.tier.replace("-", "_"), args.manifest, args.receipt)
    print(json.dumps({
        "tier": receipt["tier"], "status": receipt["status"], "receipt": receipt["receipt"],
        "quality_gate": receipt.get("quality_gate"), "model_calls": receipt.get("model_calls"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
