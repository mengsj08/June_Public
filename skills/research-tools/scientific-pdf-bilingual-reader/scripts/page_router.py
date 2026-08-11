#!/usr/bin/env python3
"""Classify PDF pages and apply conservative, region-aware fallbacks.

Run with the same Python environment as pdf2zh; it requires PyMuPDF.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from collections import Counter
from pathlib import Path

import fitz

STRUCTURED_TOC = (
    "TABLE OF CONTENTS", "LIST OF TABLES", "LIST OF FIGURES", "LIST OF ANNEXES"
)
ACRONYM_MARKERS = (
    "ACRONYMS AND ABBREVIATIONS", "ABBREVIATIONS AND ACRONYMS",
    "OTHER ABBREVIATIONS AND ACRONYMS",
)
FONT_CANDIDATES = (
    Path("~/.cache/babeldoc/fonts/SourceHanSerifCN-Regular.ttf").expanduser(),
    Path("/System/Library/Fonts/PingFang.ttc"),
)
TITLE_MAP = {
    "TABLE OF CONTENTS": "目录",
    "LIST OF TABLES": "表格目录",
    "LIST OF FIGURES": "图表目录",
    "LIST OF ANNEXES": "附件目录",
}


def page_metrics(page: fitz.Page) -> dict:
    text = page.get_text("text")
    drawings = page.get_drawings()
    drawing_items = sum(len(item.get("items", [])) for item in drawings)
    words = page.get_text("words")
    table_rows = table_cols = table_text_cells = 0
    try:
        tables = page.find_tables(strategy="lines_strict").tables
        if tables:
            table = max(tables, key=lambda candidate: fitz.Rect(candidate.bbox).get_area())
            table_rows, table_cols = table.row_count, table.col_count
            table_text_cells = sum(1 for row in table.extract() for value in row if value and re.search(r"[A-Za-z]{3,}", value))
    except Exception:
        pass
    return {
        "chars": len(text),
        "words": len(words),
        "drawings": len(drawings),
        "drawing_items": drawing_items,
        "text": text,
        "table_rows": table_rows,
        "table_cols": table_cols,
        "table_text_cells": table_text_cells,
    }


def meaningful_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [line for line in lines if not (
        re.fullmatch(r"\d+", line) or
        (line == line.lower() and re.fullmatch(r"[ivxlcdm]+", line))
    )]


def navigation_score(text: str) -> int:
    return len(re.findall(r"\.{3,}\s*\d+\s*$", text, re.M))


def is_term_code(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 32:
        return False
    if line.lower() in {"t, mt", "f"}:
        return True
    return bool(re.fullmatch(r"[A-Z0-9%][A-Z0-9%_\-/,.= ]{0,18}", line))


def term_pair_score(text: str) -> int:
    lines = meaningful_lines(text)
    return sum(1 for i, line in enumerate(lines[:-1]) if is_term_code(line) and not is_term_code(lines[i + 1]))


def classify(metrics: list[dict]) -> list[dict]:
    plan = []
    previous_dense = False
    for index, item in enumerate(metrics):
        lines = meaningful_lines(item["text"])
        heading = " ".join(lines[:2]).upper()
        nav_score = navigation_score(item["text"])
        pairs = term_pair_score(item["text"])
        if any(marker in heading for marker in STRUCTURED_TOC) or (
            index > 0 and plan[-1]["type"] == "navigation" and nav_score >= 2
        ):
            kind, policy, confidence = "navigation", "structured_reflow", 0.99
        elif any(marker in heading for marker in ACRONYM_MARKERS) or (
            index > 0 and plan[-1]["type"] == "acronym" and pairs >= 2
        ):
            kind, policy, confidence = "acronym", "term_rows", 0.97
        elif (
            item["drawing_items"] >= 20 and 2 <= item["table_cols"] <= 8
            and 2 <= item["table_rows"] <= 30 and item["table_text_cells"] >= 2
        ):
            kind, policy, confidence = "cell_table", "translate_table_cells", 0.96
        elif item["drawing_items"] >= 35 and item["chars"] >= 1800:
            kind, policy, confidence = "dense_table", "protect_table_translate_caption", 0.98
        elif previous_dense and item["chars"] < 80:
            kind, policy, confidence = "dense_table_continuation", "preserve_original", 0.92
        else:
            kind, policy, confidence = "narrative", "standard_translation", 0.75
        previous_dense = kind.startswith("dense_table")
        plan.append({
            "pdf_page": index + 1,
            "type": kind,
            "policy": policy,
            "confidence": confidence,
            "chars": item["chars"],
            "drawing_items": item["drawing_items"],
            "table_rows": item["table_rows"],
            "table_cols": item["table_cols"],
            "table_text_cells": item["table_text_cells"],
        })
    return plan


def table_region(page: fitz.Page) -> fitz.Rect | None:
    rects = [drawing.get("rect") for drawing in page.get_drawings()]
    rects = [rect for rect in rects if rect and rect.width > 20]
    if not rects:
        return None
    region = fitz.Rect(rects[0])
    for rect in rects[1:]:
        region |= rect
    region.x0 = max(0, region.x0 - 2)
    region.y0 = max(0, region.y0 - 2)
    region.x1 = min(page.rect.width, region.x1 + 2)
    region.y1 = min(page.rect.height, region.y1 + 2)
    return region


def navigation_title(text: str) -> str | None:
    upper = text.upper()
    return next((title for title in STRUCTURED_TOC if title in upper), None)


def extract_sequential_navigation(raw: list[str]) -> list[dict]:
    """Parse TOCs whose code, wrapped title, dot leader, and page are separate objects.

    Some older PDFs encode a visual row as four or five unrelated text lines, for
    example ``[93-04]`` + two title lines + a line of dots + ``1``.  The regular
    parser intentionally remains the primary path; this parser is only selected
    when the primary path collapses a page that contains several such signals.
    """
    items: list[dict] = []
    number = ""
    parts: list[str] = []

    def flush(page_number: str = "") -> None:
        nonlocal number, parts
        source = " ".join(" ".join(parts).split())
        source = re.sub(r"\.{2,}\s*$", "", source).strip()
        if source:
            items.append({
                "number": number,
                "source": source,
                "page": page_number,
                "depth": number.count(".") if number else 0,
            })
        number, parts = "", []

    for line in raw:
        line = " ".join(line.split())
        if not line:
            continue
        upper = line.upper()
        if upper == "SPECIES:" or upper.startswith("COMPENDIUM OF ") or upper == "RECOMMENDATIONS AND RESOLUTIONS":
            continue
        code = re.match(r"^(\[[^\]]+\])\s*(.*)$", line)
        if code:
            flush()
            number = code.group(1)
            if code.group(2):
                parts.append(code.group(2))
            continue
        if re.fullmatch(r"\d{1,4}", line):
            if parts:
                flush(line)
            else:
                number = line
            continue
        direct = re.search(r"\.{2,}\s*(\d{1,4})\s*$", line)
        if direct:
            body = re.sub(r"\.{2,}\s*\d{1,4}\s*$", "", line).strip()
            if body:
                parts.append(body)
            flush(direct.group(1))
            continue
        parts.append(re.sub(r"\.{2,}\s*$", "", line).strip())
    flush()
    return items


def extract_navigation(page: fitz.Page, inherited_title: str | None) -> tuple[str, list[dict]]:
    raw = [line.strip() for line in page.get_text("text").splitlines() if line.strip()]
    raw = [line for line in raw if not re.fullmatch(r"[ivxlcdm]+", line, re.I)]
    title = navigation_title("\n".join(raw)) or inherited_title or "TABLE OF CONTENTS"
    raw = [line for line in raw if not any(marker in line.upper() for marker in STRUCTURED_TOC)]
    if title == "LIST OF ANNEXES":
        combined = " ".join(raw)
        matches = list(re.finditer(r"\bANNEX\s+(\d+[a-z]?)\s+", combined, re.I))
        annexes = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(combined)
            description = combined[match.end():end].strip()
            annexes.append({"number": f"附件 {match.group(1)}", "source": description, "page": "", "depth": 0})
        if annexes:
            return title, annexes
    items: list[dict] = []
    pending_number = ""
    buffer = ""
    for line in raw:
        if re.fullmatch(r"\d+(?:\.\d+)*", line):
            pending_number = line
            continue
        if buffer:
            line = buffer + " " + line
            buffer = ""
        target = re.search(r"\.{2,}\s*(\d+)\s*$", line)
        if not target:
            buffer = line
            continue
        page_number = target.group(1)
        body = re.sub(r"\.{2,}\s*\d+\s*$", "", line).strip()
        body = re.sub(r"\s+\d+\s*$", "", body).strip()
        direct = re.match(r"^(\d+(?:\.\d+)*)\s+(.+)$", body)
        number = pending_number
        if direct:
            number, body = direct.group(1), direct.group(2)
        pending_number = ""
        if body:
            depth = number.count(".") if number else 0
            items.append({"number": number, "source": body, "page": page_number, "depth": depth})
    if buffer:
        items.append({"number": pending_number, "source": buffer, "page": "", "depth": pending_number.count(".")})
    separated_pages = sum(bool(re.fullmatch(r"\d{1,4}", line)) for line in raw)
    bracket_codes = sum(bool(re.match(r"^\[[^\]]+\]", line)) for line in raw)
    if len(items) <= 2 and max(separated_pages, bracket_codes) >= 3:
        sequential = extract_sequential_navigation(raw)
        if len(sequential) > len(items):
            items = sequential
    return title, items


def translate_strings(sources: list[str], instruction: str) -> list[str]:
    if not sources:
        return []
    base = os.environ.get("OPENAILIKED_BASE_URL")
    model = os.environ.get("OPENAILIKED_MODEL", "codex")
    key = os.environ.get("OPENAILIKED_API_KEY", "local")
    if not base:
        raise RuntimeError("结构化翻译缺少 OPENAILIKED_BASE_URL")
    prompt = instruction + "只返回与输入等长的 JSON 字符串数组。\n" + json.dumps(sources, ensure_ascii=False)
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}).encode()
    request = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        payload = json.loads(response.read())
    content = payload["choices"][0]["message"]["content"].strip()
    match = re.search(r"\[[\s\S]*\]", content)
    translated = json.loads(match.group(0) if match else content)
    if len(translated) != len(sources):
        raise RuntimeError(f"结构化翻译条数不一致：{len(sources)} -> {len(translated)}")
    return [str(text).strip() for text in translated]


def translate_titles(items: list[dict]) -> list[str]:
    if not items:
        return []
    sources = [item["source"] for item in items]
    return translate_strings(sources, (
        "把下面目录标题逐条翻译成简洁准确的中文。保留缩略语、编号、年份、拉丁学名和专有名词；"
        "不要添加解释。"
    ))


def wrap_text(text: str, font: fitz.Font, size: float, width: float) -> list[str]:
    lines, current = [], ""
    for char in text:
        trial = current + char
        if current and font.text_length(trial, fontsize=size) > width:
            lines.append(current.rstrip())
            current = char.lstrip()
        else:
            current = trial
    if current:
        lines.append(current.rstrip())
    return lines or [""]


def render_navigation(out: fitz.Page, source_page: fitz.Page, title: str, items: list[dict], translations: list[str]) -> None:
    font_path = next((path for path in FONT_CANDIDATES if path.is_file()), None)
    if not font_path:
        raise RuntimeError("缺少可用中文字体")
    font = fitz.Font(fontfile=str(font_path))
    font_name = "sourcehan"
    out.insert_font(fontname=font_name, fontfile=str(font_path))
    width, height = out.rect.width, out.rect.height
    left, right, top, bottom = 72.0, 72.0, 72.0, 46.0
    heading = TITLE_MAP.get(title, "目录")
    out.insert_text((left, top), heading, fontname=font_name, fontsize=16, color=(0, 0, 0))
    available = width - left - right
    chosen = 9.0
    prepared = []
    for size in (9.0, 8.5, 8.0, 7.5, 7.0):
        candidate, line_count = [], 0
        for item, translated in zip(items, translations):
            indent = min(item["depth"], 4) * 14
            number_width = 38 if item["number"] else 0
            title_width = available - indent - number_width - 35
            lines = wrap_text(translated, font, size, title_width)
            candidate.append((item, translated, lines, indent, number_width))
            line_count += len(lines)
        needed = line_count * size * 1.45 + len(candidate) * 2
        prepared, chosen = candidate, size
        if top + 25 + needed < height - bottom:
            break
    y = top + 30
    line_height = chosen * 1.45
    for item, _translated, lines, indent, number_width in prepared:
        x = left + indent
        if item["number"]:
            out.insert_text((x, y), item["number"], fontname=font_name, fontsize=chosen)
        text_x = x + number_width
        for line_index, line in enumerate(lines):
            out.insert_text((text_x, y), line, fontname=font_name, fontsize=chosen)
            if line_index == len(lines) - 1 and item["page"]:
                page_width = font.text_length(item["page"], fontsize=chosen)
                page_x = width - right - page_width
                text_end = text_x + font.text_length(line, fontsize=chosen)
                dot_width = font.text_length("·", fontsize=chosen)
                dots = max(0, int((page_x - text_end - 7) / max(dot_width, 1)))
                if dots:
                    out.insert_text((text_end + 4, y), "·" * dots, fontname=font_name, fontsize=chosen, color=(.35, .35, .35))
                out.insert_text((page_x, y), item["page"], fontname=font_name, fontsize=chosen)
            y += line_height
        y += 2
    footer = source_page.get_text("text").splitlines()
    label = next((line.strip() for line in footer if line.strip() == line.strip().lower() and re.fullmatch(r"[ivxlcdm]+", line.strip())), "")
    if label:
        label_width = font.text_length(label, fontsize=9)
        out.insert_text(((width - label_width) / 2, height - 28), label, fontname=font_name, fontsize=9)


def extract_terms(page: fitz.Page) -> tuple[str, list[dict]]:
    lines = meaningful_lines(page.get_text("text"))
    title = "缩略语与术语"
    lines = [line for line in lines if not any(marker in line.upper() for marker in ACRONYM_MARKERS)]
    if any(line.upper() == "FAO CODE" for line in lines):
        for header in ("FAO Code", "Common English Name", "Scientific Name"):
            lines = [line for line in lines if line.lower() != header.lower()]
        rows, index, category = [], 0, ""
        while index < len(lines):
            line = lines[index]
            if (
                line.isupper() and len(line) >= 5 and index + 2 < len(lines)
                and is_term_code(lines[index + 1]) and not is_term_code(lines[index + 2])
            ):
                category = line.title(); index += 1; continue
            if is_term_code(line) and index + 1 < len(lines):
                code = line; meaning = lines[index + 1]
                scientific = lines[index + 2] if index + 2 < len(lines) else ""
                rows.append({"code": code, "source": meaning, "scientific": scientific, "category": category})
                index += 3
            else:
                index += 1
        return title, rows
    rows, index = [], 0
    while index < len(lines):
        if not is_term_code(lines[index]):
            index += 1; continue
        code = lines[index]; index += 1; parts = []
        while index < len(lines) and not is_term_code(lines[index]):
            parts.append(lines[index]); index += 1
        if parts:
            rows.append({"code": code, "source": " ".join(parts), "scientific": "", "category": ""})
    return title, rows


def render_terms(out: fitz.Page, source_page: fitz.Page, title: str, rows: list[dict], translations: list[str]) -> None:
    font_path = next((path for path in FONT_CANDIDATES if path.is_file()), None)
    if not font_path:
        raise RuntimeError("缺少可用中文字体")
    font = fitz.Font(fontfile=str(font_path)); font_name = "sourcehan"
    out.insert_font(fontname=font_name, fontfile=str(font_path))
    width, height = out.rect.width, out.rect.height
    left, right, top = 60.0, 60.0, 68.0
    out.insert_text((left, top), title, fontname=font_name, fontsize=16)
    has_scientific = any(row["scientific"] for row in rows)
    code_width = 78.0
    meaning_width = 210.0 if has_scientific else width - left - right - code_width
    scientific_x = left + code_width + meaning_width + 12
    chosen, prepared = 9.0, []
    for size in (9.0, 8.5, 8.0, 7.5, 7.0):
        candidate, total_lines = [], 0
        last_category = None
        for row, translated in zip(rows, translations):
            meaning_lines = wrap_text(translated, font, size, meaning_width - 8)
            scientific_lines = wrap_text(row["scientific"], font, size, width - right - scientific_x) if row["scientific"] else [""]
            lines = max(len(meaning_lines), len(scientific_lines), 1)
            category_gap = 1 if row["category"] and row["category"] != last_category else 0
            candidate.append((row, meaning_lines, scientific_lines, category_gap))
            total_lines += lines + category_gap
            last_category = row["category"] or last_category
        prepared, chosen = candidate, size
        if top + 32 + total_lines * size * 1.45 + len(rows) * 2 < height - 42:
            break
    y, line_height, last_category = top + 32, chosen * 1.45, None
    for row, meaning_lines, scientific_lines, category_gap in prepared:
        if category_gap:
            out.insert_text((left, y), row["category"], fontname=font_name, fontsize=chosen, color=(.25, .25, .25))
            y += line_height
            last_category = row["category"]
        out.insert_text((left, y), row["code"], fontname=font_name, fontsize=chosen)
        count = max(len(meaning_lines), len(scientific_lines))
        for offset in range(count):
            if offset < len(meaning_lines):
                out.insert_text((left + code_width, y + offset * line_height), meaning_lines[offset], fontname=font_name, fontsize=chosen)
            if has_scientific and offset < len(scientific_lines):
                out.insert_text((scientific_x, y + offset * line_height), scientific_lines[offset], fontname=font_name, fontsize=chosen)
        y += count * line_height + 2
    footer = source_page.get_text("text").splitlines()
    label = next((line.strip() for line in footer if line.strip() == line.strip().lower() and re.fullmatch(r"[ivxlcdm]+", line.strip())), "")
    if label:
        label_width = font.text_length(label, fontsize=9)
        out.insert_text(((width - label_width) / 2, height - 28), label, fontname=font_name, fontsize=9)


def cell_needs_translation(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]{3,}", text))


def eligible_cell_tables(page: fitz.Page) -> list:
    try:
        tables = page.find_tables(strategy="lines_strict").tables
    except Exception:
        return []
    return [
        table for table in tables
        if 2 <= table.col_count <= 8 and 2 <= table.row_count <= 30
        and sum(1 for row in table.extract() for value in row if value and cell_needs_translation(value)) >= 2
    ]


def horizontal_overlap_ratio(a: fitz.Rect, b: fitz.Rect) -> float:
    overlap = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    return overlap / max(1.0, min(a.width, b.width))


def table_companion_candidates(page: fitz.Page, tables: list) -> list[dict]:
    """Collect nearby text; semantic membership is decided by the AI."""
    drawings = page.get_drawings()
    blocks = [
        {"rect": fitz.Rect(block[:4]), "text": block[4].strip()}
        for block in page.get_text("blocks")
        if block[4].strip() and block[6] == 0
    ]
    candidates, seen = [], set()
    for table_index, table in enumerate(tables):
        table_rect = fitz.Rect(table.bbox)
        for block in blocks:
            rect, text = block["rect"], block["text"]
            if rect.intersects(table_rect) or horizontal_overlap_ratio(rect, table_rect) < .35:
                continue
            if rect.y1 <= table_rect.y0:
                position, distance = "above", table_rect.y0 - rect.y1
                if distance > 72:
                    continue
            elif rect.y0 >= table_rect.y1:
                position, distance = "below", rect.y0 - table_rect.y1
                if distance > 150:
                    continue
            else:
                continue
            if re.fullmatch(r"(?:Page\s+)?\d+(?:\s+of\s+\d+)?", text, re.I):
                continue
            key = tuple(round(value, 2) for value in rect) + (text,)
            if key in seen:
                continue
            seen.add(key)
            underlined = any(
                drawing.get("rect") and drawing["rect"].width > rect.width * .45
                and drawing["rect"].height <= 2.5
                and rect.x0 - 3 <= drawing["rect"].x0 <= rect.x1 + 3
                and rect.y0 <= drawing["rect"].y0 <= rect.y1 + 3
                for drawing in drawings
            )
            candidates.append({
                "id": len(candidates), "table_index": table_index, "position": position,
                "distance": round(distance, 1), "bbox": list(rect), "text": text,
                "underlined": underlined,
            })
    return candidates


def classify_table_companions(candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []
    compact = [
        {key: item[key] for key in ("id", "table_index", "position", "distance", "text")}
        for item in candidates
    ]
    instruction = (
        "判断每段候选文字是否属于相邻表格。role 只能是 table_title、table_note、"
        "source_note、continuation_marker、unrelated_body。属于表格时给出简洁准确中文 translation；"
        "保留编号、金额、法规编号、缩略语、星号和专名。无关正文 translation 置空。"
        "只返回与输入等长、顺序和 id 不变的 JSON 对象数组，每项包含 id、role、translation。\n"
    )
    base = os.environ.get("OPENAILIKED_BASE_URL")
    model = os.environ.get("OPENAILIKED_MODEL", "codex")
    key = os.environ.get("OPENAILIKED_API_KEY", "local")
    if not base:
        raise RuntimeError("表格结构判断缺少 OPENAILIKED_BASE_URL")
    prompt = instruction + json.dumps(compact, ensure_ascii=False)
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}).encode()
    request = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        payload = json.loads(response.read())
    content = payload["choices"][0]["message"]["content"].strip()
    match = re.search(r"\[[\s\S]*\]", content)
    decisions = json.loads(match.group(0) if match else content)
    if len(decisions) != len(candidates):
        raise RuntimeError("表格关联文本判断条数不一致")
    allowed = {"table_title", "table_note", "source_note", "continuation_marker", "unrelated_body"}
    normalized = []
    for candidate, decision in zip(candidates, decisions):
        role = str(decision.get("role", "unrelated_body"))
        if decision.get("id") != candidate["id"] or role not in allowed:
            role = "unrelated_body"
        normalized.append({**candidate, "role": role, "translation": str(decision.get("translation", "")).strip()})
    return normalized


def place_companion_text(page: fitz.Page, rect: fitz.Rect, text: str, role: str) -> bool:
    font_path = next((path for path in FONT_CANDIDATES if path.is_file()), None)
    if not font_path:
        raise RuntimeError("缺少可用中文字体")
    align = fitz.TEXT_ALIGN_CENTER if role in {"table_title", "continuation_marker"} else fitz.TEXT_ALIGN_LEFT
    start = 10 if role == "table_title" else 7.5
    sizes = [start - step * .5 for step in range(int((start - 5) / .5) + 1)]
    for size in sizes:
        if page.insert_textbox(
            rect, text, fontname="sourcehan", fontfile=str(font_path), fontsize=size,
            lineheight=1.12, align=align, color=(0, 0, 0), overlay=True,
        ) >= 0:
            return True
    return False


def place_cell_text(page: fitz.Page, rect: fitz.Rect, text: str, header: bool) -> bool:
    font_path = next((path for path in FONT_CANDIDATES if path.is_file()), None)
    if not font_path:
        raise RuntimeError("缺少可用中文字体")
    inner = fitz.Rect(rect.x0 + 1.4, rect.y0 + 1.2, rect.x1 - 1.4, rect.y1 - 1.2)
    rotate = 90 if inner.height > inner.width * 3 and len(text) < 30 else 0
    align = fitz.TEXT_ALIGN_CENTER if header else fitz.TEXT_ALIGN_LEFT
    for size in (8, 7.5, 7, 6.5, 6, 5.5, 5):
        remaining = page.insert_textbox(
            inner, text, fontname="sourcehan", fontfile=str(font_path), fontsize=size,
            lineheight=1.15, align=align, rotate=rotate, color=(0, 0, 0), overlay=True,
        )
        if remaining >= 0:
            return True
    return False


def render_cell_tables(out: fitz.Page, source_page: fitz.Page, original: fitz.Document, page_no: int) -> dict:
    tables = eligible_cell_tables(source_page)
    companions = classify_table_companions(table_companion_candidates(source_page, tables))
    targets = []
    seen = set()
    for table_index, table in enumerate(tables):
        out.draw_rect(fitz.Rect(table.bbox), color=None, fill=(1, 1, 1), overlay=True)
        out.show_pdf_page(fitz.Rect(table.bbox), original, page_no, clip=fitz.Rect(table.bbox), overlay=True)
        for row_index, (values, row) in enumerate(zip(table.extract(), table.rows)):
            for value, cell in zip(values, row.cells):
                text = (value or "").strip()
                if not cell or not text or not cell_needs_translation(text):
                    continue
                rect = fitz.Rect(cell); key = tuple(round(number, 2) for number in rect) + (text,)
                if key in seen:
                    continue
                seen.add(key); targets.append((table_index, row_index, rect, text))
    translations = translate_strings(
        [target[3] for target in targets],
        "逐条翻译下面表格单元格。必须原样保留金额、数字、编号、字母等级、星号、单位和范围；译文简洁，适合放回原单元格。",
    )
    translated_count, fallback = 0, []
    for (_table_index, row_index, rect, source), translated in zip(targets, translations):
        inner = fitz.Rect(rect.x0 + .7, rect.y0 + .7, rect.x1 - .7, rect.y1 - .7)
        out.draw_rect(inner, color=None, fill=(1, 1, 1), overlay=True)
        if place_cell_text(out, rect, translated, header=row_index < 2):
            translated_count += 1
        else:
            out.show_pdf_page(rect, original, page_no, clip=rect, overlay=True)
            fallback.append(source)
    translated_companions, companion_fallback = 0, []
    for item in companions:
        if item["role"] == "unrelated_body" or not item["translation"]:
            continue
        rect = fitz.Rect(item["bbox"])
        out.draw_rect(rect, color=None, fill=(1, 1, 1), overlay=True)
        if place_companion_text(out, rect, item["translation"], item["role"]):
            translated_companions += 1
            if item.get("underlined"):
                out.draw_line((rect.x0, rect.y1 - 1.5), (rect.x1, rect.y1 - 1.5), color=(0, 0, 0), width=.8, overlay=True)
        else:
            out.show_pdf_page(rect, original, page_no, clip=rect, overlay=True)
            companion_fallback.append(item["text"])
    return {
        "tables": len(tables), "translated_cells": translated_count,
        "fallback_cells": len(fallback), "companion_candidates": len(companions),
        "translated_companions": translated_companions,
        "companion_fallbacks": len(companion_fallback),
        "companion_roles": dict(Counter(item["role"] for item in companions)),
    }


def compose(original_path: Path, translated_path: Path, output_path: Path, plan: list[dict]) -> None:
    original = fitz.open(original_path)
    translated = fitz.open(translated_path)
    if len(original) != len(translated):
        raise ValueError(f"页数不一致：原文 {len(original)}，译文 {len(translated)}")
    result = fitz.open()
    inherited_navigation_title = None
    for page_no, rule in enumerate(plan):
        source_page = original[page_no]
        target_page = translated[page_no]
        rect = source_page.rect
        out = result.new_page(width=rect.width, height=rect.height)
        if rule["policy"] == "structured_reflow":
            title, items = extract_navigation(source_page, inherited_navigation_title)
            inherited_navigation_title = title
            translations = translate_titles(items)
            render_navigation(out, source_page, title, items, translations)
            rule["structured_items"] = len(items)
        elif rule["policy"] == "term_rows":
            title, rows = extract_terms(source_page)
            translations = translate_strings(
                [row["source"] for row in rows],
                "逐条翻译下面缩略语或物种名称的英文释义。缩略语和拉丁学名不在输入中；译文简洁准确，不添加解释。",
            )
            render_terms(out, source_page, title, rows, translations)
            rule["structured_items"] = len(rows)
        elif rule["policy"] == "translate_table_cells":
            out.show_pdf_page(rect, translated, page_no)
            cell_result = render_cell_tables(out, source_page, original, page_no)
            rule.update(cell_result)
            rule["structured_items"] = cell_result["translated_cells"]
        elif rule["policy"] == "protect_table_translate_caption":
            # Keep the translated page as the base and replace only the detected
            # table rectangle with untouched original vectors and data.
            region = table_region(source_page)
            if region and region.y0 > 24 and region.height > 8:
                out.show_pdf_page(rect, translated, page_no)
                out.draw_rect(region, color=None, fill=(1, 1, 1), overlay=True)
                out.show_pdf_page(region, original, page_no, clip=region, overlay=True)
                rule["protected_region"] = [round(value, 2) for value in region]
            else:
                out.show_pdf_page(rect, translated, page_no)
                rule["fallback"] = "standard_translation"
        elif rule["policy"] == "preserve_original":
            out.show_pdf_page(rect, original, page_no)
        else:
            out.show_pdf_page(rect, translated, page_no)
    result.save(output_path, garbage=4, deflate=True)


def cjk_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u9fff]", text))


def qa(original_path: Path, translated_path: Path, output_path: Path, plan: list[dict]) -> dict:
    original = fitz.open(original_path)
    translated = fitz.open(translated_path)
    output = fitz.open(output_path)
    issues, warnings = [], []
    if len(original) != len(output):
        issues.append("page_count_changed")
    for rule in plan:
        i = rule["pdf_page"] - 1
        if i >= len(output):
            continue
        if tuple(original[i].rect) != tuple(output[i].rect):
            issues.append(f"page_{i+1}_size_changed")
        if rule["policy"] in {"structured_reflow", "term_rows", "translate_table_cells"}:
            if rule.get("structured_items", 0) <= 0:
                issues.append(f"page_{i+1}_structured_items_missing")
            if cjk_count(output[i].get_text("text")) < 2:
                issues.append(f"page_{i+1}_structured_translation_missing")
        if rule["policy"] == "protect_table_translate_caption" and rule.get("fallback"):
            warnings.append(f"page_{i+1}_table_region_unreliable_used_standard_translation")
        if rule["policy"] == "translate_table_cells" and rule.get("fallback_cells", 0):
            warnings.append(f"page_{i+1}_{rule['fallback_cells']}_cells_kept_original")
        if rule["policy"] == "translate_table_cells" and rule.get("companion_fallbacks", 0):
            warnings.append(f"page_{i+1}_{rule['companion_fallbacks']}_table_companions_kept_original")
        translated_cjk = cjk_count(translated[i].get_text("text"))
        output_cjk = cjk_count(output[i].get_text("text"))
        if rule["type"] == "narrative" and translated_cjk >= 20 and output_cjk < translated_cjk * 0.5:
            issues.append(f"page_{i+1}_unexpected_language_regression")
    counts = Counter(rule["type"] for rule in plan)
    return {"passed": not issues, "issues": issues, "warnings": warnings, "page_count": len(output), "type_counts": dict(counts)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("original", type=Path)
    parser.add_argument("translated", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    original = fitz.open(args.original)
    metrics = [page_metrics(page) for page in original]
    plan = classify(metrics)
    compose(args.original, args.translated, args.output, plan)
    report = {"version": 2, "pages": plan, "qa": qa(args.original, args.translated, args.output, plan)}
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report["qa"], ensure_ascii=False))


if __name__ == "__main__":
    main()
