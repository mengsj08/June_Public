#!/usr/bin/env python3
"""Targeted Gate 1c repair harness for known-bad PDF pages.

This experimental harness never rewrites a full customer task. It extracts a
small page set, applies family-specific repairs, and emits before/after PDFs and
QA reports for visual and deterministic comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_router import (  # noqa: E402
    FONT_CANDIDATES,
    extract_navigation,
    render_navigation,
)
from qa_alpha import audit, allowed_english, english_letters, line_records, normalized_text  # noqa: E402
from translation_broker import TranslationBroker  # noqa: E402


TOC_INSTRUCTION = "把下面目录标题逐条翻译成简洁准确的中文。保留缩略语、编号、年份、拉丁学名和专有名词；不要添加解释。"
CELL_INSTRUCTION = "逐格翻译表格或表单中的英文为简洁准确的中文。保留编号、金额、单位、缩略语、专有名词和拉丁学名；不要添加解释。"
ROTATION_INSTRUCTION = "逐条翻译旋转表格页面的标题、说明或表单字段为简洁准确的中文。保留编号、金额、单位、缩略语和专有名词；不要添加解释。"
FORM_INSTRUCTION = "逐条翻译页面标题、说明或表单字段为简洁准确的中文。保留编号、金额、单位、缩略语、专有名词和拉丁学名；不要添加解释。"
HEADING_INSTRUCTION = "逐条翻译仍为英文的页面标题、页眉页脚或重要标签。保留编号、缩略语、专有名词和拉丁学名；不要添加解释。"


def safe_task_file(task_root: Path, value: str | None, default: str) -> Path:
    root = task_root.resolve()
    relative = Path(value or default)
    if relative.is_absolute():
        raise RuntimeError("任务文件引用必须位于任务目录内")
    target = (root / relative).resolve()
    if root not in target.parents:
        raise RuntimeError("任务文件引用越出任务目录")
    if not target.is_file():
        raise FileNotFoundError(f"任务文件不存在：{relative}")
    return target


def resolve_task_files(task_root: Path) -> dict:
    task_path = task_root / "task.json"
    try:
        task = json.loads(task_path.read_text()) if task_path.is_file() else {}
    except Exception as exc:
        raise RuntimeError(f"task.json 无法读取：{exc}") from exc
    original = safe_task_file(task_root, task.get("original_file"), "original.pdf")
    source = safe_task_file(
        task_root,
        task.get("translation_source_file") or task.get("original_file"),
        "original.pdf",
    )
    current = safe_task_file(task_root, task.get("translated_file"), "translated-zh.pdf")
    plan = safe_task_file(task_root, task.get("page_plan_file"), "page-plan.json")
    return {
        "task": task,
        "task_json": task_path if task_path.is_file() else None,
        "original": original,
        "source": source,
        "current": current,
        "plan": plan,
    }


def task_relative(task_root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(task_root.resolve()))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def page_contract(page: fitz.Page) -> dict:
    pixmap = page.get_pixmap(matrix=fitz.Matrix(96 / 72, 96 / 72), alpha=False)
    text = page.get_text("text").encode("utf-8")
    return {
        "render_sha256": hashlib.sha256(pixmap.samples).hexdigest(),
        "text_sha256": hashlib.sha256(text).hexdigest(),
        "rect": [round(value, 4) for value in page.rect],
        "rotation": page.rotation,
    }


def verify_non_target_pages(current: fitz.Document, candidate_path: Path,
                            target_pages: set[int]) -> dict:
    candidate = fitz.open(candidate_path)
    if len(current) != len(candidate):
        raise RuntimeError(f"候选页数改变：{len(current)} -> {len(candidate)}")
    mismatches = []
    checked = 0
    for index in range(len(current)):
        pdf_page = index + 1
        if pdf_page in target_pages:
            continue
        checked += 1
        if page_contract(current[index]) != page_contract(candidate[index]):
            mismatches.append(pdf_page)
    candidate.close()
    if mismatches:
        raise RuntimeError(f"候选改动了非目标页：{mismatches[:20]}")
    return {"checked_pages": checked, "mismatched_pages": []}


def font_path() -> Path:
    found = next((path for path in FONT_CANDIDATES if path.is_file()), None)
    if not found:
        raise RuntimeError("缺少可用中文字体")
    return found


def repair_font_name(page: fitz.Page) -> str:
    """Return a per-output-document font resource name for repair overlays.

    Reusing the literal /repair-cjk name on a page that embeds an earlier
    repaired page can make PyMuPDF bind new CID text to the old subset font
    program. The text layer survives through ToUnicode, but rendered glyphs are
    wrong. A fresh resource name per generated document/page keeps the old Form
    XObject subset and the new overlay subset independent.
    """
    document = page.parent
    state = getattr(document, "_repair_cjk_font_state", None)
    if state is None:
        state = {"token": uuid.uuid4().hex[:10], "names": {}}
        setattr(document, "_repair_cjk_font_state", state)
    token = state["token"]
    names = state["names"]
    page_number = page.number if page.number >= 0 else len(names)
    cached = names.get(page_number)
    if cached:
        return cached
    existing = {str(font[4]) for font in page.get_fonts(full=True) if len(font) > 4}
    base = f"repair-cjk-{token}-p{page_number + 1}"
    name = base
    suffix = 1
    while name in existing:
        suffix += 1
        name = f"{base}-{suffix}"
    names[page_number] = name
    return name


def needs_translation(text: str) -> bool:
    text = normalized_text(text)
    if re.fullmatch(r"PART\s+\d+", text, re.I):
        return True
    words = re.findall(r"[A-Za-z]{2,}", text)
    if english_letters(text) < 6 or len(words) < 2:
        return False
    if re.fullmatch(r"(?:https?://|www\.)\S+", text, re.I):
        return False
    return not allowed_english(text) or len(words) >= 3


def cell_needs_translation(text: str) -> bool:
    text = normalized_text(text)
    letters = "".join(char for char in text if char.isascii() and char.isalpha())
    if len(letters) < 3:
        return False
    if text == text.upper() and len(letters) <= 8 and " " not in text:
        return False
    return True


def translate_many(texts: list[str], instruction: str, broker: TranslationBroker) -> list[str]:
    return broker.translate(texts, instruction)


def display_to_page_rect(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
    """Map extraction/display coordinates to writable coordinates on rotated pages."""
    rect = fitz.Rect(rect)
    return rect * page.derotation_matrix if page.rotation else rect


def fit_text(page: fitz.Page, rect: fitz.Rect, text: str, *, center: bool = False,
             min_size: float = 4.0, max_size: float = 11.0,
             text_rotation: int = 0) -> bool:
    rect = fitz.Rect(rect)
    if rect.width < 4 or rect.height < 3:
        return False
    path = font_path()
    name = repair_font_name(page)
    page.insert_font(fontname=name, fontfile=str(path))
    align = fitz.TEXT_ALIGN_CENTER if center else fitz.TEXT_ALIGN_LEFT
    for size in (max_size, 10, 9, 8, 7, 6, 5, min_size):
        if size < min_size or size > max_size:
            continue
        spare = page.insert_textbox(
            rect, text, fontname=name, fontsize=size, align=align,
            color=(0, 0, 0), rotate=text_rotation, overlay=True,
        )
        if spare >= 0:
            return True
    return False


def overlay_records(out: fitz.Page, records: list[dict], instruction: str,
                    broker: TranslationBroker, *, erase_padding: float = 1.2) -> dict:
    targets = [item for item in records if needs_translation(item["text"])]
    translations = translate_many([item["text"] for item in targets], instruction, broker)
    placed, fallback = 0, []
    for item, translated in zip(targets, translations):
        rect = fitz.Rect(item["bbox"])
        erase = fitz.Rect(rect.x0 - erase_padding, rect.y0 - .6, rect.x1 + erase_padding, rect.y1 + .8)
        writable_rect = display_to_page_rect(out, rect)
        out.draw_rect(display_to_page_rect(out, erase), color=None, fill=(1, 1, 1), overlay=True)
        if fit_text(
            out, writable_rect, translated, center=False, min_size=4,
            max_size=max(6, min(12, item.get("size", 9))),
            text_rotation=out.rotation,
        ):
            placed += 1
        else:
            fallback.append(item["text"])
    return {"targets": len(targets), "placed": placed, "fallbacks": fallback}


def overlay_table_cells(out: fitz.Page, source: fitz.Page, broker: TranslationBroker) -> dict:
    try:
        tables = source.find_tables(strategy="lines_strict").tables
    except Exception:
        tables = []
    targets = []
    for table in tables:
        for row_index, (values, row) in enumerate(zip(table.extract(), table.rows)):
            for value, cell in zip(values, row.cells):
                if cell and value and cell_needs_translation(value):
                    targets.append((row_index, fitz.Rect(cell), normalized_text(value)))
    translations = translate_many(
        [item[2] for item in targets],
        CELL_INSTRUCTION,
        broker,
    )
    placed, fallback = 0, []
    for (row_index, rect, source_text), translated in zip(targets, translations):
        inner = fitz.Rect(rect.x0 + .7, rect.y0 + .7, rect.x1 - .7, rect.y1 - .7)
        writable_inner = display_to_page_rect(out, inner)
        out.draw_rect(writable_inner, color=None, fill=(1, 1, 1), overlay=True)
        if fit_text(
            out, writable_inner, translated, center=row_index < 2,
            min_size=3.5, max_size=8, text_rotation=out.rotation,
        ):
            placed += 1
        else:
            out.show_pdf_page(display_to_page_rect(out, rect), source.parent, source.number, clip=rect, overlay=True)
            fallback.append(source_text)
    return {"tables": len(tables), "targets": len(targets), "placed": placed, "fallbacks": fallback}


def repair_page(out: fitz.Page, source: fitz.Page, current: fitz.Page, family: str,
                inherited_toc: str | None, broker: TranslationBroker) -> tuple[dict, str | None]:
    rect = source.rect
    if family == "unexpected_text":
        out.show_pdf_page(rect, source.parent, source.number)
        return {"strategy": "preserve_source_noise", "placed": 0}, inherited_toc

    if family == "toc_layout":
        title, items = extract_navigation(source, inherited_toc)
        translations = translate_many(
            [item["source"] for item in items],
            TOC_INSTRUCTION,
            broker,
        )
        render_navigation(out, source, title, items, translations)
        return {"strategy": "semantic_toc_reflow", "items": len(items)}, title

    if family == "rotation_layout":
        cell_result = overlay_table_cells(out, source, broker)
        table_rects = []
        try:
            table_rects = [fitz.Rect(table.bbox) for table in source.find_tables(strategy="lines_strict").tables]
        except Exception:
            pass
        outside = [
            item for item in line_records(source)
            if not any(fitz.Rect(item["bbox"]).intersects(table_rect) for table_rect in table_rects)
        ]
        preserved = sum(needs_translation(item["text"]) for item in outside)
        line_result = {
            "targets": 0, "placed": 0, "fallbacks": [],
            "preserved_original": preserved,
            "strategy": "preserve_rotated_text_outside_detected_grid",
        }
        return {"strategy": "preserve_rotation_and_overlay", "rotation": source.rotation,
                "cells": cell_result, "outside": line_result}, inherited_toc

    if family == "table_layout":
        out.show_pdf_page(rect, current.parent, current.number)
        try:
            tables = source.find_tables(strategy="lines_strict").tables
        except Exception:
            tables = []
        for table in tables:
            table_rect = fitz.Rect(table.bbox)
            out.draw_rect(table_rect, color=None, fill=(1, 1, 1), overlay=True)
            out.show_pdf_page(table_rect, source.parent, source.number, clip=table_rect, overlay=True)
        cell_result = overlay_table_cells(out, source, broker)
        return {"strategy": "restore_grid_then_cell_overlay", "cells": cell_result}, inherited_toc

    if family in {"table_untranslated", "form_untranslated", "layout"}:
        out.show_pdf_page(rect, source.parent, source.number)
        cell_result = overlay_table_cells(out, source, broker)
        table_rects = []
        try:
            table_rects = [fitz.Rect(table.bbox) for table in source.find_tables(strategy="lines_strict").tables]
        except Exception:
            pass
        outside = [
            item for item in line_records(source)
            if not any(fitz.Rect(item["bbox"]).intersects(table_rect) for table_rect in table_rects)
        ]
        line_result = overlay_records(
            out, outside, FORM_INSTRUCTION, broker,
        )
        return {"strategy": "source_grid_cell_overlay", "cells": cell_result, "outside": line_result}, inherited_toc

    out.show_pdf_page(rect, current.parent, current.number)
    if family == "untranslated_region":
        result = overlay_records(out, line_records(current), HEADING_INSTRUCTION, broker)
        result["strategy"] = "localized_untranslated_overlay"
        return result, inherited_toc
    candidates = []
    for item in line_records(current):
        salient = item["size"] >= 10 or item["bbox"][1] < rect.height * .2 or item["bbox"][3] > rect.height * .86
        if salient and needs_translation(item["text"]):
            candidates.append(item)
    result = overlay_records(
        out, candidates, HEADING_INSTRUCTION, broker,
    )
    result["strategy"] = "localized_untranslated_overlay"
    return result, inherited_toc


def extract_subset(document: fitz.Document, cases: list[dict]) -> fitz.Document:
    result = fitz.open()
    for case in cases:
        page = int(case["pdf_page"]) - 1
        result.insert_pdf(document, from_page=page, to_page=page)
    return result


def table_texts(page: fitz.Page) -> tuple[list[str], list[fitz.Rect]]:
    try:
        tables = page.find_tables(strategy="lines_strict").tables
    except Exception:
        tables = []
    texts, rects = [], [fitz.Rect(table.bbox) for table in tables]
    for table in tables:
        for row in table.extract():
            for value in row:
                if value and cell_needs_translation(value):
                    texts.append(normalized_text(value))
    return texts, rects


def prefetch_cases(source: fitz.Document, current: fitz.Document, cases: list[dict],
                   broker: TranslationBroker) -> None:
    grouped = {instruction: [] for instruction in (
        TOC_INSTRUCTION, CELL_INSTRUCTION, ROTATION_INSTRUCTION,
        FORM_INSTRUCTION, HEADING_INSTRUCTION,
    )}
    inherited_toc = None
    for case in cases:
        source_page = source[int(case["pdf_page"]) - 1]
        current_page = current[int(case["pdf_page"]) - 1]
        family = case["family"]
        if family == "toc_layout":
            title, items = extract_navigation(source_page, inherited_toc)
            inherited_toc = title
            grouped[TOC_INSTRUCTION].extend(item["source"] for item in items)
            continue
        if family in {"table_layout", "table_untranslated", "form_untranslated", "rotation_layout", "layout"}:
            cells, rects = table_texts(source_page)
            grouped[CELL_INSTRUCTION].extend(cells)
            if family in {"table_untranslated", "form_untranslated", "layout"}:
                instruction = ROTATION_INSTRUCTION if family == "rotation_layout" else FORM_INSTRUCTION
                grouped[instruction].extend(
                    item["text"] for item in line_records(source_page)
                    if not any(fitz.Rect(item["bbox"]).intersects(rect) for rect in rects)
                    and needs_translation(item["text"])
                )
            continue
        if family == "untranslated_region":
            grouped[HEADING_INSTRUCTION].extend(
                item["text"] for item in line_records(current_page) if needs_translation(item["text"])
            )
            continue
        if family != "unexpected_text":
            rect = source_page.rect
            grouped[HEADING_INSTRUCTION].extend(
                item["text"] for item in line_records(current_page)
                if (item["size"] >= 10 or item["bbox"][1] < rect.height * .2 or item["bbox"][3] > rect.height * .86)
                and needs_translation(item["text"])
            )
    for instruction, texts in grouped.items():
        if texts:
            broker.translate(texts, instruction)


def run(task_root: Path, cases: list[dict], output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    refs = resolve_task_files(task_root)
    source = fitz.open(refs["source"])
    current = fitz.open(refs["current"])
    broker = TranslationBroker(task_root / "repair-translation-cache.json")
    prefetch_cases(source, current, cases, broker)
    source_subset = extract_subset(source, cases)
    before_subset = extract_subset(current, cases)
    source_path = output_dir / "source-sample.pdf"
    before_path = output_dir / "before-sample.pdf"
    after_path = output_dir / "after-sample.pdf"
    source_subset.save(source_path, garbage=4, deflate=True)
    before_subset.save(before_path, garbage=4, deflate=True)

    after = fitz.open()
    details, inherited_toc = [], None
    for index, case in enumerate(cases):
        source_page = source[int(case["pdf_page"]) - 1]
        current_page = current[int(case["pdf_page"]) - 1]
        if case["family"] == "rotation_layout":
            after.insert_pdf(source, from_page=source_page.number, to_page=source_page.number)
            out = after[-1]
        else:
            rect = source_page.rect
            out = after.new_page(width=rect.width, height=rect.height)
        detail, inherited_toc = repair_page(out, source_page, current_page, case["family"], inherited_toc, broker)
        detail.update(sample_page=index + 1, original_pdf_page=case["pdf_page"], family=case["family"])
        details.append(detail)
    after.save(after_path, garbage=4, deflate=True)

    baseline = {"version": 1, "tasks": {"sample": [
        {"pdf_page": index + 1, "family": case["family"]} for index, case in enumerate(cases)
    ]}}
    baseline_path = output_dir / "sample-baseline.json"
    baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2))
    before_report = audit(source_path, before_path, baseline_path=baseline_path, task_id="sample")
    after_report = audit(source_path, after_path, baseline_path=baseline_path, task_id="sample")
    (output_dir / "qa-before.json").write_text(json.dumps(before_report, ensure_ascii=False, indent=2))
    (output_dir / "qa-after.json").write_text(json.dumps(after_report, ensure_ascii=False, indent=2))
    mapping = {"task_root": str(task_root), "cases": cases, "repairs": details,
               "translation_metrics": broker.metrics,
               "before": {"status": before_report["status"], "summary": before_report["summary"]},
               "after": {"status": after_report["status"], "summary": after_report["summary"]}}
    (output_dir / "harness-result.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2))
    return mapping


def run_full(task_root: Path, cases: list[dict], output_dir: Path,
             baseline_path: Path | None = None, task_id: str | None = None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    refs = resolve_task_files(task_root)
    source = fitz.open(refs["source"])
    current = fitz.open(refs["current"])
    broker = TranslationBroker(task_root / "repair-translation-cache.json")
    ordered_cases = sorted(cases, key=lambda item: int(item["pdf_page"]))
    prefetch_cases(source, current, ordered_cases, broker)
    case_map = {int(item["pdf_page"]): item for item in ordered_cases}
    after = fitz.open()
    details, inherited_toc = [], None
    for index in range(len(source)):
        pdf_page = index + 1
        case = case_map.get(pdf_page)
        if not case:
            after.insert_pdf(current, from_page=index, to_page=index)
            continue
        source_page, current_page = source[index], current[index]
        if case["family"] == "rotation_layout":
            after.insert_pdf(source, from_page=index, to_page=index)
            out = after[-1]
        else:
            rect = source_page.rect
            out = after.new_page(width=rect.width, height=rect.height)
        detail, inherited_toc = repair_page(
            out, source_page, current_page, case["family"], inherited_toc, broker,
        )
        detail.update(original_pdf_page=pdf_page, family=case["family"])
        details.append(detail)
    repaired_path = output_dir / "translated-zh.repaired.pdf"
    after.save(repaired_path, garbage=4, deflate=True)
    after.close()
    target_pages = set(case_map)
    non_target_integrity = verify_non_target_pages(current, repaired_path, target_pages)

    plan_path = refs["plan"]
    plan = json.loads(plan_path.read_text()) if plan_path.is_file() else {"version": 2, "pages": []}
    pages = {int(item["pdf_page"]): item for item in plan.get("pages", [])}
    for detail in details:
        page = pages.get(int(detail["original_pdf_page"]))
        if not page:
            continue
        page["repair"] = detail
        page.pop("fallback", None)
        page.pop("fallback_cells", None)
        page.pop("companion_fallbacks", None)
        family = detail["family"]
        if family == "toc_layout":
            page.update(type="navigation", policy="structured_reflow")
        elif family in {"table_layout", "table_untranslated", "form_untranslated", "rotation_layout"}:
            page.update(type="cell_table", policy="translate_table_cells")
        else:
            page.update(type="narrative", policy="standard_translation")
    repaired_plan_path = output_dir / "page-plan.repaired.json"
    repaired_plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    qa_report = audit(
        refs["source"], repaired_path, repaired_plan_path,
        baseline_path=baseline_path, task_id=task_id,
        task_json_path=refs["task_json"],
        visual_source_path=refs["original"] if refs["original"] != refs["source"] else None,
    )
    qa_path = output_dir / "qa-repaired.json"
    qa_path.write_text(json.dumps(qa_report, ensure_ascii=False, indent=2))
    result = {
        "task_root": str(task_root), "task_id": task_id, "cases": ordered_cases,
        "repairs": details, "translation_metrics": broker.metrics,
        "input_files": {
            "source": {"path": task_relative(task_root, refs["source"]), "sha256": file_sha256(refs["source"])},
            "current": {"path": task_relative(task_root, refs["current"]), "sha256": file_sha256(refs["current"])},
            "plan": {"path": task_relative(task_root, refs["plan"]), "sha256": file_sha256(refs["plan"])},
        },
        "non_target_integrity": non_target_integrity,
        "qa": {"status": qa_report["status"], "summary": qa_report["summary"],
               "flagged_pages": qa_report["flagged_pages"], "baseline": qa_report["baseline"]},
        "repaired_file": repaired_path.name, "repaired_plan": repaired_plan_path.name,
        "qa_file": qa_path.name,
    }
    (output_dir / "full-repair-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_root", type=Path)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--task-id")
    args = parser.parse_args()
    payload = json.loads(args.cases.read_text())
    runner = run_full if args.full else run
    if args.full:
        result = runner(args.task_root, payload["cases"], args.output, args.baseline, args.task_id)
    else:
        result = runner(args.task_root, payload["cases"], args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
