#!/usr/bin/env python3
"""Stable subprocess boundary around PaddleOCR.

The workbench invokes this file with the OCR runtime's Python.  Only JSON and
PNG/PDF paths cross the boundary, so Paddle dependencies never share an
interpreter with pdf2zh.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_FILE = ROOT / "references" / "ocr-runtime-lock.json"


def load_lock() -> dict:
    return json.loads(LOCK_FILE.read_text(encoding="utf-8"))


def pipeline_config() -> dict:
    pipeline = load_lock()["pipeline"]
    return {
        "lang": pipeline["language"],
        "ocr_version": pipeline["ocr_version"],
        "text_detection_model_name": pipeline["text_detection_model"],
        "text_recognition_model_name": pipeline["text_recognition_model"],
        "use_doc_orientation_classify": pipeline["use_doc_orientation_classify"],
        "use_doc_unwarping": pipeline["use_doc_unwarping"],
        "use_textline_orientation": pipeline["use_textline_orientation"],
    }


def create_pipeline():
    from paddleocr import PaddleOCR
    return PaddleOCR(**pipeline_config())


def model_assets_manifest_sha256() -> str | None:
    model_home = os.environ.get("PADDLE_PDX_CACHE_HOME") or os.environ.get("PADDLEX_HOME")
    assets_manifest = Path(model_home).parent / "model-assets.json" if model_home else None
    if not assets_manifest or not assets_manifest.is_file():
        return None
    return hashlib.sha256(assets_manifest.read_bytes()).hexdigest()


def result_payload(result) -> dict:
    payload = result.json
    if callable(payload):
        payload = payload()
    if isinstance(payload, str):
        payload = json.loads(payload)
    if isinstance(payload, dict) and isinstance(payload.get("res"), dict):
        payload = payload["res"]
    if not isinstance(payload, dict):
        raise RuntimeError(f"PaddleOCR 返回了不支持的结果类型：{type(payload).__name__}")
    return payload


def _normalise_box(box) -> list[float] | None:
    if box is None:
        return None
    if hasattr(box, "tolist"):
        box = box.tolist()
    if len(box) == 4 and all(isinstance(value, (int, float)) for value in box):
        return [float(value) for value in box]
    if len(box) >= 4 and all(len(point) >= 2 for point in box):
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        return [min(xs), min(ys), max(xs), max(ys)]
    return None


def extract_lines(payload: dict) -> list[dict]:
    texts = payload.get("rec_texts") or []
    scores = payload.get("rec_scores") or []
    boxes = payload.get("rec_boxes") or payload.get("rec_polys") or []
    polygons = payload.get("rec_polys") or []
    if hasattr(texts, "tolist"):
        texts = texts.tolist()
    if hasattr(scores, "tolist"):
        scores = scores.tolist()
    if hasattr(boxes, "tolist"):
        boxes = boxes.tolist()
    if hasattr(polygons, "tolist"):
        polygons = polygons.tolist()
    lines = []
    for index, text in enumerate(texts):
        clean = str(text).strip()
        if not clean:
            continue
        score = float(scores[index]) if index < len(scores) else None
        box = _normalise_box(boxes[index]) if index < len(boxes) else None
        if not box:
            continue
        polygon = polygons[index] if index < len(polygons) else None
        if hasattr(polygon, "tolist"):
            polygon = polygon.tolist()
        lines.append({
            "text": clean,
            "score": score,
            "box_px": box,
            "polygon_px": [[float(point[0]), float(point[1])] for point in polygon] if polygon is not None else None,
        })
    return lines


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_manifest(root: Path) -> dict:
    assets = []
    if root.is_dir():
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            digest = sha256_file(path)
            assets.append({
                "path": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "sha256": digest,
            })
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_root": str(root),
        "pipeline": load_lock()["pipeline"],
        "asset_count": len(assets),
        "total_bytes": sum(item["bytes"] for item in assets),
        "assets": assets,
    }


def model_cache_root() -> Path:
    configured = os.environ.get("PADDLE_PDX_CACHE_HOME") or os.environ.get("PADDLEX_HOME")
    return Path(configured or (Path.home() / ".paddlex")).expanduser()


def prefetch(manifest: Path) -> None:
    create_pipeline()
    model_root = model_cache_root()
    payload = file_manifest(model_root)
    if not payload["asset_count"]:
        raise RuntimeError(f"OCR 管线已初始化，但模型目录为空：{model_root}")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    temp = manifest.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(manifest)
    print(json.dumps({"ready": True, "asset_count": payload["asset_count"], "total_bytes": payload["total_bytes"]}))


def check_assets(manifest: Path) -> None:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    root = Path(payload["model_root"])
    failures = []
    for asset in payload.get("assets", []):
        path = root / asset["path"]
        if (
            not path.is_file()
            or path.stat().st_size != asset["bytes"]
            or sha256_file(path) != asset["sha256"]
        ):
            failures.append(asset["path"])
    if failures:
        raise SystemExit("模型资产缺失或大小改变：" + ", ".join(failures[:10]))
    print(json.dumps({"ready": bool(payload.get("asset_count")), "asset_count": payload.get("asset_count", 0)}))


def _recognize_rendered(
    pipeline,
    rendered_image: Path,
    processed_image: Path,
    base_record: dict,
    lock: dict,
) -> dict:
    import cv2

    started = time.perf_counter()
    predictions = list(pipeline.predict(str(rendered_image)))
    if not predictions:
        payload = {}
        image = rendered_image
        raw = cv2.imread(str(rendered_image))
        image_height, image_width = raw.shape[:2]
    else:
        prediction = predictions[0]
        payload = result_payload(prediction)
        image = processed_image
        try:
            processed = prediction["doc_preprocessor_res"]["output_img"]
            if not cv2.imwrite(str(image), processed):
                raise RuntimeError("cv2.imwrite returned false")
            image_height, image_width = processed.shape[:2]
        except Exception:
            image = rendered_image
            raw = cv2.imread(str(rendered_image))
            image_height, image_width = raw.shape[:2]
    lines = extract_lines(payload)
    scores = [line["score"] for line in lines if line["score"] is not None]
    mean_score = sum(scores) / len(scores) if scores else None
    warnings = []
    if not lines:
        warnings.append("no_text_detected")
    if mean_score is not None and mean_score < 0.90:
        warnings.append("low_mean_confidence")
    if scores and min(scores) < 0.75:
        warnings.append("low_line_confidence")
    return {
        **base_record,
        "image_file": str(image),
        "rendered_image_file": str(rendered_image),
        "image_width": image_width,
        "image_height": image_height,
        "preprocessing": {
            "document_orientation_angle": (payload.get("doc_preprocessor_res") or {}).get("angle"),
            "document_orientation_enabled": lock["pipeline"]["use_doc_orientation_classify"],
            "document_unwarping_enabled": lock["pipeline"]["use_doc_unwarping"],
            "textline_orientation_enabled": lock["pipeline"]["use_textline_orientation"],
        },
        "line_count": len(lines),
        "mean_score": mean_score,
        "min_score": min(scores) if scores else None,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "warnings": warnings,
        "lines": lines,
    }


def run_ocr(source: Path, request: dict, output: Path, image_dir: Path) -> None:
    import fitz

    pipeline = create_pipeline()
    lock = load_lock()
    dpi = int(lock["pipeline"]["render_dpi"])
    zoom = dpi / 72.0
    image_dir.mkdir(parents=True, exist_ok=True)
    document = fitz.open(source)
    page_records, image_records = [], []
    for page_number in sorted(set(int(page) for page in request.get("pages", []))):
        if page_number < 1 or page_number > document.page_count:
            raise ValueError(f"OCR 页码越界：{page_number}")
        page = document[page_number - 1]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, colorspace=fitz.csRGB)
        rendered = image_dir / f"page-{page_number:04d}-render.png"
        pixmap.save(rendered)
        page_records.append(_recognize_rendered(
            pipeline, rendered, image_dir / f"page-{page_number:04d}-processed.png",
            {
                "kind": "page", "page": page_number,
                "pdf_width": page.rect.width, "pdf_height": page.rect.height,
                "render_dpi": dpi, "rotation_metadata": page.rotation,
            },
            lock,
        ))
    for item in request.get("images", []):
        page_number, image_index = int(item["page"]), int(item["image"])
        if page_number < 1 or page_number > document.page_count:
            raise ValueError(f"图片 OCR 页码越界：{page_number}")
        page = document[page_number - 1]
        rect = fitz.Rect(item["rect_pdf"]) & page.rect
        if rect.is_empty:
            raise ValueError(f"第 {page_number} 页图片 #{image_index} 的范围无效")
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False, colorspace=fitz.csRGB)
        rendered = image_dir / f"page-{page_number:04d}-image-{image_index:02d}-render.png"
        pixmap.save(rendered)
        image_records.append(_recognize_rendered(
            pipeline, rendered, image_dir / f"page-{page_number:04d}-image-{image_index:02d}-processed.png",
            {
                "kind": "image", "page": page_number, "image": image_index,
                "xref": item.get("xref"), "target_rect_pdf": list(rect),
                "pdf_width": rect.width, "pdf_height": rect.height,
                "render_dpi": dpi, "rotation_metadata": page.rotation,
            },
            lock,
        ))
    document.close()
    all_warnings = [
        {
            "page": record["page"], "code": code,
            **({"image": record["image"]} if record.get("kind") == "image" else {}),
        }
        for record in [*page_records, *image_records] for code in record["warnings"]
    ]
    result = {
        "schema_version": 1,
        "engine": "PaddleOCR",
        "runtime_lock_sha256": hashlib.sha256(LOCK_FILE.read_bytes()).hexdigest(),
        "model_assets_manifest_sha256": model_assets_manifest_sha256(),
        "pipeline": lock["pipeline"],
        "source": str(source),
        "pages": page_records,
        "images": image_records,
        "summary": {
            "requested_pages": request.get("pages", []),
            "requested_images": [{"page": item["page"], "image": item["image"]} for item in request.get("images", [])],
            "processed_pages": len(page_records),
            "processed_images": len(image_records),
            "text_lines": sum(record["line_count"] for record in [*page_records, *image_records]),
            "warnings": all_warnings,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(output)
    print(json.dumps(result["summary"], ensure_ascii=False))


def parse_pages(value: str) -> list[int]:
    pages = []
    for token in value.split(","):
        token = token.strip()
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
    return sorted(set(pages))


def main() -> None:
    parser = argparse.ArgumentParser(description="PaddleOCR JSON worker")
    sub = parser.add_subparsers(dest="command", required=True)
    prefetch_parser = sub.add_parser("prefetch")
    prefetch_parser.add_argument("--manifest", type=Path, required=True)
    check_parser = sub.add_parser("check-assets")
    check_parser.add_argument("--manifest", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("source", type=Path)
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--image-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prefetch":
        prefetch(args.manifest)
    elif args.command == "check-assets":
        check_assets(args.manifest)
    else:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        if not request.get("pages") and not request.get("images"):
            raise SystemExit("至少需要一个 OCR 页面或图片")
        run_ocr(args.source, request, args.output, args.image_dir)


if __name__ == "__main__":
    main()
