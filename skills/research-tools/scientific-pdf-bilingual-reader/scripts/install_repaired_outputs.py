#!/usr/bin/env python3
"""Validate, back up, and atomically install staged repaired PDF outputs."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import fitz


FILE_MAP = {
    "translated-zh.repaired.pdf": "translated-zh.pdf",
    "bilingual-side-by-side.repaired.pdf": "bilingual-side-by-side.pdf",
    "page-plan.repaired.json": "page-plan.json",
    "qa-repaired.json": "qa-alpha.json",
}


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(payload: dict, target: Path) -> None:
    with tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=f".{target.name}.", mode="w", encoding="utf-8", delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, target)


def validate_pdf_set(task: Path, stage: Path) -> int:
    original = fitz.open(task / "original.pdf")
    translated = fitz.open(stage / "translated-zh.repaired.pdf")
    bilingual = fitz.open(stage / "bilingual-side-by-side.repaired.pdf")
    counts = {len(original), len(translated), len(bilingual)}
    if len(counts) != 1:
        raise RuntimeError(
            f"页数不一致：original={len(original)}, translated={len(translated)}, bilingual={len(bilingual)}"
        )
    return len(original)


def install(task_root: Path, staging_root: Path, backup_root: Path, task_id: str) -> dict:
    task = task_root / task_id
    stage = staging_root / task_id
    if not task.is_dir() or not stage.is_dir():
        raise FileNotFoundError(f"缺少任务或修复目录：{task_id}")
    missing = [name for name in (*FILE_MAP, "full-repair-result.json") if not (stage / name).is_file()]
    if missing:
        raise FileNotFoundError(f"{task_id} 缺少修复文件：{', '.join(missing)}")
    page_count = validate_pdf_set(task, stage)
    result = json.loads((stage / "full-repair-result.json").read_text())
    qa = json.loads((stage / "qa-repaired.json").read_text())
    metrics = result.get("translation_metrics", {})
    if metrics.get("unresolved") or metrics.get("errors"):
        raise RuntimeError(f"{task_id} 尚有未解析翻译或调用错误")

    backup = backup_root / task_id
    backup.mkdir(parents=True, exist_ok=True)
    for name in (*FILE_MAP.values(), "task.json"):
        source = task / name
        if source.is_file():
            shutil.copy2(source, backup / name)

    for staged_name, installed_name in FILE_MAP.items():
        atomic_copy(stage / staged_name, task / installed_name)

    task_path = task / "task.json"
    payload = json.loads(task_path.read_text())
    status_map = {
        "passed": "completed",
        "passed_with_warnings": "completed_with_warnings",
        "needs_review": "needs_review",
    }
    qa_status = qa.get("status", "needs_review")
    flagged = qa.get("flagged_pages", [])
    installed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    payload.update(
        status=status_map.get(qa_status, "needs_review"),
        translated_file="translated-zh.pdf",
        dual_file="bilingual-side-by-side.pdf",
        page_plan_file="page-plan.json",
        qa_alpha_file="qa-alpha.json",
        qa_alpha={
            "status": qa_status,
            "summary": qa.get("summary", {}),
            "flagged_pages": flagged,
            "baseline": qa.get("baseline"),
        },
        repair_v2={
            "installed_at": installed_at,
            "known_problem_pages": [int(item["original_pdf_page"]) for item in result.get("repairs", [])],
            "translation_metrics": metrics,
            "result_file": str(stage / "full-repair-result.json"),
            "backup_dir": str(backup),
        },
        message=(
            f"已安装问题页修复版；全篇确定性 QA 仍标记 {len(flagged)} 页，需继续复核"
            if qa_status == "needs_review" else
            f"已安装问题页修复版；全篇确定性 QA 保留 {len(flagged)} 个警告页"
            if qa_status == "passed_with_warnings" else
            "已安装问题页修复版；确定性 QA 通过"
        ),
    )
    atomic_json(payload, task_path)
    return {
        "task_id": task_id,
        "page_count": page_count,
        "status": payload["status"],
        "known_problem_pages": payload["repair_v2"]["known_problem_pages"],
        "flagged_pages": len(flagged),
        "backup": str(backup),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("task_ids", nargs="+")
    args = parser.parse_args()
    installed = [
        install(args.task_root, args.staging_root, args.backup_root, task_id)
        for task_id in args.task_ids
    ]
    print(json.dumps({"installed": installed}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
