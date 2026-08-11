#!/usr/bin/env python3
"""Gate 1c-alpha: deterministic text-layer and rendered-page PDF QA.

This script does not repair output. It produces evidence for COMPLETED vs
NEEDS_REVIEW and can score a local, page-level known-defect baseline.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

import cv2
import fitz
import numpy as np

from qa_contract import (
    build_contract, category_summary, classify_issue, gate_status, page_status,
    score_precision_recall, severity_summary,
)


REPEAT_RE = re.compile(r"([\u3400-\u9fff])\1{2,}")
EN_WORD_RE = re.compile(r"[A-Za-z]{2,}")
CJK_RE = re.compile(r"[\u3400-\u9fff]")
TOC_RE = re.compile(r"\.{3,}\s*\d+\s*$", re.M)
ALLOWED_SHORT_ENGLISH = re.compile(r"^[A-Z0-9%_./,()\-–—\s]{1,48}$")
MODEL_META_RESPONSE_RE = re.compile(
    r"(?:^|[.!?]\s+)(?:I\s+translate\b|I['’]ll\b|I\s+can['’]t\b|Let\s+me\b|The\s+translated\s+text\b)|translation\s+engine",
    re.I | re.M,
)


def cjk_count(text: str) -> int:
    return len(CJK_RE.findall(text))


def model_meta_response_leak(text: str) -> re.Match | None:
    nonspace = len(re.sub(r"\s", "", text))
    cjk = cjk_count(text)
    if cjk < 3 or cjk / max(nonspace, 1) < 0.10:
        return None
    return MODEL_META_RESPONSE_RE.search(text)


def english_letters(text: str) -> int:
    return sum(char.isascii() and char.isalpha() for char in text)


def normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def line_records(page: fitz.Page) -> list[dict]:
    records = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = normalized_text("".join(span.get("text", "") for span in spans))
            if not text:
                continue
            sizes = [float(span.get("size", 0)) for span in spans if span.get("text", "").strip()]
            records.append({
                "text": text,
                "bbox": list(line.get("bbox", (0, 0, 0, 0))),
                "size": max(sizes) if sizes else 0.0,
                "dir": list(line.get("dir", (1, 0))),
            })
    return records


def rect_overlap_ratio(a: fitz.Rect, b: fitz.Rect) -> float:
    inter = a & b
    if inter.is_empty:
        return 0.0
    return inter.get_area() / max(1.0, min(a.get_area(), b.get_area()))


def has_nearby_cjk(record: dict, records: list[dict]) -> bool:
    rect = fitz.Rect(record["bbox"])
    expanded = fitz.Rect(rect.x0 - 3, rect.y0 - 3, rect.x1 + 3, rect.y1 + 3)
    return any(
        other is not record and cjk_count(other["text"]) >= 2
        and (rect_overlap_ratio(expanded, fitz.Rect(other["bbox"])) >= .3)
        for other in records
    )


def allowed_english(text: str) -> bool:
    stripped = normalized_text(text)
    if not stripped:
        return True
    if ALLOWED_SHORT_ENGLISH.fullmatch(stripped):
        return True
    if re.fullmatch(r"(?:https?://|www\.)\S+", stripped, re.I):
        return True
    words = EN_WORD_RE.findall(stripped)
    if len(words) <= 1 and len(stripped) < 40:
        return True
    return False


def render_gray(page: fitz.Page, dpi: int = 96) -> np.ndarray:
    scale = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)


def ink_ratio(image: np.ndarray) -> float:
    return float(np.mean(image < 235))


def occupancy(image: np.ndarray, rows: int = 8, cols: int = 8) -> np.ndarray:
    h, w = image.shape
    result = np.zeros((rows, cols), dtype=float)
    for row in range(rows):
        for col in range(cols):
            y0, y1 = round(row * h / rows), round((row + 1) * h / rows)
            x0, x1 = round(col * w / cols), round((col + 1) * w / cols)
            result[row, col] = ink_ratio(image[y0:y1, x0:x1])
    return result


def structure_mask(image: np.ndarray) -> np.ndarray:
    binary = cv2.threshold(image, 205, 255, cv2.THRESH_BINARY_INV)[1]
    length = max(18, min(image.shape) // 30)
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, length)))
    return cv2.bitwise_or(horizontal, vertical) > 0


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        if a.shape == b.T.shape:
            clockwise = np.rot90(b, -1)
            counterclockwise = np.rot90(b, 1)
            b = max(
                (clockwise, counterclockwise),
                key=lambda candidate: float(np.logical_and(a, candidate).sum()),
            )
        else:
            b = cv2.resize(b.astype(np.uint8), (a.shape[1], a.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    union = np.logical_or(a, b).sum()
    return 1.0 if not union else float(np.logical_and(a, b).sum() / union)


def align_render(source: np.ndarray, output: np.ndarray) -> np.ndarray:
    """Align output raster orientation to source before occupancy comparison."""
    if source.shape == output.shape:
        return output
    if source.shape == output.T.shape:
        candidates = (np.rot90(output, -1), np.rot90(output, 1))
        return min(candidates, key=lambda image: float(np.mean(np.abs(source.astype(float) - image.astype(float)))))
    return cv2.resize(output, (source.shape[1], source.shape[0]), interpolation=cv2.INTER_AREA)


def dominant_directions(records: list[dict]) -> tuple[float, float]:
    if not records:
        return 0.0, 0.0
    vertical = sum(1 for item in records if abs(item["dir"][1]) > .7)
    return vertical / len(records), 1 - vertical / len(records)


def issue(kind: str, severity: str, evidence: str, region=None) -> dict:
    result = {"issue_type": kind, "severity": severity, "evidence": evidence}
    if region is not None:
        result["region"] = [round(float(value), 1) for value in region]
    return result


def page_issues(source: fitz.Page, output: fitz.Page, plan: dict | None,
                visual_source: fitz.Page | None = None, route: str = "text",
                refusal_fallback: bool = False) -> tuple[list[dict], dict]:
    issues: list[dict] = []
    source_text, output_text = source.get_text("text"), output.get_text("text")
    source_lines, output_lines = line_records(source), line_records(output)
    page_rect = output.rect
    sizes = [item["size"] for item in output_lines if item["size"] > 0]
    median_size = float(np.median(sizes)) if sizes else 0.0

    if source.rotation != output.rotation:
        issues.append(issue("rotation_metadata_mismatch", "critical", f"rotation {source.rotation} -> {output.rotation}"))

    source_vertical, _ = dominant_directions(source_lines)
    output_vertical, _ = dominant_directions(output_lines)
    if source_vertical >= .18 and abs(source_vertical - output_vertical) >= .16:
        issues.append(issue("text_direction_mismatch", "critical", f"vertical line ratio {source_vertical:.2f} -> {output_vertical:.2f}"))

    repeated = sorted(set(match.group(0) for match in REPEAT_RE.finditer(output_text)))
    if repeated:
        issues.append(issue("unexpected_repetition", "critical", "repeated CJK sequence: " + ", ".join(repeated[:5])))
    control_chars = sorted(set(ord(char) for char in output_text if ord(char) < 32 and char not in "\n\r\t"))

    prominent_english = []
    for record in output_lines:
        text = record["text"]
        if english_letters(text) < 12 or len(EN_WORD_RE.findall(text)) < 2 or allowed_english(text):
            continue
        if cjk_count(text) >= 3 or has_nearby_cjk(record, output_lines):
            continue
        rect = fitz.Rect(record["bbox"])
        top_or_bottom = rect.y1 < page_rect.height * .18 or rect.y0 > page_rect.height * .86
        title_salient = record["size"] >= max(11.5, median_size * 1.35)
        protected_title = bool(plan and plan.get("policy") == "protect_table_translate_caption" and rect.y1 < page_rect.height * .25)
        prominent_english.append((record, title_salient or protected_title, top_or_bottom))
    for record, salient, _edge in sorted(prominent_english, key=lambda item: item[0]["size"], reverse=True)[:12]:
        severity = "critical" if salient else "warning"
        issues.append(issue(
            "prominent_english_untranslated" if salient else "english_region_untranslated",
            severity, record["text"][:180], record["bbox"],
        ))

    source_letters = english_letters(source_text)
    output_cjk = cjk_count(output_text)
    leaked = model_meta_response_leak(output_text)
    if leaked:
        issues.append(issue("model_meta_response_leak", "critical", leaked.group(0).strip()[:120]))
    if source_letters >= 30 and output_cjk < max(4, source_letters * .015):
        severity = "warning" if refusal_fallback else "critical"
        suffix = "; 按设计保留原文（模型拒答回退）" if refusal_fallback else ""
        coverage_issue = issue("page_translation_coverage_low", severity, f"source English letters={source_letters}, output CJK={output_cjk}{suffix}")
        if refusal_fallback:
            coverage_issue["designed_fallback"] = True
        issues.append(coverage_issue)

    source_toc = bool(re.search(r"\b(?:TABLE OF )?CONTENTS\b", source_text, re.I)) or len(TOC_RE.findall(source_text)) >= 3
    if control_chars:
        issues.append(issue(
            "unexpected_control_characters", "critical" if source_toc or len(source_text.strip()) < 20 else "warning",
            "control codepoints: " + ", ".join(map(str, control_chars)),
        ))
    if source_toc:
        right_fragments = sum(
            1 for item in output_lines
            if item["bbox"][0] > page_rect.width * .74 and len(item["text"]) <= 30
        )
        overlaps = 0
        sorted_lines = sorted(output_lines, key=lambda item: (item["bbox"][1], item["bbox"][0]))
        for index, first in enumerate(sorted_lines):
            a = fitz.Rect(first["bbox"])
            for second in sorted_lines[index + 1:index + 8]:
                b = fitz.Rect(second["bbox"])
                if b.y0 > a.y1 + 2:
                    break
                if rect_overlap_ratio(a, b) >= .12:
                    overlaps += 1
        if right_fragments >= 3 or overlaps >= 2:
            issues.append(issue("toc_layout_suspect", "critical", f"right fragments={right_fragments}, overlapping lines={overlaps}"))

    # OCR translation sources may intentionally have a white visible layer.
    # Render comparisons must use what the reader sees in the original pane,
    # while text, direction and font checks continue to use the translation source.
    source_ink = output_ink = structure_iou = None
    missing_regions = crowded_regions = 0
    structured_page = bool(plan and plan.get("policy") in {"translate_table_cells", "protect_table_translate_caption", "preserve_original"})
    if route != "ocr":
        source_image, output_image = render_gray(visual_source or source), render_gray(output)
        output_image = align_render(source_image, output_image)
        source_ink, output_ink = ink_ratio(source_image), ink_ratio(output_image)
        source_occ, output_occ = occupancy(source_image), occupancy(output_image)
        missing_regions = int(np.logical_and(source_occ > .025, output_occ < .004).sum())
        crowded_regions = int(np.logical_and(output_occ > .19, output_occ > source_occ * 2.8 + .03).sum())
        if source_ink > .01 and output_ink < source_ink * .32:
            issues.append(issue("rendered_page_too_sparse", "critical", f"ink ratio {source_ink:.3f} -> {output_ink:.3f}"))
        if missing_regions >= 4:
            severity = "critical" if structured_page or source_toc or source_vertical >= .18 else "warning"
            issues.append(issue("rendered_regions_missing", severity, f"missing occupancy cells={missing_regions}"))
        if crowded_regions >= 2:
            issues.append(issue("rendered_regions_crowded", "critical", f"crowded occupancy cells={crowded_regions}"))
        source_structure, output_structure = structure_mask(source_image), structure_mask(output_image)
        structure_pixels = int(source_structure.sum())
        structure_iou = mask_iou(source_structure, output_structure)
        if structure_pixels > 1200 and structure_iou < .58 and (structured_page or source_vertical >= .18):
            issues.append(issue("rendered_structure_drift", "critical", f"line/grid IoU={structure_iou:.2f}"))

    source_sizes = [item["size"] for item in source_lines if item["size"] > 0]
    source_median = float(np.median(source_sizes)) if source_sizes else 0.0
    if source_median >= 5 and median_size > 0 and median_size < source_median * .58:
        issues.append(issue("rendered_text_too_small", "critical", f"median font {source_median:.1f} -> {median_size:.1f}"))

    if plan and plan.get("policy") in {"preserve_original", "protect_table_translate_caption"}:
        issues.append(issue("strategy_preserved_source_region", "warning", f"policy={plan.get('policy')}"))
    if plan and plan.get("companion_fallbacks", 0):
        issues.append(issue("structured_region_fallback", "critical", f"companion fallbacks={plan['companion_fallbacks']}"))

    metrics = {
        "source_ink_ratio": round(source_ink, 4) if source_ink is not None else None,
        "output_ink_ratio": round(output_ink, 4) if output_ink is not None else None,
        "structure_iou": round(structure_iou, 4) if structure_iou is not None else None, "missing_regions": missing_regions,
        "crowded_regions": crowded_regions, "source_vertical_ratio": round(source_vertical, 3),
        "output_vertical_ratio": round(output_vertical, 3), "source_english_letters": source_letters,
        "output_cjk": output_cjk,
    }
    return issues, metrics


def load_plan(path: Path | None) -> dict[int, dict]:
    if not path or not path.is_file():
        return {}
    payload = json.loads(path.read_text())
    return {int(item["pdf_page"]): item for item in payload.get("pages", [])}


def load_document_routes(path: Path | None) -> dict[int, str]:
    if not path or not path.is_file():
        return {}
    payload = json.loads(path.read_text())
    return {int(item["page"]): item.get("route", "text") for item in payload.get("pages", [])}


def load_refusal_pages(path: Path | None) -> set[int]:
    if not path or not path.is_file():
        return set()
    pages = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("code") == "translation_refusal_kept_source":
            pages.update(int(page) for page in event.get("pages", []))
    return pages


def load_baseline(path: Path | None, task_id: str | None) -> list[dict]:
    if not path or not path.is_file() or not task_id:
        return []
    payload = json.loads(path.read_text())
    return payload.get("tasks", {}).get(task_id, [])


def load_fixture_pages(path: Path | None, task_id: str | None) -> list[dict]:
    if not path or not path.is_file() or not task_id:
        return []
    payload = json.loads(path.read_text())
    return [
        page for page in payload.get("pages", [])
        if (page.get("task_pointer") or {}).get("task_id") == task_id
    ]


def load_task_projection(path: Path | None) -> dict | None:
    if not path or not path.is_file():
        return None
    return json.loads(path.read_text())


def audit(original_path: Path, output_path: Path, plan_path: Path | None = None,
          baseline_path: Path | None = None, task_id: str | None = None,
          task_json_path: Path | None = None, fixture_manifest_path: Path | None = None,
          visual_source_path: Path | None = None, document_plan_path: Path | None = None,
          translation_warnings_path: Path | None = None) -> dict:
    original, output = fitz.open(original_path), fitz.open(output_path)
    visual_source = fitz.open(visual_source_path) if visual_source_path else original
    plan = load_plan(plan_path)
    routes = load_document_routes(document_plan_path)
    refusal_pages = load_refusal_pages(translation_warnings_path)
    pages, document_issues = [], []
    if len(original) != len(output):
        document_issues.append(classify_issue(issue("page_count_changed", "critical", f"{len(original)} -> {len(output)}")))
    if len(visual_source) != len(output):
        document_issues.append(classify_issue(issue(
            "page_count_changed", "critical", f"visual source {len(visual_source)} -> {len(output)}",
        )))
    count = min(len(original), len(output), len(visual_source))
    for index in range(count):
        found, metrics = page_issues(
            original[index], output[index], plan.get(index + 1), visual_source[index],
            routes.get(index + 1, "text"), index + 1 in refusal_pages,
        )
        classified = [classify_issue(item, plan.get(index + 1)) for item in found]
        pages.append({"pdf_page": index + 1, "status": page_status(classified), "issues": classified, "metrics": metrics})

    known = load_baseline(baseline_path, task_id)
    flagged_pages = {item["pdf_page"] for item in pages if item["issues"]}
    hits = [item for item in known if int(item["pdf_page"]) in flagged_pages]
    misses = [item for item in known if int(item["pdf_page"]) not in flagged_pages]
    baseline = {
        "known_defects": len(known), "detected": len(hits), "missed": len(misses),
        "page_recall": round(len(hits) / len(known), 4) if known else None,
        "misses": misses,
    }
    severity_counts = severity_summary(pages, document_issues)
    categories = category_summary(pages, document_issues)
    task = load_task_projection(task_json_path)
    contract = build_contract(
        original_path=original_path, output_path=output_path, plan_path=plan_path,
        task=task,
    )
    fixture_pages = load_fixture_pages(fixture_manifest_path, task_id)
    quality_gate = score_precision_recall({"pages": pages, "task_id": task_id}, fixture_pages) if fixture_manifest_path else None
    return {
        "version": 2, "gate": "1c-alpha", "status": gate_status(severity_counts),
        "page_count": count, "document_issues": document_issues, "summary": severity_counts,
        "issue_category_summary": categories,
        "flagged_pages": [item["pdf_page"] for item in pages if item["issues"]],
        "baseline": baseline, "quality_gate": quality_gate, "contract": contract, "pages": pages,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("original", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--task-id")
    parser.add_argument("--task-json", type=Path)
    parser.add_argument("--fixture-manifest", type=Path)
    parser.add_argument("--visual-source", type=Path)
    parser.add_argument("--document-plan", type=Path)
    parser.add_argument("--translation-warnings", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = audit(
        args.original, args.output, args.plan, args.baseline, args.task_id,
        task_json_path=args.task_json, fixture_manifest_path=args.fixture_manifest,
        visual_source_path=args.visual_source,
        document_plan_path=args.document_plan,
        translation_warnings_path=args.translation_warnings,
    )
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({key: report[key] for key in ("status", "page_count", "summary", "flagged_pages", "baseline", "quality_gate")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
