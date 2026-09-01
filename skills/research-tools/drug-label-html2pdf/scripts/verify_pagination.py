#!/usr/bin/env python3
"""Optional detailed page-text check for a generated or official PDF."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf")
    parser.add_argument("titles", nargs="*", help="期望存在的章节标题；可省略")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        import pymupdf
    except ImportError:
        print("ERROR 缺少 pymupdf；请改用已安装依赖的 Python 运行", file=sys.stderr)
        return 1
    path = Path(args.pdf).expanduser().resolve()
    if not path.is_file():
        print(f"ERROR PDF 不存在: {path}", file=sys.stderr)
        return 1
    try:
        document = pymupdf.open(path)
    except Exception as exc:
        print(f"ERROR PDF 无法打开: {exc}", file=sys.stderr)
        return 1
    pages = [page.get_text("text") for page in document]
    issues = []
    title_hits = []
    for title in args.titles:
        hits = []
        for page_index, page_text in enumerate(pages, 1):
            lines = [line.strip() for line in page_text.splitlines() if line.strip()]
            for line_index, line in enumerate(lines):
                if line == title:
                    hits.append({"page": page_index, "line_index": line_index, "lines_after": len(lines) - line_index - 1})
                    if line_index == len(lines) - 1:
                        issues.append(f"「{title}」孤立在第 {page_index} 页页尾")
        if not hits:
            issues.append(f"未找到章节标题「{title}」")
        title_hits.append({"title": title, "hits": hits})
    page_summaries = []
    total_text = 0
    for page_index, page_text in enumerate(pages, 1):
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        total_text += len(page_text.strip())
        page_summaries.append(
            {
                "page": page_index,
                "first_line": lines[0][:80] if lines else "",
                "last_line": lines[-1][-80:] if lines else "",
                "text_characters": len(page_text.strip()),
            }
        )
    if total_text < 30:
        issues.append("PDF 文字层很少，可能是扫描版")
    report = {
        "status": "fail" if issues else "pass",
        "page_count": document.page_count,
        "text_characters": total_text,
        "title_hits": title_hits,
        "page_summaries": page_summaries,
        "issues": issues,
        "scope_note": "本检查验证文字层和标题位置，不证明表格视觉边界或药学内容正确性。",
    }
    document.close()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"页数: {report['page_count']}  文字数: {report['text_characters']}  状态: {report['status']}")
        for page in page_summaries:
            print(f"P{page['page']}: 首[{page['first_line']}] … 尾[{page['last_line']}]")
        for issue in issues:
            print(f"ERROR {issue}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
