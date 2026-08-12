#!/usr/bin/env python3
"""Build a page-aligned side-by-side bilingual PDF."""
from __future__ import annotations
import argparse
from pathlib import Path
import fitz

def fit_rect(source: fitz.Rect, target: fitz.Rect) -> fitz.Rect:
    scale = min(target.width / source.width, target.height / source.height)
    width, height = source.width * scale, source.height * scale
    x0 = target.x0 + (target.width - width) / 2
    y0 = target.y0 + (target.height - height) / 2
    return fitz.Rect(x0, y0, x0 + width, y0 + height)

def merge(original_path: Path, translated_path: Path, output_path: Path, gutter: float = 18.0) -> None:
    original, translated = fitz.open(original_path), fitz.open(translated_path)
    if len(original) != len(translated):
        raise ValueError(f"页数不一致：原文 {len(original)}，译文 {len(translated)}")
    result = fitz.open()
    for index, (left_page, right_page) in enumerate(zip(original, translated)):
        panel_width = max(left_page.rect.width, right_page.rect.width)
        canvas_height = max(left_page.rect.height, right_page.rect.height)
        canvas_width = panel_width * 2 + gutter
        page = result.new_page(width=canvas_width, height=canvas_height)
        left_panel = fitz.Rect(0, 0, panel_width, canvas_height)
        right_panel = fitz.Rect(panel_width + gutter, 0, canvas_width, canvas_height)
        page.show_pdf_page(fit_rect(left_page.rect, left_panel), original, index)
        page.show_pdf_page(fit_rect(right_page.rect, right_panel), translated, index)
        divider = panel_width + gutter / 2
        page.draw_line((divider, 18), (divider, canvas_height - 18), color=(0.82, 0.82, 0.82), width=0.5)
    result.save(output_path, garbage=4, deflate=True)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("original", type=Path); parser.add_argument("translated", type=Path); parser.add_argument("output", type=Path)
    parser.add_argument("--gutter", type=float, default=18.0); args = parser.parse_args()
    merge(args.original, args.translated, args.output, args.gutter); print(args.output)

if __name__ == "__main__": main()
