#!/usr/bin/env python3
"""Download or verify the BabelDOC assets required before the first PDF run."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

REQUIRED_FONTS = (
    "SourceHanSerifCN-Regular.ttf",
    "GoNotoKurrent-Regular.ttf",
)


def download_doclayout_with_fallback() -> Path:
    from babeldoc.assets.assets import verify_file
    from babeldoc.assets.embedding_assets_metadata import DOC_LAYOUT_ONNX_MODEL_URL
    from babeldoc.assets.embedding_assets_metadata import DOCLAYOUT_YOLO_DOCSTRUCTBENCH_IMGSZ1024ONNX_SHA3_256
    from babeldoc.const import get_cache_file_path

    name = "doclayout_yolo_docstructbench_imgsz1024.onnx"
    target = get_cache_file_path(name, "models")
    digest = DOCLAYOUT_YOLO_DOCSTRUCTBENCH_IMGSZ1024ONNX_SHA3_256
    if verify_file(target, digest):
        return target
    errors = []
    order = ("modelscope", "hf-mirror", "huggingface")
    for upstream in order:
        url = DOC_LAYOUT_ONNX_MODEL_URL[upstream]
        temporary = target.with_suffix(".download")
        try:
            print(f"下载版面模型：{upstream}", flush=True)
            request = urllib.request.Request(
                url, headers={"User-Agent": "scientific-pdf-bilingual-reader-assets/1"},
            )
            hash_value = hashlib.sha3_256()
            with urllib.request.urlopen(request, timeout=180) as response, temporary.open("wb") as stream:
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
                    hash_value.update(chunk)
            if hash_value.hexdigest() != digest:
                raise ValueError("SHA3-256 校验不匹配")
            temporary.replace(target)
            return target
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            errors.append(f"{upstream}: {type(exc).__name__}")
    raise RuntimeError("版面模型下载失败（已尝试多个上游）：" + "；".join(errors))


def asset_report() -> dict:
    from babeldoc.assets.assets import DOCLAYOUT_YOLO_DOCSTRUCTBENCH_IMGSZ1024ONNX_SHA3_256
    from babeldoc.assets.assets import verify_file
    from babeldoc.assets.embedding_assets_metadata import EMBEDDING_FONT_METADATA
    from babeldoc.assets.embedding_assets_metadata import TIKTOKEN_CACHES
    from babeldoc.const import get_cache_file_path

    rows = []
    model_name = "doclayout_yolo_docstructbench_imgsz1024.onnx"
    model_path = get_cache_file_path(model_name, "models")
    rows.append({
        "kind": "models", "name": model_name, "path": str(model_path),
        "ready": bool(verify_file(model_path, DOCLAYOUT_YOLO_DOCSTRUCTBENCH_IMGSZ1024ONNX_SHA3_256)),
    })
    for name in REQUIRED_FONTS:
        path = get_cache_file_path(name, "fonts")
        rows.append({
            "kind": "fonts", "name": name, "path": str(path),
            "ready": bool(verify_file(path, EMBEDDING_FONT_METADATA[name]["sha3_256"])),
        })
    for name, digest in TIKTOKEN_CACHES.items():
        path = get_cache_file_path(name, "tiktoken")
        rows.append({
            "kind": "tiktoken", "name": name, "path": str(path),
            "ready": bool(verify_file(path, digest)),
        })
    return {
        "ready": bool(rows) and all(row["ready"] for row in rows),
        "asset_count": len(rows),
        "missing": [row["name"] for row in rows if not row["ready"]],
        "assets": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="预下载或校验 PDF 翻译模型和字体")
    parser.add_argument("--check", action="store_true", help="只校验，不联网下载")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    parser.add_argument("--summary-json", action="store_true", help="只输出机器可读摘要")
    args = parser.parse_args()

    if not args.check:
        from babeldoc.assets.assets import get_font_and_metadata
        from tiktoken import encoding_for_model

        print("正在预下载版面模型、简中字体、回退字体和 tokenizer 缓存……", flush=True)
        download_doclayout_with_fallback()
        for font in REQUIRED_FONTS:
            get_font_and_metadata(font)
        encoding_for_model("gpt-4o")

    report = asset_report()
    if args.summary_json:
        print(json.dumps({
            "ready": report["ready"],
            "asset_count": report["asset_count"],
            "missing": report["missing"],
        }, ensure_ascii=False))
    elif args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"资产校验：{'通过' if report['ready'] else '未完成'}；共 {report['asset_count']} 项")
        if report["missing"]:
            print("缺失：" + "、".join(report["missing"][:10]))
    raise SystemExit(0 if report["ready"] else 2)


if __name__ == "__main__":
    main()
