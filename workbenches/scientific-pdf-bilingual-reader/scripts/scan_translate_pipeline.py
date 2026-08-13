#!/usr/bin/env python3
"""OCR-page translation pipeline: geometry repair, block layout, paragraph fill."""

from __future__ import annotations

import json
import hashlib
import copy
import math
import time
from dataclasses import dataclass
from pathlib import Path

import fitz

from page_router import FONT_CANDIDATES
from translation_broker import TranslationBroker, normalized_text


SCAN_PARAGRAPH_INSTRUCTION = (
    "把下面扫描论文段落翻译成自然、连贯、准确的中文。保留 URL、邮箱、公式符号、引用编号、"
    "专有名词和缩略语；不要添加解释。"
)


class ScanTranslationError(RuntimeError):
    def __init__(self, message: str, report: dict | None = None, report_path: Path | None = None):
        super().__init__(message)
        self.report = report or {}
        self.report_path = report_path


@dataclass
class LineGeom:
    text: str
    score: float
    polygon_px: list[list[float]] | None
    box_px: list[float]
    rect_px: list[float]
    angle_deg: float
    height_px: float
    width_px: float
    center: tuple[float, float]


def _distance(a: list[float], b: list[float]) -> float:
    return math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))


def _median(values: list[float], default: float = 0.0) -> float:
    values = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not values:
        return default
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


def valid_polygon(value: object) -> list[list[float]] | None:
    if not isinstance(value, list) or len(value) < 4:
        return None
    try:
        points = [[float(item[0]), float(item[1])] for item in value[:4]]
    except Exception:
        return None
    if len({(round(x, 2), round(y, 2)) for x, y in points}) < 4:
        return None
    return points


def polygon_angle_deg(points: list[list[float]]) -> float:
    top = (float(points[1][0]) - float(points[0][0]), float(points[1][1]) - float(points[0][1]))
    bottom = (float(points[2][0]) - float(points[3][0]), float(points[2][1]) - float(points[3][1]))
    dx = top[0] + bottom[0]
    dy = top[1] + bottom[1]
    if abs(dx) < 1e-6:
        return 0.0
    return math.degrees(math.atan2(dy, dx))


def polygon_area(points: list[list[float]]) -> float:
    total = 0.0
    for index, point in enumerate(points):
        other = points[(index + 1) % len(points)]
        total += point[0] * other[1] - other[0] * point[1]
    return abs(total) / 2.0


def line_geometry(line: dict) -> LineGeom:
    box = [float(value) for value in line["box_px"]]
    polygon = valid_polygon(line.get("polygon_px"))
    if polygon:
        width = (_distance(polygon[0], polygon[1]) + _distance(polygon[3], polygon[2])) / 2
        box_height = max(1.0, box[3] - box[1])
        height = min(polygon_area(polygon) / max(width, 1.0), box_height * 0.55)
        center_x = sum(point[0] for point in polygon) / 4
        center_y = sum(point[1] for point in polygon) / 4
        rect = [center_x - width / 2, center_y - height / 2, center_x + width / 2, center_y + height / 2]
        if rect[0] <= 1.0:
            shift = 2.0 - rect[0]
            rect[0] += shift
            rect[2] += shift
        angle = polygon_angle_deg(polygon)
    else:
        width, height = max(1.0, box[2] - box[0]), max(1.0, box[3] - box[1])
        center_x, center_y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        rect, angle = box, 0.0
    return LineGeom(
        text=str(line.get("text", "")),
        score=float(line.get("score", 0.0) or 0.0),
        polygon_px=polygon,
        box_px=box,
        rect_px=rect,
        angle_deg=angle,
        height_px=max(1.0, height),
        width_px=max(1.0, width),
        center=(center_x, center_y),
    )


def estimate_page_angle(record: dict) -> float:
    return _median([
        line_geometry(line).angle_deg for line in record.get("lines", [])
        if valid_polygon(line.get("polygon_px")) and len(str(line.get("text", "")).strip()) >= 3
    ])


def transform_point(matrix, point: list[float]) -> list[float]:
    x, y = float(point[0]), float(point[1])
    return [
        float(matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]),
        float(matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]),
    ]


def deskew_record_image(record: dict, output_dir: Path | None = None) -> dict:
    """Rotate the scan image and OCR polygons into a page-level deskew frame."""
    angle = estimate_page_angle(record)
    if abs(angle) < 0.1:
        adjusted = copy.deepcopy(record)
        adjusted["deskew"] = {"angle_deg": angle, "applied": False}
        return adjusted
    image = Path(record.get("image_file") or "")
    if not image.is_file():
        adjusted = copy.deepcopy(record)
        adjusted["deskew"] = {"angle_deg": angle, "applied": False, "warning": "image_missing"}
        return adjusted
    import cv2
    data = cv2.imread(str(image))
    if data is None:
        adjusted = copy.deepcopy(record)
        adjusted["deskew"] = {"angle_deg": angle, "applied": False, "warning": "image_unreadable"}
        return adjusted
    height, width = data.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    rotated = cv2.warpAffine(data, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    output_root = output_dir or image.parent
    output_root.mkdir(parents=True, exist_ok=True)
    out = output_root / f"page-{int(record.get('page', 0)):04d}-deskew.png"
    cv2.imwrite(str(out), rotated)
    adjusted = copy.deepcopy(record)
    adjusted["image_file"] = str(out)
    adjusted["image_width"] = width
    adjusted["image_height"] = height
    adjusted["deskew"] = {"angle_deg": angle, "applied": True, "image_file": str(out)}
    for line in adjusted.get("lines", []):
        polygon = valid_polygon(line.get("polygon_px"))
        if not polygon:
            continue
        transformed = [transform_point(matrix, point) for point in polygon]
        line["polygon_px"] = transformed
        xs = [point[0] for point in transformed]
        ys = [point[1] for point in transformed]
        line["box_px"] = [min(xs), min(ys), max(xs), max(ys)]
    return adjusted


def geometry_audit(record: dict) -> dict:
    before = []
    after = []
    x0_before = x0_after = 0
    for line in record.get("lines", []):
        geom = line_geometry(line)
        box = [float(value) for value in line["box_px"]]
        before.append(max(0.0, box[3] - box[1]))
        after.append(geom.height_px)
        if box[0] <= 1.0:
            x0_before += 1
        if geom.rect_px[0] <= 1.0:
            x0_after += 1
    return {
        "page": record.get("page"),
        "line_count": len(record.get("lines", [])),
        "deskew_angle_deg": estimate_page_angle(record),
        "x0_collapse_before": x0_before,
        "x0_collapse_after": x0_after,
        "median_height_before_px": _median(before),
        "median_height_after_px": _median(after),
    }


def line_pdf_rect(record: dict, line: dict, target_rect: fitz.Rect | None = None) -> fitz.Rect:
    target = fitz.Rect(target_rect or record.get("target_rect_pdf") or [0, 0, record["pdf_width"], record["pdf_height"]])
    width_scale = target.width / max(float(record["image_width"]), 1.0)
    height_scale = target.height / max(float(record["image_height"]), 1.0)
    x0, y0, x1, y1 = line_geometry(line).rect_px
    rect = fitz.Rect(
        target.x0 + x0 * width_scale,
        target.y0 + y0 * height_scale,
        target.x0 + x1 * width_scale,
        target.y0 + y1 * height_scale,
    )
    return rect & target


def _union_rect(rects: list[list[float]]) -> list[float]:
    return [
        min(rect[0] for rect in rects), min(rect[1] for rect in rects),
        max(rect[2] for rect in rects), max(rect[3] for rect in rects),
    ]


def _block(kind: str, lines: list[dict], order: int, page_width: float, page_height: float) -> dict:
    rects = [line_geometry(line).rect_px for line in lines]
    bbox = _union_rect(rects)
    return {
        "block_id": f"{kind}-{order}",
        "kind": kind,
        "order": order,
        "bbox_px": [round(max(0.0, bbox[0]), 2), round(max(0.0, bbox[1]), 2),
                    round(min(page_width, bbox[2]), 2), round(min(page_height, bbox[3]), 2)],
        "line_count": len(lines),
        "line_indices": [line["_index"] for line in lines],
    }


def _line_items(record: dict) -> list[dict]:
    lines = []
    for index, line in enumerate(record.get("lines", [])):
        item = dict(line)
        item["_index"] = index
        lines.append(item)
    return lines


def _sort_lines(lines: list[dict]) -> list[dict]:
    return sorted(lines, key=lambda line: (line_geometry(line).center[1], line_geometry(line).center[0]))


def _looks_like_title_line(line: dict, page_width: float, page_height: float) -> bool:
    geom = line_geometry(line)
    if geom.center[1] > page_height * 0.18:
        return False
    centered = abs(geom.center[0] - page_width / 2) <= page_width * 0.18
    wide_enough = geom.width_px >= page_width * 0.22
    return centered and wide_enough


def _split_group_blocks(kind: str, lines: list[dict], order: int, page_width: float, page_height: float) -> tuple[list[dict], int]:
    ordered = _sort_lines(lines)
    if not ordered:
        return [], order
    heights = [line_geometry(line).height_px for line in ordered]
    median_height = _median(heights, 28.0)
    gap_limit = max(42.0, median_height * 2.2)
    max_lines = 6 if kind == "title" else 18
    blocks: list[dict] = []
    current: list[dict] = []
    previous_bottom = None
    base_indent = None
    for line in ordered:
        geom = line_geometry(line)
        text = normalized_text(line.get("text", ""))
        gap = 0.0 if previous_bottom is None else geom.rect_px[1] - previous_bottom
        if base_indent is None:
            base_indent = geom.rect_px[0]
        indent_shift = abs(geom.rect_px[0] - base_indent)
        heading_like = (
            len(text) <= 90
            and (
                text[:2].rstrip(".").isdigit()
                or text[:3].rstrip(".").isdigit()
                or (geom.height_px > median_height * 1.25 and geom.width_px < page_width * 0.45)
            )
        )
        starts_new = bool(
            current
            and (
                len(current) >= max_lines
                or gap > gap_limit
                or (gap > median_height * 0.75 and indent_shift > max(32.0, median_height * 1.2))
                or (kind != "title" and heading_like and gap > median_height * 0.35)
            )
        )
        if starts_new:
            blocks.append(_block(kind, current, order, page_width, page_height))
            order += 1
            current = []
            base_indent = geom.rect_px[0]
        current.append(line)
        previous_bottom = geom.rect_px[3]
    if current:
        blocks.append(_block(kind, current, order, page_width, page_height))
        order += 1
    return blocks, order


def deterministic_layout_blocks(record: dict) -> list[dict]:
    page_width, page_height = float(record["image_width"]), float(record["image_height"])
    lines = _line_items(record)
    if not lines:
        return []
    mid = page_width / 2
    title_lines, left, right, full, footer = [], [], [], [], []
    for line in lines:
        geom = line_geometry(line)
        y = geom.center[1]
        if _looks_like_title_line(line, page_width, page_height):
            title_lines.append(line)
        elif y > page_height * 0.91:
            footer.append(line)
        elif geom.width_px > page_width * 0.72 and abs(geom.center[0] - mid) < page_width * 0.15:
            full.append(line)
        elif geom.center[0] < mid:
            left.append(line)
        else:
            right.append(line)
    order = 0
    blocks: list[dict] = []
    for kind, group in (("title", title_lines), ("paragraph", left), ("paragraph", right), ("footer", footer), ("paragraph", full)):
        if group:
            new_blocks, order = _split_group_blocks(kind, group, order, page_width, page_height)
            blocks.extend(new_blocks)
    return blocks


def _normalize_doclayout_kind(kind: str) -> str:
    lowered = kind.lower().replace("_", " ").strip()
    if "title" in lowered:
        return "title"
    if "foot" in lowered:
        return "footer"
    if any(token in lowered for token in ("text", "plain", "list", "caption", "abandon")):
        return "paragraph"
    return lowered or "paragraph"


def doclayout_blocks(record: dict) -> tuple[list[dict], dict]:
    started = time.monotonic()
    meta = {
        "model_attempted": True,
        "model_backend": "cpu",
        "model_provider": "pdf2zh.doclayout",
        "model_elapsed_seconds": 0.0,
        "model_block_count": 0,
        "model_error": None,
    }
    image_path = Path(record.get("image_file") or "")
    if not image_path.is_file():
        meta["model_error"] = "image_missing"
        return [], meta
    try:
        import cv2
        from pdf2zh.doclayout import DocLayoutModel, set_backend
        set_backend("cpu")
        image = cv2.imread(str(image_path))
        if image is None:
            meta["model_error"] = "image_unreadable"
            return [], meta
        model = DocLayoutModel.load_available()
        meta["model_path"] = getattr(model, "model_path", None)
        ort_session = getattr(model, "model", None)
        if ort_session is not None and hasattr(ort_session, "get_providers"):
            meta["model_providers"] = list(ort_session.get_providers())
        result = model.predict(image, imgsz=1024)
    except Exception as exc:
        meta["model_error"] = f"{type(exc).__name__}: {exc}"
        meta["model_elapsed_seconds"] = round(time.monotonic() - started, 3)
        return [], meta
    blocks = []
    results = result if isinstance(result, list) else [result]
    order = 0
    for item in results:
        names = getattr(item, "names", {}) if item is not None else {}
        for box in getattr(item, "boxes", []) or []:
            conf = float(getattr(box, "conf", 0.0))
            if conf < 0.25:
                continue
            cls = int(getattr(box, "cls", 0))
            kind = _normalize_doclayout_kind(str(names.get(cls, cls)))
            x0, y0, x1, y1 = [float(value) for value in getattr(box, "xyxy", [])[:4]]
            blocks.append({
                "block_id": f"doclayout-{order}",
                "kind": kind,
                "order": order,
                "bbox_px": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
                "confidence": conf,
                "line_indices": [],
            })
            order += 1
    meta["model_elapsed_seconds"] = round(time.monotonic() - started, 3)
    meta["model_block_count"] = len(blocks)
    return blocks, meta


def attach_line_indices_to_blocks(record: dict, blocks: list[dict]) -> list[dict]:
    grouped = assign_lines_to_blocks(record, blocks)
    attached = []
    for block in blocks:
        updated = dict(block)
        lines = grouped.get(block["block_id"], [])
        updated["line_indices"] = [line["_index"] for line in lines]
        updated["line_count"] = len(lines)
        attached.append(updated)
    return attached


def refine_model_blocks_with_ocr_lines(record: dict, blocks: list[dict]) -> list[dict]:
    page_width, page_height = float(record["image_width"]), float(record["image_height"])
    grouped = assign_lines_to_blocks(record, blocks)
    refined: list[dict] = []
    order = 0
    for source_block in sorted(blocks, key=lambda block: (float(block["bbox_px"][1]), float(block["bbox_px"][0]))):
        kind = source_block.get("kind", "paragraph")
        lines = grouped.get(source_block["block_id"], [])
        if kind in {"paragraph", "title", "footer"} and lines:
            split, order = _split_group_blocks(kind, lines, order, page_width, page_height)
            for child in split:
                child["source_block_id"] = source_block["block_id"]
                if "confidence" in source_block:
                    child["confidence"] = source_block["confidence"]
                refined.append(child)
            continue
        if kind in {"paragraph", "title", "footer"} and not lines:
            continue
        updated = dict(source_block)
        updated["order"] = order
        updated["line_count"] = len(lines)
        updated["line_indices"] = [line["_index"] for line in lines]
        refined.append(updated)
        order += 1
    return refined


def validate_blocks(record: dict, blocks: list[dict]) -> dict:
    page_width, page_height = float(record["image_width"]), float(record["image_height"])
    page_area = max(1.0, page_width * page_height)
    errors = []
    coverage = 0.0
    for block in blocks:
        x0, y0, x1, y1 = [float(value) for value in block["bbox_px"]]
        if x0 < -1 or y0 < -1 or x1 > page_width + 1 or y1 > page_height + 1 or x1 <= x0 or y1 <= y0:
            errors.append({
                "code": "block_out_of_bounds",
                "block_id": block.get("block_id"),
                "bbox_px": block.get("bbox_px"),
                "overflow_px": {
                    "left": round(max(0.0, -x0), 2),
                    "top": round(max(0.0, -y0), 2),
                    "right": round(max(0.0, x1 - page_width), 2),
                    "bottom": round(max(0.0, y1 - page_height), 2),
                },
            })
        width = max(0.0, x1 - x0)
        height = max(0.0, y1 - y0)
        coverage += width * height
        line_count = int(block.get("line_count") or len(block.get("line_indices") or []))
        if block.get("kind") == "title" and (line_count > 8 or (width / max(page_width, 1.0) > 0.82 and height / max(page_height, 1.0) > 0.13)):
            errors.append({
                "code": "title_block_too_large",
                "block_id": block.get("block_id"),
                "line_count": line_count,
                "width_ratio": round(width / max(page_width, 1.0), 4),
                "height_ratio": round(height / max(page_height, 1.0), 4),
            })
        if block.get("kind") == "paragraph" and line_count > 24:
            errors.append({
                "code": "paragraph_block_too_large",
                "block_id": block.get("block_id"),
                "line_count": line_count,
            })
    paragraph_blocks = [block for block in blocks if block.get("kind") == "paragraph"]
    for index, left in enumerate(paragraph_blocks):
        a = fitz.Rect(left["bbox_px"])
        for right in paragraph_blocks[index + 1:]:
            b = fitz.Rect(right["bbox_px"])
            inter = a & b
            if not inter.is_empty:
                ratio = inter.get_area() / max(1.0, min(a.get_area(), b.get_area()))
                if ratio > 0.08:
                    errors.append({
                        "code": "block_overlap",
                        "blocks": [left.get("block_id"), right.get("block_id")],
                        "ratio": round(ratio, 4),
                        "intersection_px": [round(inter.x0, 2), round(inter.y0, 2), round(inter.x1, 2), round(inter.y1, 2)],
                    })
    coverage_ratio = min(1.0, coverage / page_area)
    if coverage_ratio > 0.92:
        errors.append({"code": "block_coverage_too_high", "coverage": round(coverage_ratio, 4)})
    return {"ok": not errors, "errors": errors, "coverage": round(coverage_ratio, 4)}


def detect_layout_blocks(record: dict, *, prefer_model: bool = True) -> dict:
    model_meta = {
        "model_attempted": False,
        "model_backend": "cpu",
        "model_provider": "pdf2zh.doclayout",
        "model_elapsed_seconds": 0.0,
        "model_block_count": 0,
        "model_error": None,
    }
    blocks: list[dict] = []
    source = "deterministic_columns"
    fallback_used = not prefer_model
    fallback_reason = "model_disabled" if not prefer_model else None
    if prefer_model:
        blocks, model_meta = doclayout_blocks(record)
        if blocks:
            blocks = refine_model_blocks_with_ocr_lines(record, blocks)
            source = "doclayout_onnx_cpu"
            validation = validate_blocks(record, blocks)
            return {
                "page": record.get("page"), "source": source, "blocks": blocks,
                "validation": validation, "fallback_used": False, "fallback_reason": None,
                **model_meta,
            }
        else:
            fallback_used = True
            fallback_reason = "model_unavailable_or_empty"
    if fallback_used:
        blocks = deterministic_layout_blocks(record)
        source = "deterministic_columns"
    validation = validate_blocks(record, blocks)
    return {
        "page": record.get("page"), "source": source, "blocks": blocks,
        "validation": validation, "fallback_used": fallback_used, "fallback_reason": fallback_reason,
        **model_meta,
    }


def assign_lines_to_blocks(record: dict, blocks: list[dict]) -> dict[str, list[dict]]:
    assigned = {block["block_id"]: [] for block in blocks}
    block_rects = [(block, fitz.Rect(block["bbox_px"])) for block in blocks]
    for index, line in enumerate(record.get("lines", [])):
        geom = line_geometry(line)
        point = fitz.Point(*geom.center)
        candidates = [block for block, rect in block_rects if rect.contains(point)]
        if not candidates:
            candidates = [min(blocks, key=lambda block: abs(fitz.Rect(block["bbox_px"]).y0 - geom.center[1]))] if blocks else []
        if candidates:
            item = dict(line)
            item["_index"] = index
            assigned[candidates[0]["block_id"]].append(item)
    return assigned


def _paragraph_join(previous: str, current: str) -> str:
    if previous.endswith("-") and current[:1].islower():
        return previous[:-1] + current
    if previous.endswith("-"):
        return previous[:-1] + current
    return previous + " " + current


def aggregate_paragraphs(record: dict, blocks: list[dict]) -> list[dict]:
    grouped = assign_lines_to_blocks(record, blocks)
    paragraphs = []
    for block in sorted(blocks, key=lambda item: int(item.get("order", 0))):
        lines = sorted(grouped.get(block["block_id"], []), key=lambda line: (line_geometry(line).center[1], line_geometry(line).center[0]))
        if not lines:
            continue
        heights = [line_geometry(line).height_px for line in lines]
        gap_limit = max(10.0, _median(heights, 18.0) * 1.85)
        current_lines: list[dict] = []
        current_text = ""
        previous_bottom = None
        for line in lines:
            text = normalized_text(line.get("text", ""))
            if not text:
                continue
            geom = line_geometry(line)
            gap = 0.0 if previous_bottom is None else geom.rect_px[1] - previous_bottom
            list_like = bool(text[:2].strip() in {"-", "*"} or text[:3].rstrip(".").isdigit())
            starts_new = bool(current_text and (gap > gap_limit or list_like))
            if starts_new:
                paragraphs.append(_paragraph_record(record, block, current_lines, current_text))
                current_lines, current_text = [], ""
            current_text = text if not current_text else _paragraph_join(current_text, text)
            current_lines.append(line)
            previous_bottom = geom.rect_px[3]
        if current_text:
            paragraphs.append(_paragraph_record(record, block, current_lines, current_text))
    return paragraphs


def _paragraph_record(record: dict, block: dict, lines: list[dict], text: str) -> dict:
    rects = [line_geometry(line).rect_px for line in lines]
    return {
        "paragraph_id": f"p{record.get('page')}-{block['block_id']}-{hashlib.sha256(text.encode()).hexdigest()[:10]}",
        "page": record.get("page"),
        "block_id": block["block_id"],
        "kind": block.get("kind", "paragraph"),
        "bbox_px": [round(value, 2) for value in _union_rect(rects)],
        "line_indices": [line["_index"] for line in lines],
        "text": text,
    }


def font_path() -> Path:
    found = next((path for path in FONT_CANDIDATES if path.is_file()), None)
    if not found:
        raise RuntimeError("缺少可用中文字体")
    return found


def fitted_text_shape(page: fitz.Page, rect: fitz.Rect, text: str, *, max_size: float = 10.5):
    rect = fitz.Rect(rect)
    if rect.width < 8 or rect.height < 6:
        return None
    page.insert_font(fontname="scan-cjk", fontfile=str(font_path()))
    for size in (max_size, 10, 9, 8, 7, 6, 5, 4):
        shape = page.new_shape()
        if shape.insert_textbox(rect, text, fontname="scan-cjk", fontsize=size, color=(0, 0, 0)) >= 0:
            return shape
    return None


def fit_text(page: fitz.Page, rect: fitz.Rect, text: str, *, max_size: float = 10.5) -> bool:
    shape = fitted_text_shape(page, rect, text, max_size=max_size)
    if shape is None:
        return False
    shape.commit(overlay=True)
    return True


def px_rect_to_pdf(record: dict, rect_px: list[float]) -> fitz.Rect:
    target = fitz.Rect(0, 0, float(record["pdf_width"]), float(record["pdf_height"]))
    width_scale = target.width / max(float(record["image_width"]), 1.0)
    height_scale = target.height / max(float(record["image_height"]), 1.0)
    x0, y0, x1, y1 = [float(value) for value in rect_px]
    return fitz.Rect(x0 * width_scale, y0 * height_scale, x1 * width_scale, y1 * height_scale) & target


def _rect_px_tuple(rect: list[float]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = [float(value) for value in rect]
    return math.floor(x0), math.floor(y0), math.ceil(x1), math.ceil(y1)


def _line_ink_floor_box(line: dict) -> list[float]:
    geom = line_geometry(line).rect_px
    raw = [float(value) for value in line.get("box_px", geom)]
    return [
        min(float(geom[0]), raw[0]),
        min(float(geom[1]), raw[1]),
        max(float(geom[2]), raw[2]),
        max(float(geom[3]), raw[3]),
    ]


def _component_payload(components: list[dict]) -> dict:
    ordered = sorted(components, key=lambda item: item["area_px"], reverse=True)
    return {
        "non_text_component_count": len(ordered),
        "largest_component_area_px": ordered[0]["area_px"] if ordered else 0,
        "non_text_components": ordered[:12],
    }


def classify_scan_page_render_mode(record: dict, layout: dict) -> dict:
    figure_kinds = {"figure", "table", "chart", "image", "formula"}
    figure_blocks = [
        block for block in layout.get("blocks", [])
        if str(block.get("kind", "")).lower() in figure_kinds
    ]
    if figure_blocks:
        return {
            "mode": "overlay",
            "reason": "layout_non_text_blocks",
            "non_text_block_count": len(figure_blocks),
        }

    image_path = Path(record.get("image_file") or "")
    if not image_path.is_file():
        return {"mode": "overlay", "reason": "image_missing_for_ink_floor"}
    try:
        import cv2
        import numpy as np
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            return {"mode": "overlay", "reason": "image_unreadable_for_ink_floor"}
        height, width = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        dark = gray < 215
        saturated = (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 90)
        text_mask = np.zeros((height, width), dtype=np.uint8)
        for line in record.get("lines", []):
            x0, y0, x1, y1 = _rect_px_tuple(_line_ink_floor_box(line))
            pad_x = max(3, int((x1 - x0) * 0.06))
            pad_y = max(3, int((y1 - y0) * 0.25))
            x0 = max(0, x0 - pad_x)
            y0 = max(0, y0 - pad_y)
            x1 = min(width, x1 + pad_x)
            y1 = min(height, y1 + pad_y)
            if x1 > x0 and y1 > y0:
                text_mask[y0:y1, x0:x1] = 1
        candidate = (dark | saturated) & (text_mask == 0)
        candidate[: max(1, int(height * 0.015)), :] = False
        candidate[-max(1, int(height * 0.015)):, :] = False
        candidate[:, : max(1, int(width * 0.015))] = False
        candidate[:, -max(1, int(width * 0.015)):] = False
        candidate = cv2.morphologyEx(candidate.astype("uint8"), cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8))
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(candidate, 8)
        page_area = max(1, width * height)
        floor_area = max(900, int(page_area * 0.0015))
        floor_span = min(width, height) * 0.10
        components = []
        ignored_line_like = []
        for label in range(1, component_count):
            x, y, w, h, area = [int(value) for value in stats[label]]
            if area >= floor_area or (area >= 240 and (w >= floor_span or h >= floor_span)):
                component = {"bbox_px": [x, y, x + w, y + h], "area_px": area}
                line_like = h <= 80 and w >= max(floor_span, h * 12)
                if line_like:
                    ignored_line_like.append(component)
                else:
                    components.append(component)
        if len(ignored_line_like) >= 10:
            components.extend(ignored_line_like)
        if components:
            payload = _component_payload(components)
            if ignored_line_like:
                payload["ignored_line_like_component_count"] = len(ignored_line_like)
            return {
                "mode": "overlay",
                "reason": "non_text_ink_floor",
                "reason_detail": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                **payload,
            }
        return {
            "mode": "clean",
            "reason": "text_blocks_only_and_no_non_text_ink",
            "non_text_component_count": 0,
            "ignored_line_like_component_count": len(ignored_line_like),
        }
    except Exception as exc:
        return {"mode": "overlay", "reason": "ink_floor_error", "error": f"{type(exc).__name__}: {exc}"}


def _render_scan_page_overlay(page: fitz.Page, record: dict, paragraphs: list[dict], translations: dict[str, str]) -> dict:
    image = Path(record.get("image_file") or "")
    if not image.is_file():
        raise RuntimeError(f"扫描页图像缺失：第 {record.get('page')} 页")
    page.insert_image(page.rect, filename=str(image), keep_proportion=False)
    placed, fallbacks = 0, []
    for paragraph in paragraphs:
        if paragraph.get("kind") not in {"paragraph", "title", "footer"}:
            continue
        rect = px_rect_to_pdf(record, paragraph["bbox_px"])
        translated = translations.get(paragraph["paragraph_id"], paragraph["text"])
        shape = fitted_text_shape(page, rect, translated)
        if shape is not None:
            erase = fitz.Rect(rect.x0 - 1.5, rect.y0 - 1.0, rect.x1 + 1.5, rect.y1 + 1.0) & page.rect
            page.draw_rect(erase, color=None, fill=(1, 1, 1), overlay=True)
            shape.commit(overlay=True)
            placed += 1
        else:
            # Fail without erasing: the source image remains visible and QA
            # receives the stable paragraph id through page-plan fallbacks.
            fallbacks.append(paragraph["paragraph_id"])
    return {"placed": placed, "fallbacks": fallbacks}


def _render_scan_page_clean(page: fitz.Page, record: dict, paragraphs: list[dict], translations: dict[str, str]) -> dict:
    prepared, fallbacks = [], []
    for paragraph in paragraphs:
        if paragraph.get("kind") not in {"paragraph", "title", "footer"}:
            continue
        rect = px_rect_to_pdf(record, paragraph["bbox_px"])
        translated = translations.get(paragraph["paragraph_id"], paragraph["text"])
        max_size = 12.5 if paragraph.get("kind") == "title" else 10.5
        shape = fitted_text_shape(page, rect, translated, max_size=max_size)
        if shape is None:
            fallbacks.append(paragraph["paragraph_id"])
        else:
            prepared.append(shape)
    if fallbacks:
        return {"placed": 0, "fallbacks": fallbacks, "clean_commit": False}
    page.draw_rect(page.rect, color=None, fill=(1, 1, 1), overlay=False)
    for shape in prepared:
        shape.commit(overlay=True)
    return {"placed": len(prepared), "fallbacks": [], "clean_commit": True}


def render_scan_page(page: fitz.Page, record: dict, paragraphs: list[dict], translations: dict[str, str],
                     layout: dict | None = None) -> dict:
    decision = classify_scan_page_render_mode(record, layout or {"blocks": []})
    if decision["mode"] == "clean":
        render = _render_scan_page_clean(page, record, paragraphs, translations)
        if render.get("fallbacks"):
            classified_reason = decision.get("reason")
            render = _render_scan_page_overlay(page, record, paragraphs, translations)
            decision = {
                **decision,
                "mode": "overlay",
                "reason": "clean_fit_failed_preserve_source",
                "classified_mode": "clean",
                "classified_reason": classified_reason,
            }
    else:
        render = _render_scan_page_overlay(page, record, paragraphs, translations)
    return {**render, **decision}


def write_scan_failure_report(destination: Path, reason: str, page_reports: list[dict], started: float) -> tuple[dict, Path]:
    report = {
        "schema": "scan-translation-failure/v2",
        "reason": reason,
        "destination": str(destination),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "page_count": len(page_reports),
        "pages": page_reports,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    failure_path = destination.parent / "scan-translation-failure.json"
    failure_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report, failure_path


def build_scan_translation_pdf(source: Path, plan: dict, ocr_results: dict, destination: Path,
                               broker: TranslationBroker, *, prefer_model: bool = True) -> dict:
    original = fitz.open(source)
    output = fitz.open()
    records = {
        int(record["page"]): record
        for record in ocr_results.get("pages", []) if record.get("kind", "page") == "page"
    }
    started = time.monotonic()
    page_reports = []
    total_paragraphs = 0
    try:
        for page_plan in plan["pages"]:
            index = int(page_plan["page"])
            source_page = original[index - 1]
            out = output.new_page(width=source_page.rect.width, height=source_page.rect.height)
            if page_plan["route"] != "ocr":
                out.show_pdf_page(out.rect, original, index - 1)
                page_reports.append({"page": index, "route": page_plan["route"], "status": "copied"})
                continue
            record = records.get(index)
            if not record:
                page_reports.append({"page": index, "route": "ocr", "status": "failed", "reason": "ocr_record_missing"})
                report, failure_path = write_scan_failure_report(destination, "ocr_record_missing", page_reports, started)
                raise ScanTranslationError(f"OCR 结果缺少第 {index} 页；拒绝静默生成扫描译文；报告：{failure_path}", report, failure_path)
            page_started = time.monotonic()
            record = deskew_record_image(record, destination.parent / "scan-deskew")
            layout = detect_layout_blocks(record, prefer_model=prefer_model)
            if not layout["validation"]["ok"]:
                page_reports.append({
                    "page": index,
                    "route": "ocr",
                    "status": "layout_failed",
                    "reason": "layout_validation_failed",
                    "geometry": geometry_audit(record),
                    "layout": layout,
                    "layout_source": layout["source"],
                    "model_attempted": layout.get("model_attempted"),
                    "model_error": layout.get("model_error"),
                    "block_count": len(layout["blocks"]),
                    "paragraph_count": 0,
                    "translation_request_count": broker.metrics.get("requests", 0),
                    "elapsed_seconds": round(time.monotonic() - page_started, 3),
                })
                report, failure_path = write_scan_failure_report(destination, "layout_validation_failed", page_reports, started)
                raise ScanTranslationError(f"扫描页块几何校验失败：第 {index} 页；报告：{failure_path}", report, failure_path)
            paragraphs = aggregate_paragraphs(record, layout["blocks"])
            total_paragraphs += len(paragraphs)
            requests_before = broker.metrics.get("requests", 0)
            translated = broker.translate([item["text"] for item in paragraphs], SCAN_PARAGRAPH_INSTRUCTION)
            translations = {item["paragraph_id"]: text for item, text in zip(paragraphs, translated)}
            render = render_scan_page(out, record, paragraphs, translations, layout)
            page_reports.append({
                "page": index,
                "route": "ocr",
                "status": "translated",
                "geometry": geometry_audit(record),
                "layout": layout,
                "layout_source": layout["source"],
                "model_attempted": layout.get("model_attempted"),
                "model_error": layout.get("model_error"),
                "block_count": len(layout["blocks"]),
                "paragraph_count": len(paragraphs),
                "translation_request_count": broker.metrics.get("requests", 0) - requests_before,
                "elapsed_seconds": round(time.monotonic() - page_started, 3),
                "render": render,
                "render_mode": render.get("mode"),
                "render_reason": render.get("reason"),
                "fallbacks": list(render.get("fallbacks") or []),
            })
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_suffix(".tmp.pdf")
        output.save(temp, garbage=4, deflate=True)
        temp.replace(destination)
    finally:
        output.close()
        original.close()
    return {
        "schema": "scan-translation-report/v1",
        "destination": str(destination),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "page_count": len(page_reports),
        "paragraph_count": total_paragraphs,
        "translation_metrics": broker.metrics,
        "pages": page_reports,
    }


def merge_scan_pages(text_pdf: Path, scan_pdf: Path, plan: dict, destination: Path) -> None:
    text_doc = fitz.open(text_pdf)
    scan_doc = fitz.open(scan_pdf)
    output = fitz.open()
    try:
        for index, page_plan in enumerate(plan["pages"]):
            source = scan_doc if page_plan["route"] == "ocr" else text_doc
            output.insert_pdf(source, from_page=index, to_page=index)
        temp = destination.with_suffix(".tmp.pdf")
        output.save(temp, garbage=4, deflate=True)
        temp.replace(destination)
    finally:
        output.close()
        scan_doc.close()
        text_doc.close()


def scan_page_plan(plan: dict, report: dict | None = None) -> dict:
    report_pages = {
        int(item.get("page", 0)): item
        for item in (report or {}).get("pages", [])
        if int(item.get("page", 0)) > 0
    }
    pages = []
    for page in plan.get("pages", []):
        pdf_page = int(page["page"])
        record = report_pages.get(pdf_page, {})
        item = {
            "pdf_page": pdf_page,
            "type": "scan_ocr" if page.get("route") == "ocr" else "narrative",
            "policy": "scan_page_dual_mode" if page.get("route") == "ocr" else "standard_translation",
            "confidence": 0.9,
        }
        if page.get("route") == "ocr":
            render = record.get("render") or {}
            item.update(
                render_mode=record.get("render_mode") or render.get("mode"),
                render_reason=record.get("render_reason") or render.get("reason"),
                fallbacks=list(record.get("fallbacks") or render.get("fallbacks") or []),
                placed=int(render.get("placed") or 0),
                paragraph_count=int(record.get("paragraph_count") or 0),
            )
        pages.append(item)
    counts = {}
    for page in pages:
        counts[page["type"]] = counts.get(page["type"], 0) + 1
    return {"version": 2, "pages": pages, "qa": {"type_counts": counts}}
