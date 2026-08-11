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
import time
import urllib.request
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_router import (  # noqa: E402
    FONT_CANDIDATES,
    extract_navigation,
    render_navigation,
)
from qa_alpha import audit, allowed_english, english_letters, line_records, normalized_text  # noqa: E402


GLOSSARY = {
    "Total": "总计", "PART 3": "第3部分", "Canada": "加拿大", "Japan": "日本",
    "China": "中国", "Korea": "韩国", "Brazil": "巴西", "Barbados": "巴巴多斯",
    "Venezuela": "委内瑞拉", "Mexico": "墨西哥", "Morocco": "摩洛哥",
    "United States": "美国", "European Community": "欧洲共同体",
    "Contracting Parties": "缔约方", "Other Contracting Parties": "其他缔约方",
    "Trinidad & Tobago": "特立尼达和多巴哥",
    "UK (Overseas Territories) (4)": "英国（海外领土）(4)",
    "France (St. Pierre et Miquelon) (4)": "法国（圣皮埃尔和密克隆）(4)",
}
TOC_INSTRUCTION = "把下面目录标题逐条翻译成简洁准确的中文。保留缩略语、编号、年份、拉丁学名和专有名词；不要添加解释。"
CELL_INSTRUCTION = "逐格翻译表格或表单中的英文为简洁准确的中文。保留编号、金额、单位、缩略语、专有名词和拉丁学名；不要添加解释。"
ROTATION_INSTRUCTION = "逐条翻译旋转表格页面的标题、说明或表单字段为简洁准确的中文。保留编号、金额、单位、缩略语和专有名词；不要添加解释。"
FORM_INSTRUCTION = "逐条翻译页面标题、说明或表单字段为简洁准确的中文。保留编号、金额、单位、缩略语、专有名词和拉丁学名；不要添加解释。"
HEADING_INSTRUCTION = "逐条翻译仍为英文的页面标题、页眉页脚或重要标签。保留编号、缩略语、专有名词和拉丁学名；不要添加解释。"


class TranslationBroker:
    """Task-local translation cache with bounded, ID-stable AI batches."""

    def __init__(self, cache_path: Path, *, max_calls: int = 12, batch_size: int = 40,
                 max_batch_chars: int = 8000):
        self.cache_path = cache_path
        try:
            self.cache = json.loads(cache_path.read_text()) if cache_path.is_file() else {}
        except Exception:
            self.cache = {}
        self.max_calls = max_calls
        self.batch_size = batch_size
        self.max_batch_chars = max_batch_chars
        self.metrics = {"requests": 0, "ai_seconds": 0.0, "cache_hits": 0,
                        "glossary_hits": 0, "unique_ai_items": 0, "unresolved": [], "errors": []}

    @staticmethod
    def cache_key(text: str, instruction: str) -> str:
        payload = "repair-v2\n" + normalized_text(instruction) + "\n" + normalized_text(text)
        return hashlib.sha256(payload.encode()).hexdigest()

    def save(self) -> None:
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2))
        temporary.replace(self.cache_path)

    def _request(self, entries: list[dict], instruction: str) -> dict[str, str]:
        if self.metrics["requests"] >= self.max_calls:
            return {}
        base = os.environ.get("OPENAILIKED_BASE_URL")
        model = os.environ.get("OPENAILIKED_MODEL", "codex")
        key = os.environ.get("OPENAILIKED_API_KEY", "local")
        if not base:
            raise RuntimeError("修复翻译缺少 OPENAILIKED_BASE_URL")
        prompt = (
            instruction
            + "\n输入是带稳定 id 的 JSON 数组。只返回 JSON 数组，每项必须包含原 id 和 translation；"
              "不要省略、合并或改变 id。\n"
            + json.dumps(entries, ensure_ascii=False)
        )
        body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}).encode()
        request = urllib.request.Request(
            base.rstrip("/") + "/chat/completions", data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        started = time.monotonic()
        self.metrics["requests"] += 1
        try:
            with urllib.request.urlopen(request, timeout=100) as response:
                payload = json.loads(response.read())
            content = payload["choices"][0]["message"]["content"].strip()
            match = re.search(r"\[[\s\S]*\]", content)
            decoded = json.loads(match.group(0) if match else content)
            return {
                str(item.get("id")): str(item.get("translation", "")).strip()
                for item in decoded if isinstance(item, dict) and item.get("id") is not None
            }
        except Exception as exc:
            self.metrics["errors"].append(type(exc).__name__)
            return {}
        finally:
            self.metrics["ai_seconds"] += round(time.monotonic() - started, 3)

    def translate(self, texts: list[str], instruction: str) -> list[str]:
        normalized = [normalized_text(text) for text in texts]
        resolved: dict[str, str] = {}
        pending: list[str] = []
        for text in dict.fromkeys(normalized):
            if text in GLOSSARY:
                resolved[text] = GLOSSARY[text]
                self.metrics["glossary_hits"] += 1
                continue
            cache_key = self.cache_key(text, instruction)
            if cache_key in self.cache:
                resolved[text] = self.cache[cache_key]
                self.metrics["cache_hits"] += 1
            else:
                pending.append(text)
        self.metrics["unique_ai_items"] += len(pending)

        batches, current, current_chars = [], [], 0
        for text in pending:
            if current and (len(current) >= self.batch_size or current_chars + len(text) > self.max_batch_chars):
                batches.append(current); current, current_chars = [], 0
            current.append(text); current_chars += len(text)
        if current:
            batches.append(current)

        for batch in batches:
            entries = [{"id": f"t{index}", "text": text} for index, text in enumerate(batch)]
            returned = self._request(entries, instruction)
            missing = []
            for entry in entries:
                translation = returned.get(entry["id"], "")
                if translation:
                    text = entry["text"]
                    resolved[text] = translation
                    self.cache[self.cache_key(text, instruction)] = translation
                else:
                    missing.append(entry)
            if missing and self.metrics["requests"] < self.max_calls:
                retry = self._request(missing, instruction)
                for entry in missing:
                    translation = retry.get(entry["id"], "")
                    if translation:
                        text = entry["text"]
                        resolved[text] = translation
                        self.cache[self.cache_key(text, instruction)] = translation
                    else:
                        self.metrics["unresolved"].append(entry["text"])
        self.save()
        return [resolved.get(text, text) for text in normalized]


def font_path() -> Path:
    found = next((path for path in FONT_CANDIDATES if path.is_file()), None)
    if not found:
        raise RuntimeError("缺少可用中文字体")
    return found


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
    path = font_path()
    name = "repair-cjk"
    page.insert_font(fontname=name, fontfile=str(path))
    rect = fitz.Rect(rect)
    if rect.width < 4 or rect.height < 3:
        return False
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
    source = fitz.open(task_root / "original.pdf")
    current = fitz.open(task_root / "translated-zh.pdf")
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
    source = fitz.open(task_root / "original.pdf")
    current = fitz.open(task_root / "translated-zh.pdf")
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

    plan_path = task_root / "page-plan.json"
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
        task_root / "original.pdf", repaired_path, repaired_plan_path,
        baseline_path=baseline_path, task_id=task_id,
    )
    qa_path = output_dir / "qa-repaired.json"
    qa_path.write_text(json.dumps(qa_report, ensure_ascii=False, indent=2))
    result = {
        "task_root": str(task_root), "task_id": task_id, "cases": ordered_cases,
        "repairs": details, "translation_metrics": broker.metrics,
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
