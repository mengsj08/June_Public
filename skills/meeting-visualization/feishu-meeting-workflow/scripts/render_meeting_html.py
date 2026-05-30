#!/usr/bin/env python3
"""Render a local meeting Markdown note as a standalone HTML report.

The renderer is intentionally conservative: it does not embed Feishu signed
media URLs or copy minute/doc tokens into the generated page. Source evidence
should stay in the case `source_index.md` and runtime source files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
from pathlib import Path
import re
from typing import Iterable

from _safety import has_secret_content, is_secret_file


DEFAULT_INPUT = Path.cwd() / "meeting-cases" / "analysis.md"
DEFAULT_CASE = Path.cwd() / "meeting-cases" / "case.yaml"
DEFAULT_OUTPUT = Path.cwd() / "meeting-runtime" / "report.html"

FEISHU_PRIVATE_URL = re.compile(
    r"(feishu\.cn/(minutes|docx)|internal-api-drive-stream\.feishu\.cn|/authcode/)",
    re.I,
)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
TAG_RE = re.compile(r"</?(?:grid|column|readonly-block|cite)\b[^>]*>", re.I)
WHITEBOARD_RE = re.compile(r"<whiteboard\b[^>]*></whiteboard>", re.I)
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def read_case_metadata(case_path: Path | None) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if not case_path or not case_path.exists():
        return metadata
    for raw_line in case_path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([a-zA-Z_]+):\s*(.*)$", raw_line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip().strip('"')
        if key in {"case_id", "title", "source_kind", "meeting_type", "customer_page_generator"}:
            metadata[key] = value
    return metadata


def extract_title(markdown: str, fallback: str) -> tuple[str, str]:
    match = TITLE_RE.search(markdown)
    if not match:
        return fallback, markdown
    title = html.unescape(match.group(1).strip()) or fallback
    return title, TITLE_RE.sub("", markdown, count=1)


def extract_intro(markdown: str) -> tuple[list[str], str]:
    intro: list[str] = []
    body: list[str] = []
    in_intro = True
    for line in markdown.splitlines():
        if in_intro and line.startswith("# "):
            in_intro = False
        if in_intro:
            cleaned = line.strip()
            if cleaned.startswith(">"):
                cleaned = cleaned.lstrip(">").strip()
                if cleaned:
                    intro.append(cleaned)
            elif cleaned and not cleaned.startswith("<title>"):
                intro.append(cleaned)
        else:
            body.append(line)
    return intro, "\n".join(body)


def split_sections(markdown: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_title = "正文"
    current_lines: list[str] = []
    for line in markdown.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            if current_lines or current_title != "正文":
                sections.append((current_title, current_lines))
            current_title = strip_inline_markdown(match.group(1))
            current_lines = []
            continue
        current_lines.append(line)
    if current_lines or current_title != "正文":
        sections.append((current_title, current_lines))
    return [(title, lines) for title, lines in sections if title != "正文" or any(line.strip() for line in lines)]


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", value).strip("-").lower()
    return slug or "section"


def strip_inline_markdown(value: str) -> str:
    value = BOLD_RE.sub(r"\1", value)
    value = LINK_RE.sub(r"\1", value)
    value = IMAGE_RE.sub("图像引用", value)
    value = TAG_RE.sub("", value)
    value = WHITEBOARD_RE.sub("白板引用", value)
    return html.unescape(value).strip()


def safe_link(label: str, url: str) -> str:
    clean_label = html.escape(strip_inline_markdown(label))
    if FEISHU_PRIVATE_URL.search(url) or has_secret_content(url):
        return f'<span class="source-ref">{clean_label}</span>'
    return f'<a href="{html.escape(url, quote=True)}" rel="noreferrer">{clean_label}</a>'


def inline_html(text: str) -> str:
    text = TAG_RE.sub("", text)
    text = WHITEBOARD_RE.sub('<span class="media-ref">白板引用已隐藏，见来源索引</span>', text)
    text = IMAGE_RE.sub('<span class="media-ref">图像引用已隐藏，见来源索引</span>', text)

    escaped = html.escape(text)

    def link_repl(match: re.Match[str]) -> str:
        label = html.unescape(match.group(1))
        url = html.unescape(match.group(2))
        return safe_link(label, url)

    escaped = LINK_RE.sub(link_repl, escaped)
    escaped = BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    return escaped


def close_lists(stack: list[tuple[int, str]], out: list[str], target_level: int = -1) -> None:
    while stack and stack[-1][0] > target_level:
        out.append(f"</{stack.pop()[1]}>")


def render_lines(lines: Iterable[str]) -> str:
    out: list[str] = []
    list_tag: list[str] = []
    quote_buffer: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            out.append(f"<p>{inline_html(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_quote() -> None:
        if quote_buffer:
            out.append("<blockquote>")
            out.extend(f"<p>{inline_html(item)}</p>" for item in quote_buffer)
            out.append("</blockquote>")
            quote_buffer.clear()

    def close_current_list() -> None:
        if list_tag:
            out.append(f"</{list_tag.pop()}>")

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            flush_quote()
            continue
        if TAG_RE.sub("", stripped).strip() == "":
            continue
        if stripped == "---":
            flush_paragraph()
            flush_quote()
            close_current_list()
            out.append("<hr>")
            continue
        if WHITEBOARD_RE.fullmatch(stripped):
            flush_paragraph()
            flush_quote()
            close_current_list()
            out.append('<div class="media-row"><span class="media-ref">白板引用已隐藏，见来源索引</span></div>')
            continue
        if IMAGE_RE.fullmatch(stripped):
            flush_paragraph()
            flush_quote()
            close_current_list()
            out.append('<div class="media-row"><span class="media-ref">图像引用已隐藏，见来源索引</span></div>')
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            quote_text = stripped.lstrip(">").strip()
            if quote_text:
                quote_buffer.append(quote_text)
            continue

        list_match = re.match(r"^(\s*)([-*]|\d+\.)\s+(\[[ xX]\]\s+)?(.+)$", line)
        if list_match:
            flush_paragraph()
            flush_quote()
            indent, marker, checkbox, item = list_match.groups()
            level = min(len(indent.replace("\t", "  ")) // 2, 5)
            tag = "ol" if marker.endswith(".") else "ul"
            if not list_tag or list_tag[-1] != tag:
                close_current_list()
                out.append(f'<{tag} class="list-tree">')
                list_tag.append(tag)
            item_html = inline_html(item)
            if checkbox is not None:
                checked = " checked" if "x" in checkbox.lower() else ""
                item_html = f'<span class="taskbox{checked}"></span>{item_html}'
            out.append(f'<li class="indent-{level}">{item_html}</li>')
            continue

        heading_match = re.match(r"^(#{2,4})\s+(.+)$", line)
        if heading_match:
            flush_paragraph()
            flush_quote()
            close_current_list()
            level = min(len(heading_match.group(1)) + 1, 5)
            out.append(f"<h{level}>{inline_html(heading_match.group(2))}</h{level}>")
            continue

        close_current_list()
        flush_quote()
        paragraph.append(stripped)

    flush_paragraph()
    flush_quote()
    close_current_list()
    return "\n".join(out)


def build_stat_cards(sections: list[tuple[str, list[str]]], metadata: dict[str, str]) -> str:
    task_count = sum(1 for _title, lines in sections for line in lines if re.match(r"\s*-\s+\[[ xX]\]", line))
    chapter_count = 0
    for title, lines in sections:
        if title == "智能章节":
            chapter_count = sum(1 for line in lines if re.match(r"\[\d{2}:\d{2}\]", line.strip()))
    cards = [
        ("会议类型", metadata.get("meeting_type", "internal")),
        ("行动项", f"{task_count} 项"),
        ("章节节点", f"{chapter_count} 个"),
        ("客户页路由", metadata.get("customer_page_generator", "none")),
    ]
    return "\n".join(
        f'<div class="stat"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>'
        for label, value in cards
    )


def build_html(markdown: str, metadata: dict[str, str], source_path: Path, case_path: Path | None) -> str:
    title, without_title = extract_title(markdown, metadata.get("title", "会议纪要"))
    intro, body = extract_intro(without_title)
    sections = split_sections(body)
    nav = "\n".join(
        f'<a href="#{slugify(section_title)}">{html.escape(section_title)}</a>' for section_title, _ in sections
    )
    section_html = "\n".join(
        f'<section id="{slugify(section_title)}"><h2>{html.escape(section_title)}</h2>{render_lines(lines)}</section>'
        for section_title, lines in sections
    )
    meta_items = "\n".join(f"<li>{inline_html(item)}</li>" for item in intro)
    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    case_display = str(case_path) if case_path else "未指定"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --ink: #18201b;
      --muted: #5f6a62;
      --line: #d9ddd2;
      --paper: #f7f5ee;
      --panel: #fffdf7;
      --sage: #4f6f57;
      --blue: #315f7d;
      --rust: #9b5136;
      --gold: #b58b3b;
      --shadow: 0 16px 40px rgba(45, 54, 43, 0.10);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background:
        linear-gradient(90deg, rgba(24,32,27,0.05) 1px, transparent 1px),
        linear-gradient(0deg, rgba(24,32,27,0.035) 1px, transparent 1px),
        var(--paper);
      background-size: 44px 44px;
      color: var(--ink);
      font-family: "Songti SC", "STSong", "Noto Serif CJK SC", Georgia, serif;
      line-height: 1.72;
    }}
    a {{ color: var(--blue); text-decoration-thickness: 1px; text-underline-offset: 3px; }}
    .page {{ max-width: 1180px; margin: 0 auto; padding: 34px 24px 56px; }}
    header {{
      border: 1px solid var(--line);
      background: rgba(255, 253, 247, 0.94);
      box-shadow: var(--shadow);
      padding: 30px;
    }}
    .kicker {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      color: var(--muted);
      font: 700 12px/1.3 "Avenir Next", "Helvetica Neue", sans-serif;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    .pill {{
      border: 1px solid var(--line);
      background: #eef1e9;
      padding: 4px 8px;
      border-radius: 999px;
    }}
    h1 {{
      max-width: 880px;
      margin: 18px 0 18px;
      font-size: clamp(34px, 5vw, 58px);
      line-height: 1.12;
      letter-spacing: 0;
      font-weight: 900;
    }}
    .intro {{
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
      gap: 24px;
      align-items: start;
    }}
    .intro ul {{ margin: 0; padding-left: 20px; color: var(--muted); }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .stat {{
      min-height: 86px;
      border: 1px solid var(--line);
      background: #fbf8ef;
      padding: 12px;
    }}
    .stat span {{
      display: block;
      color: var(--muted);
      font: 700 12px/1.2 "Avenir Next", "Helvetica Neue", sans-serif;
    }}
    .stat strong {{
      display: block;
      margin-top: 12px;
      color: var(--sage);
      font-size: 22px;
      line-height: 1.15;
      overflow-wrap: anywhere;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 220px minmax(0, 1fr);
      gap: 28px;
      margin-top: 28px;
      align-items: start;
    }}
    nav {{
      position: sticky;
      top: 18px;
      border-left: 3px solid var(--sage);
      padding: 8px 0 8px 14px;
      font-family: "Avenir Next", "Helvetica Neue", sans-serif;
    }}
    nav a {{
      display: block;
      color: var(--muted);
      text-decoration: none;
      padding: 8px 0;
      font-size: 14px;
      line-height: 1.3;
    }}
    nav a:hover {{ color: var(--ink); }}
    main {{
      background: rgba(255, 253, 247, 0.88);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }}
    section {{
      padding: 30px;
      border-bottom: 1px solid var(--line);
    }}
    section:last-child {{ border-bottom: 0; }}
    h2 {{
      margin: 0 0 16px;
      font-size: 27px;
      line-height: 1.25;
      letter-spacing: 0;
    }}
    h3, h4, h5 {{
      margin: 22px 0 8px;
      color: var(--sage);
      letter-spacing: 0;
    }}
    p {{ margin: 10px 0; }}
    ul, ol {{ padding-left: 22px; margin: 10px 0; }}
    li {{ margin: 7px 0; }}
    .list-tree {{
      list-style-position: outside;
    }}
    .list-tree .indent-1 {{ margin-left: 18px; }}
    .list-tree .indent-2 {{ margin-left: 36px; }}
    .list-tree .indent-3 {{ margin-left: 54px; }}
    .list-tree .indent-4 {{ margin-left: 72px; }}
    .list-tree .indent-5 {{ margin-left: 90px; }}
    li strong {{ color: #2f4735; }}
    blockquote {{
      margin: 16px 0;
      padding: 12px 16px;
      border-left: 4px solid var(--gold);
      background: #f5f0e3;
      color: #3d433d;
    }}
    blockquote p {{ margin: 4px 0; }}
    hr {{
      border: 0;
      border-top: 1px dashed var(--line);
      margin: 24px 0;
    }}
    .taskbox {{
      display: inline-block;
      width: 16px;
      height: 16px;
      margin-right: 8px;
      border: 1px solid var(--rust);
      vertical-align: -2px;
      background: #fffdf7;
    }}
    .taskbox.checked {{ background: var(--rust); }}
    .media-row {{ margin: 14px 0; }}
    .media-ref, .source-ref {{
      display: inline-flex;
      align-items: center;
      max-width: 100%;
      min-height: 28px;
      border: 1px solid #cfd7c7;
      background: #edf1e8;
      color: #435044;
      border-radius: 6px;
      padding: 3px 8px;
      font: 700 13px/1.4 "Avenir Next", "Helvetica Neue", sans-serif;
      overflow-wrap: anywhere;
    }}
    .evidence {{
      margin-top: 28px;
      border: 1px solid var(--line);
      background: #ece8dc;
      padding: 18px;
      color: var(--muted);
      font: 13px/1.55 "Avenir Next", "Helvetica Neue", sans-serif;
    }}
    .evidence code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      overflow-wrap: anywhere;
    }}
    @media (max-width: 820px) {{
      .page {{ padding: 18px 14px 36px; }}
      header, section {{ padding: 20px; }}
      .intro, .layout {{ grid-template-columns: 1fr; }}
      nav {{ position: static; display: flex; overflow-x: auto; gap: 14px; border-left: 0; border-bottom: 3px solid var(--sage); padding: 0 0 10px; }}
      nav a {{ flex: 0 0 auto; }}
      .stats {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <header>
      <div class="kicker">
        <span class="pill">内部会议 HTML</span>
        <span class="pill">Feishu Minutes</span>
        <span class="pill">生成于 {html.escape(generated_at)}</span>
      </div>
      <h1>{html.escape(title)}</h1>
      <div class="intro">
        <ul>{meta_items}</ul>
        <div class="stats">{build_stat_cards(sections, metadata)}</div>
      </div>
    </header>
    <div class="layout">
      <nav aria-label="章节导航">
        {nav}
      </nav>
      <main>
        {section_html}
      </main>
    </div>
    <div class="evidence" id="source-boundary">
      <strong>来源边界</strong><br>
      本页面不复制飞书 minute/doc token、内部图片授权链接或登录材料。原始 Markdown 与来源索引保存在本地：<br>
      <code>{html.escape(str(source_path))}</code><br>
      <code>{html.escape(case_display)}</code>
    </div>
  </div>
</body>
</html>
"""


def update_case_output_path(case_path: Path | None, output_path: Path) -> None:
    if not case_path or not case_path.exists():
        return
    text = case_path.read_text(encoding="utf-8")
    output = str(output_path)
    if output in text:
        return
    replacement = f'output_paths:\n  - "{output}"'
    if "output_paths: []" in text:
        text = text.replace("output_paths: []", replacement, 1)
    else:
        text = text.rstrip() + "\n\n" + replacement + "\n"
    case_path.write_text(text, encoding="utf-8")


def render(input_path: Path, output_path: Path, case_path: Path | None) -> Path:
    if is_secret_file(input_path) or is_secret_file(output_path):
        raise SystemExit("Refusing to read or write a secret-like path.")
    markdown = input_path.read_text(encoding="utf-8")
    metadata = read_case_metadata(case_path)
    html_doc = build_html(markdown, metadata, input_path, case_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_doc, encoding="utf-8")
    update_case_output_path(case_path, output_path)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a meeting Markdown note into standalone HTML.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--case", default=str(DEFAULT_CASE))
    args = parser.parse_args()

    case_path = Path(args.case).expanduser() if args.case else None
    output_path = render(
        input_path=Path(args.input).expanduser(),
        output_path=Path(args.output).expanduser(),
        case_path=case_path,
    )
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
