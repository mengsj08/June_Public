#!/usr/bin/env python3
"""Convert a user-supplied legacy hospital drug-label HTML into safe local HTML/PDF."""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

from label_common import (
    LabelError,
    TOOL_VERSION,
    artifact_entry,
    render_html_to_pdf,
    sha256_path,
    utc_now,
    verify_manifest,
    wrap_html,
    write_json,
    write_text,
)


LONG_SECTION_UNITS = 1200


def prepare_output(path_value: str) -> Path:
    root = Path(path_value).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise LabelError(f"输出目录不是空目录，拒绝覆盖: {root}")
    root.mkdir(parents=True, exist_ok=True)
    return root


def sanitize_fragment(node) -> tuple[str, int]:
    from bs4 import BeautifulSoup

    fragment = BeautifulSoup(str(node), "html.parser")
    for tag in fragment.find_all(
        ["script", "style", "noscript", "iframe", "object", "embed", "form", "input", "button", "link", "meta", "svg", "canvas", "img"]
    ):
        tag.decompose()
    allowed = {
        "div", "span", "p", "br", "hr", "strong", "b", "em", "i", "u", "sup", "sub", "small",
        "blockquote", "pre", "code", "ul", "ol", "li", "dl", "dt", "dd", "table", "caption", "thead",
        "tbody", "tfoot", "tr", "th", "td",
    }
    for tag in list(fragment.find_all(True)):
        if tag.name not in allowed:
            tag.unwrap()
            continue
        kept = {}
        if tag.name in {"td", "th"}:
            for key in ("colspan", "rowspan", "scope"):
                value = tag.attrs.get(key)
                if value is not None and re.fullmatch(r"[A-Za-z0-9_-]{1,20}", str(value)):
                    kept[key] = str(value)
        tag.attrs = kept
    text_units = len(fragment.get_text(" ", strip=True))
    text_units += len(fragment.find_all("tr")) * 35
    return "".join(str(child) for child in fragment.contents), text_units


def parse_sections(raw: bytes) -> tuple[list[tuple[str, str, int]], str | None]:
    try:
        from bs4 import BeautifulSoup, UnicodeDammit
    except ImportError as exc:
        raise LabelError("缺少 beautifulsoup4；请改用已安装依赖的 Python 运行") from exc
    decoded = UnicodeDammit(raw).unicode_markup
    if not decoded:
        raise LabelError("无法识别源 HTML 编码")
    soup = BeautifulSoup(decoded, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript", "iframe", "object", "embed"]):
        tag.decompose()
    container = soup.find("ul", id="instruction")
    if container is None:
        raise LabelError('未找到 id="instruction" 的说明书正文')
    sections: list[tuple[str, str, int]] = []
    for item in container.find_all("li"):
        name_node = item.select_one(".dict-name")
        value_node = item.select_one(".dict-value")
        if name_node is None or value_node is None:
            continue
        name = name_node.get_text(" ", strip=True)
        if not name or "${" in name:
            continue
        value_html, units = sanitize_fragment(value_node)
        if len(re.sub(r"<[^>]+>", "", value_html).strip()) < 1:
            continue
        sections.append((name, value_html, units))
    if len(sections) < 3:
        raise LabelError(f"仅解析到 {len(sections)} 个章节；拒绝生成可能不完整的说明书")
    source_title = soup.title.get_text(" ", strip=True) if soup.title else None
    return sections, source_title


def infer_title(sections: list[tuple[str, str, int]], fallback: str | None) -> str:
    from bs4 import BeautifulSoup

    for name, value, _ in sections:
        if "通用名称" in name or name.strip() in {"药品名称", "名称"}:
            soup = BeautifulSoup(value, "html.parser")
            strings = list(soup.stripped_strings)
            name_string = next((item for item in strings if "通用名称" in item), strings[0] if strings else "")
            match = re.search(r"通用名称[：:]?\s*([^；;。\n]+)", name_string)
            candidate = (match.group(1) if match else name_string).strip()
            if candidate:
                return candidate if candidate.endswith("说明书") else f"{candidate}说明书"
    return fallback or "药品说明书"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--title")
    parser.add_argument("--subtitle")
    parser.add_argument(
        "--format",
        choices=["html", "pdf", "both"],
        required=True,
        help="用户明确选择的交付格式；不得默认",
    )
    args = parser.parse_args()
    try:
        source_path = Path(args.input).expanduser().resolve()
        if not source_path.is_file():
            raise LabelError(f"源文件不存在: {source_path}")
        if source_path.stat().st_size > 80 * 1024 * 1024:
            raise LabelError("源 HTML 超过 80 MB 安全上限")
        raw = source_path.read_bytes()
        sections, source_title = parse_sections(raw)
        title = args.title or infer_title(sections, source_title)
        rendered_sections = []
        for name, value, units in sections:
            css_class = "section long" if units > LONG_SECTION_UNITS else "section"
            rendered_sections.append(
                f'<section class="{css_class}"><h2>{html.escape(name)}</h2>{value}</section>'
            )
        subtitle = f"<p><strong>{html.escape(args.subtitle)}</strong></p>" if args.subtitle else ""
        document = wrap_html(
            title=title,
            body_html=subtitle + "".join(rendered_sections),
            source_url=None,
            source_label="用户提供的医院/网页说明书兼容转换",
            derived_note="来源内容未被监管机构核验；已删除脚本、插件、表单、iframe 和远程资源",
        )
        root = prepare_output(args.out_dir)
        html_path = root / "label.html"
        write_text(html_path, document)
        artifacts = [
            artifact_entry(
                root,
                html_path,
                role="derived_sanitized_html",
                media_type="text/html",
                derived=True,
                derived_from=str(source_path),
            )
        ]
        if args.format in {"pdf", "both"}:
            pdf_path = root / "label.pdf"
            render_html_to_pdf(html_path, pdf_path)
            artifacts.append(
                artifact_entry(
                    root,
                    pdf_path,
                    role="derived_pdf",
                    media_type="application/pdf",
                    derived=True,
                    derived_from="label.html",
                )
            )
        manifest = {
            "schema_version": 1,
            "tool": {"name": "drug-label-html2pdf", "version": TOOL_VERSION},
            "created_at": utc_now(),
            "request": {"mode": "legacy_html", "format": args.format, "title": args.title},
            "source": {
                "provider": "user_supplied_legacy_html",
                "jurisdiction": "unknown",
                "path": str(source_path),
                "bytes": source_path.stat().st_size,
                "sha256": sha256_path(source_path),
                "authority_verified": False,
            },
            "parsed_section_count": len(sections),
            "artifacts": artifacts,
            "warnings": ["来源不是本 Skill 自动取得的监管机构原件；不得据此声称当前有效或官方批准"],
            "medical_use_boundary": "Formatting and archival only; not medical advice.",
        }
        write_json(root / "manifest.json", manifest)
        verification = verify_manifest(root, manifest)
        write_json(root / "verification.json", verification)
        print(f"OK {len(sections)} 个章节 -> {root}")
        print(f"验证状态: {verification['status']}")
        if verification["errors"]:
            for error in verification["errors"]:
                print(f"ERROR {error}", file=sys.stderr)
            return 1
        return 0
    except LabelError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
