#!/usr/bin/env python3
"""Generate and score the non-sensitive 24-page OCR gold set.

The fixture is generated locally rather than committed as a binary.  Its text is
synthetic and contains no user documents.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import cv2
import fitz
import numpy as np


SENTENCES = [
    "Cellular pathways respond to oxygen and nutrient signals.",
    "The study reports reproducible measurements across three cohorts.",
    "Methods include blinded review and independent quality control.",
    "Figure legends define every abbreviation before quantitative analysis.",
    "The primary endpoint was assessed at twelve weeks after enrollment.",
    "Source data remain linked to page number, section, and sample identifier.",
]


def page_text(index: int) -> str:
    sentence = SENTENCES[(index - 1) % len(SENTENCES)]
    return f"OCR VALIDATION PAGE {index:02d}. {sentence} Record {1000 + index}."


def text_image(text: str, *, degraded: bool = False, rotation: int = 0) -> np.ndarray:
    image = np.full((1650, 1275, 3), 255, dtype=np.uint8)
    words = text.split()
    lines, current = [], []
    for word in words:
        candidate = " ".join([*current, word])
        if cv2.getTextSize(candidate, cv2.FONT_HERSHEY_SIMPLEX, 1.15, 2)[0][0] > 1080:
            lines.append(" ".join(current)); current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    for row, line in enumerate(lines):
        cv2.putText(image, line, (85, 180 + row * 100), cv2.FONT_HERSHEY_SIMPLEX, 1.15, (20, 20, 20), 2, cv2.LINE_AA)
    if degraded:
        rng = np.random.default_rng(20260805 + len(text))
        image = cv2.GaussianBlur(image, (3, 3), 0.8)
        noise = rng.normal(0, 5.0, image.shape).astype(np.int16)
        image = np.clip(image.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        image = cv2.convertScaleAbs(image, alpha=0.86, beta=20)
    if rotation == 90:
        image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    elif rotation == 180:
        image = cv2.rotate(image, cv2.ROTATE_180)
    return image


def generate(destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    image_dir = destination / "images"
    image_dir.mkdir(exist_ok=True)
    pdf_path = destination / "ocr-goldset-24-pages.pdf"
    truth_path = destination / "ground-truth.json"
    document = fitz.open()
    pages = []
    for index in range(1, 25):
        text = page_text(index)
        if index <= 6:
            category, expected_route = "native_text", "text"
            page = document.new_page(width=612, height=792)
            page.insert_textbox(fitz.Rect(54, 90, 558, 300), text, fontsize=16, fontname="helv")
        else:
            category, expected_route = (
                ("clean_scan", "ocr") if index <= 12 else
                ("degraded_scan", "ocr") if index <= 18 else
                ("rotated_scan", "ocr")
            )
            rotation = 90 if category == "rotated_scan" and index % 2 else 180 if category == "rotated_scan" else 0
            image = text_image(text, degraded=category == "degraded_scan", rotation=rotation)
            image_path = image_dir / f"page-{index:02d}.png"
            cv2.imwrite(str(image_path), image)
            page = document.new_page(width=612, height=792)
            page.insert_image(page.rect, filename=str(image_path), keep_proportion=True)
        pages.append({
            "page": index,
            "category": category,
            "expected_route": expected_route,
            "text": text,
        })
    document.save(pdf_path, garbage=4, deflate=True)
    document.close()
    truth = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "synthetic non-sensitive English text",
        "pdf": str(pdf_path),
        "page_count": 24,
        "gates": {
            "route_accuracy": 1.0,
            "clean_scan_cer_max": 0.01,
            "degraded_or_rotated_cer_max": 0.05,
            "page_count_and_order": 1.0,
            "silent_empty_pages": 0,
        },
        "pages": pages,
    }
    truth_path.write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"pdf": str(pdf_path), "ground_truth": str(truth_path), "page_count": 24}


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for row, char_a in enumerate(a, start=1):
        current = [row]
        for column, char_b in enumerate(b, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (char_a != char_b),
            ))
        previous = current
    return previous[-1]


def cer(expected: str, actual: str) -> float:
    expected, actual = normalise(expected), normalise(actual)
    return edit_distance(expected, actual) / max(len(expected), 1)


def score(truth_file: Path, plan_file: Path, ocr_file: Path, searchable_pdf: Path, report_file: Path) -> dict:
    truth = json.loads(truth_file.read_text(encoding="utf-8"))
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    ocr = json.loads(ocr_file.read_text(encoding="utf-8"))
    expected = {int(page["page"]): page for page in truth["pages"]}
    planned = {int(page["page"]): page for page in plan["pages"]}
    results = {int(page["page"]): page for page in ocr["pages"]}
    route_matches = sum(
        planned.get(page, {}).get("route") == record["expected_route"]
        for page, record in expected.items()
    )
    ocr_expected = [page for page, record in expected.items() if record["expected_route"] == "ocr"]
    result_order = [int(page["page"]) for page in ocr["pages"]]
    per_page = []
    for page in ocr_expected:
        actual = " ".join(line["text"] for line in results.get(page, {}).get("lines", []))
        per_page.append({
            "page": page,
            "category": expected[page]["category"],
            "cer": cer(expected[page]["text"], actual),
            "empty": not normalise(actual),
        })
    category_cer = {}
    for category in ("clean_scan", "degraded_scan", "rotated_scan"):
        rows = [row["cer"] for row in per_page if row["category"] == category]
        category_cer[category] = sum(rows) / len(rows) if rows else None
    searchable = fitz.open(searchable_pdf)
    searchable_count = searchable.page_count
    searchable_empty = [
        page for page in ocr_expected if not normalise(searchable[page - 1].get_text("text"))
    ]
    searchable.close()
    gates = {
        "route_accuracy": route_matches / max(len(expected), 1),
        "clean_scan_cer": category_cer["clean_scan"],
        "degraded_scan_cer": category_cer["degraded_scan"],
        "rotated_scan_cer": category_cer["rotated_scan"],
        "page_count_and_order": searchable_count == truth["page_count"] and result_order == ocr_expected,
        "silent_empty_pages": sorted(set([row["page"] for row in per_page if row["empty"]] + searchable_empty)),
    }
    passed = (
        gates["route_accuracy"] == 1.0
        and gates["clean_scan_cer"] <= 0.01
        and gates["degraded_scan_cer"] <= 0.05
        and gates["rotated_scan_cer"] <= 0.05
        and gates["page_count_and_order"]
        and not gates["silent_empty_pages"]
    )
    report = {
        "schema_version": 1,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if passed else "failed",
        "gates": gates,
        "category_cer": category_cer,
        "pages": per_page,
        "inputs": {
            "ground_truth": str(truth_file), "plan": str(plan_file),
            "ocr_results": str(ocr_file), "searchable_pdf": str(searchable_pdf),
        },
    }
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="PaddleOCR gold-set acceptance")
    sub = parser.add_subparsers(dest="command", required=True)
    generate_parser = sub.add_parser("generate")
    generate_parser.add_argument("destination", type=Path)
    score_parser = sub.add_parser("score")
    score_parser.add_argument("--truth", type=Path, required=True)
    score_parser.add_argument("--plan", type=Path, required=True)
    score_parser.add_argument("--ocr-results", type=Path, required=True)
    score_parser.add_argument("--searchable", type=Path, required=True)
    score_parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "generate":
        print(json.dumps(generate(args.destination), ensure_ascii=False, indent=2))
        return
    report = score(args.truth, args.plan, args.ocr_results, args.searchable, args.report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "passed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
