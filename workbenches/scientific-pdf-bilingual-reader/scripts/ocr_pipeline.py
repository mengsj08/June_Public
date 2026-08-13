#!/usr/bin/env python3
"""Page routing and searchable-PDF composition for the OCR vertical slice."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import fitz
from ocr_runtime import runtime_paths as ocr_runtime_paths
from scan_translate_pipeline import deskew_record_image, line_geometry, line_pdf_rect

ROOT = Path(__file__).resolve().parents[1]


def parse_page_selection(value: str | list[int] | None) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        pages = [int(item) for item in value]
    else:
        pages = []
        for token in re.split(r"[,，\s]+", str(value).strip()):
            if not token:
                continue
            if "-" in token:
                start, end = (int(part.strip()) for part in token.split("-", 1))
                if start < 1 or end < start:
                    raise ValueError(f"非法页码范围：{token}")
                pages.extend(range(start, end + 1))
            else:
                page = int(token)
                if page < 1:
                    raise ValueError(f"非法页码：{token}")
                pages.append(page)
    if any(page < 1 for page in pages):
        raise ValueError("页码必须从 1 开始")
    return sorted(set(pages))


def normalise_image_selection(value: list[dict] | None) -> list[dict]:
    selected = []
    for item in value or []:
        page, image = int(item.get("page", 0)), int(item.get("image", 0))
        if page < 1 or image < 1:
            raise ValueError("图片 OCR 必须包含从 1 开始的页码和图片序号")
        selected.append({"page": page, "image": image})
    return sorted({(item["page"], item["image"]) for item in selected})


def _page_images(page: fitz.Page) -> list[dict]:
    records, seen = [], set()
    for image in page.get_images(full=True):
        xref = int(image[0])
        try:
            rects = page.get_image_rects(xref)
        except (RuntimeError, ValueError):
            continue
        for rect in rects:
            clipped = rect & page.rect
            key = (xref, round(clipped.x0, 3), round(clipped.y0, 3), round(clipped.x1, 3), round(clipped.y1, 3))
            if clipped.is_empty or key in seen:
                continue
            seen.add(key)
            records.append({
                "xref": xref,
                "rect_pdf": [clipped.x0, clipped.y0, clipped.x1, clipped.y1],
                "source_width": int(image[2]),
                "source_height": int(image[3]),
                "coverage": round(clipped.width * clipped.height / max(page.rect.width * page.rect.height, 1.0), 4),
            })
    records.sort(key=lambda item: (item["rect_pdf"][1], item["rect_pdf"][0], item["xref"]))
    for index, record in enumerate(records, start=1):
        record["image"] = index
    return records


def _image_coverage(page: fitz.Page, images: list[dict] | None = None) -> float:
    page_area = max(page.rect.width * page.rect.height, 1.0)
    areas = [
        (item["rect_pdf"][2] - item["rect_pdf"][0]) * (item["rect_pdf"][3] - item["rect_pdf"][1])
        for item in (images if images is not None else _page_images(page))
    ]
    return min(1.0, sum(areas) / page_area)


def analyze_document(
    source: Path,
    forced_pages: list[int] | None = None,
    forced_images: list[dict] | None = None,
) -> dict:
    forced = set(parse_page_selection(forced_pages))
    selected_images = set(normalise_image_selection(forced_images))
    document = fitz.open(source)
    if forced and max(forced) > document.page_count:
        document.close()
        raise ValueError(f"强制 OCR 页码超过文档总页数 {document.page_count}")
    pages = []
    counts = {"text": 0, "ocr": 0, "blank": 0}
    warnings = []
    for index, page in enumerate(document, start=1):
        text = page.get_text("text") or ""
        nonspace_chars = len(re.sub(r"\s", "", text))
        words = len(page.get_text("words") or [])
        images = _page_images(page)
        image_coverage = _image_coverage(page, images)
        forced_route = index in forced
        sparse_text = nonspace_chars < 40 or words < 8
        likely_scanned = image_coverage >= 0.45 and sparse_text
        if forced_route or likely_scanned:
            route = "ocr"
            reason = "manual_override" if forced_route else "image_page_with_missing_or_sparse_text"
        elif nonspace_chars == 0 and image_coverage < 0.05:
            route = "blank"
            reason = "blank_page_preserved"
        else:
            route = "text"
            reason = "usable_text_layer"
        counts[route] += 1
        if nonspace_chars == 0 and route == "text":
            warnings.append({"page": index, "code": "empty_text_page_not_routed"})
        pages.append({
            "page": index,
            "route": route,
            "reason": reason,
            "manual": forced_route,
            "text_chars": nonspace_chars,
            "words": words,
            "image_coverage": round(image_coverage, 4),
            "rotation_metadata": page.rotation,
            "images": images,
        })
    known_images = {
        (page["page"], image["image"]): {"page": page["page"], **image}
        for page in pages for image in page["images"]
    }
    missing = sorted(selected_images - set(known_images))
    if missing:
        document.close()
        page, image = missing[0]
        raise ValueError(f"第 {page} 页没有图片 #{image}")
    ocr_pages = [page["page"] for page in pages if page["route"] == "ocr"]
    ocr_images = [
        {**known_images[key], "kind": "image"}
        for key in sorted(selected_images)
        if key[0] not in ocr_pages
    ]
    document.close()
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "page_count": len(pages),
        "forced_ocr_pages": sorted(forced),
        "forced_ocr_images": [{"page": page, "image": image} for page, image in sorted(selected_images)],
        "routes": counts,
        "ocr_required": counts["ocr"] > 0 or bool(ocr_images),
        "ocr_pages": ocr_pages,
        "ocr_images": ocr_images,
        "ocr_unit_count": len(ocr_pages) + len(ocr_images),
        "warnings": warnings,
        "pages": pages,
    }


def write_plan(plan: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(".tmp")
    temp.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(destination)


def run_worker(source: Path, plan: dict, ocr_python: Path, results: Path, image_dir: Path) -> dict:
    request_file = results.parent / "ocr-request.json"
    request_file.write_text(json.dumps({
        "pages": plan["ocr_pages"], "images": plan.get("ocr_images", []),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    command = [
        str(ocr_python), str(ROOT / "scripts" / "ocr_worker.py"), "run", str(source),
        "--request", str(request_file),
        "--output", str(results), "--image-dir", str(image_dir),
    ]
    env = os.environ.copy()
    # The managed Python is a symlink into root/python; resolving it and walking
    # parents selects the shadow python/models directory. Use the runtime's
    # canonical path contract so worker, doctor, and asset manifest agree.
    runtime = ocr_runtime_paths()
    env.update({
        "PADDLE_PDX_CACHE_HOME": str(runtime["models"]),
        # Keep the compatibility alias because the worker accepts older runtimes.
        "PADDLEX_HOME": str(runtime["models"]),
        "PADDLE_PDX_MODEL_SOURCE": env.get("PADDLE_PDX_MODEL_SOURCE", "BOS"),
        "FLAGS_use_mkldnn": "0",
    })
    completed = subprocess.run(command, capture_output=True, text=True, timeout=4 * 3600, env=env)
    if completed.returncode or not results.is_file():
        detail = (completed.stderr or completed.stdout)[-2000:]
        raise RuntimeError(f"PaddleOCR 页面处理失败：{detail}")
    return json.loads(results.read_text(encoding="utf-8"))


def _insert_invisible_text(page: fitz.Page, record: dict) -> list[dict]:
    target_rect = fitz.Rect(record.get("target_rect_pdf") or page.rect)
    warnings = []
    for line in record.get("lines", []):
        box = line_pdf_rect(record, line, target_rect)
        if box.is_empty or box.width < 1 or box.height < 1:
            warnings.append({"page": record["page"], "code": "invalid_text_box", "text": line["text"][:80]})
            continue
        if not line.get("polygon_px"):
            warnings.append({"page": record["page"], "code": "missing_polygon_fallback", "text": line["text"][:80]})
        unit_width = max(fitz.get_text_length(line["text"], fontname="helv", fontsize=1), 0.1)
        font_size = max(1.0, min(36.0, box.height * 0.72, box.width * 0.95 / unit_width))
        inserted = page.insert_textbox(
            box, line["text"], fontname="helv", fontsize=font_size,
            render_mode=3, overlay=True,
        )
        if inserted < 0:
            baseline = fitz.Point(box.x0, max(box.y0 + font_size, box.y1 - 1))
            page.insert_text(baseline, line["text"], fontname="helv", fontsize=font_size, render_mode=3, overlay=True)
            warnings.append({"page": record["page"], "code": "textbox_fallback", "text": line["text"][:80]})
    return warnings


def build_searchable_pdf(source: Path, plan: dict, ocr_results: dict, destination: Path) -> list[dict]:
    original = fitz.open(source)
    output = fitz.open()
    records = {
        int(record["page"]): record
        for record in ocr_results.get("pages", []) if record.get("kind", "page") == "page"
    }
    image_records = {}
    for record in ocr_results.get("images", []):
        image_records.setdefault(int(record["page"]), []).append(record)
    warnings = []
    for page_plan in plan["pages"]:
        index = int(page_plan["page"])
        source_page = original[index - 1]
        target = output.new_page(width=source_page.rect.width, height=source_page.rect.height)
        if page_plan["route"] == "blank":
            if image_records.get(index):
                target.show_pdf_page(target.rect, original, index - 1)
                for image_record in image_records[index]:
                    warnings.extend(_insert_invisible_text(target, image_record))
            continue
        if page_plan["route"] != "ocr":
            target.show_pdf_page(target.rect, original, index - 1)
            for image_record in image_records.get(index, []):
                warnings.extend(_insert_invisible_text(target, image_record))
            continue
        record = records.get(index)
        if not record:
            output.close()
            original.close()
            raise RuntimeError(f"OCR 结果缺少第 {index} 页；拒绝静默生成空页")
        record = deskew_record_image(record, destination.parent / "ocr-deskew")
        image = Path(record["image_file"])
        if not image.is_file():
            output.close()
            original.close()
            raise RuntimeError(f"OCR 第 {index} 页渲染图缺失：{image}")
        target.insert_image(target.rect, filename=str(image), keep_proportion=False)
        warnings.extend(_insert_invisible_text(target, record))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(".tmp.pdf")
    output.save(temp, garbage=4, deflate=True)
    output.close()
    original.close()
    temp.replace(destination)
    return warnings


def _ocr_box_area_ratio(record: dict) -> float:
    page_area = max(float(record.get("image_width", 0)) * float(record.get("image_height", 0)), 1.0)
    area = 0.0
    for line in record.get("lines", []):
        x0, y0, x1, y1 = line_geometry(line).rect_px
        area += max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return min(1.0, area / page_area)


def _is_figure_dominant(page_plan: dict, record: dict) -> bool:
    line_count = int(record.get("line_count", len(record.get("lines", []))))
    box_ratio = _ocr_box_area_ratio(record)
    image_coverage = float(page_plan.get("image_coverage", 0.0))
    # Calibrated on the 2026-08-11 24-page Atlas acceptance sample: its
    # figure/sparse pages had box ratios <= 0.0717 and image coverage >= 0.7286,
    # while text-dominant pages started at 0.1778. Keep line_count as a guard
    # against treating dense OCR pages as figures when boxes happen to overlap.
    return image_coverage >= 0.72 and box_ratio < 0.08 and line_count <= 50


def _white_out_ocr_lines(page: fitz.Page, record: dict) -> None:
    target_rect = fitz.Rect(record.get("target_rect_pdf") or page.rect)
    width_scale = target_rect.width / max(float(record["image_width"]), 1.0)
    height_scale = target_rect.height / max(float(record["image_height"]), 1.0)
    # A small margin covers anti-aliased glyph pixels just outside PaddleOCR's box.
    margin_x, margin_y = 2.0 * width_scale, 2.0 * height_scale
    for line in record.get("lines", []):
        rect = line_pdf_rect(record, line, target_rect)
        box = fitz.Rect(rect.x0 - margin_x, rect.y0 - margin_y, rect.x1 + margin_x, rect.y1 + margin_y) & target_rect
        if not box.is_empty:
            page.draw_rect(box, color=None, fill=(1, 1, 1), overlay=True)


def build_translation_source(source: Path, plan: dict, ocr_results: dict, destination: Path) -> list[dict]:
    """Build a pdf2zh input without visible English pixels on OCR text regions."""
    original = fitz.open(source)
    output = fitz.open()
    records = {
        int(record["page"]): record
        for record in ocr_results.get("pages", []) if record.get("kind", "page") == "page"
    }
    warnings = []
    try:
        for page_plan in plan["pages"]:
            index = int(page_plan["page"])
            source_page = original[index - 1]
            target = output.new_page(width=source_page.rect.width, height=source_page.rect.height)
            if page_plan["route"] == "blank":
                # PyMuPDF rejects show_pdf_page() when the source page has no
                # drawable contents. The target page was already created with
                # the same dimensions, so leaving it empty preserves the page
                # contract without turning a legitimate blank into a failure.
                continue
            if page_plan["route"] != "ocr":
                target.show_pdf_page(target.rect, original, index - 1)
                continue
            record = records.get(index)
            if not record:
                raise RuntimeError(f"OCR 结果缺少第 {index} 页；拒绝静默生成翻译底稿")
            if _is_figure_dominant(page_plan, record):
                image = Path(record["image_file"])
                if not image.is_file():
                    raise RuntimeError(f"OCR 第 {index} 页渲染图缺失：{image}")
                target.insert_image(target.rect, filename=str(image), keep_proportion=False)
                _white_out_ocr_lines(target, record)
            warnings.extend(_insert_invisible_text(target, record))
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_suffix(".tmp.pdf")
        output.save(temp, garbage=4, deflate=True)
        temp.replace(destination)
    finally:
        output.close()
        original.close()
    return warnings


def process_document(
    source: Path,
    task_folder: Path,
    ocr_python: Path,
    forced_pages: list[int] | None = None,
    forced_images: list[dict] | None = None,
) -> dict:
    plan_file = task_folder / "document-plan.json"
    results_file = task_folder / "ocr-results.json"
    searchable = task_folder / "searchable-original.pdf"
    translation_source = task_folder / "translation-source.pdf"
    image_dir = task_folder / "ocr-pages"
    plan = analyze_document(source, forced_pages, forced_images)
    write_plan(plan, plan_file)
    if not plan["ocr_required"]:
        return {
            "plan": plan, "translation_source": source, "searchable": None,
            "ocr_results": None, "warnings": plan["warnings"],
        }
    results = run_worker(source, plan, ocr_python, results_file, image_dir)
    compose_warnings = build_searchable_pdf(source, plan, results, searchable)
    translation_warnings = build_translation_source(source, plan, results, translation_source)
    return {
        "plan": plan,
        "translation_source": translation_source,
        "searchable": searchable,
        "ocr_results": results_file,
        "warnings": [
            *plan["warnings"], *results["summary"].get("warnings", []),
            *compose_warnings, *translation_warnings,
        ],
    }
