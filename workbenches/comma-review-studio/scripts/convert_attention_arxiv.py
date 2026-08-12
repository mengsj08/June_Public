#!/usr/bin/env python3
"""Convert arXiv:1706.03762v7 source into private Markdown spike artifacts.

This is intentionally a one-paper spike, not a generic TeX importer. It keeps
source locators and reports known downgrade points instead of silently
pretending that LaTeX was fully rendered.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import shutil
import subprocess
from pathlib import Path


ARXIV_ID = "1706.03762v7"
TITLE = "Attention Is All You Need"
VERSION = "v7"
ABS_URL = f"https://arxiv.org/abs/{ARXIV_ID}"
SOURCE_URL = f"https://arxiv.org/e-print/{ARXIV_ID}"
PDF_URL = f"https://arxiv.org/pdf/{ARXIV_ID}"
CONVERTER_NAME = "scripts/convert_attention_arxiv.py"
CONVERTER_VERSION = "0.4.0"
MATH_GUARD_TOKENS = ["sqrt", "frac", "sum", "mathrm", "cdot"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def strip_comments(text: str) -> str:
    out = []
    for line in text.splitlines():
        escaped = False
        cut = len(line)
        for i, ch in enumerate(line):
            if ch == "\\":
                escaped = not escaped
                continue
            if ch == "%" and not escaped:
                cut = i
                break
            escaped = False
        out.append(line[:cut])
    return "\n".join(out)


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def expand_inputs(source_dir: Path, filename: str, seen: set[str] | None = None) -> tuple[str, list[dict]]:
    seen = seen or set()
    if filename in seen:
        return "", []
    seen.add(filename)
    path = source_dir / filename
    raw = strip_comments(path.read_text(encoding="utf-8"))
    chunks: list[str] = []
    segments: list[dict] = []
    pos = 0
    for match in re.finditer(r"\\input\{([^}]+)\}", raw):
        before = raw[pos : match.start()]
        chunks.append(before)
        if before.strip():
            segments.append({"file": filename, "start_line": line_of(raw, pos), "end_line": line_of(raw, match.start())})
        child = match.group(1)
        child_file = child if child.endswith(".tex") else f"{child}.tex"
        child_text, child_segments = expand_inputs(source_dir, child_file, seen)
        chunks.append(f"\n\n<!-- begin input: {child_file} -->\n\n")
        chunks.append(child_text)
        chunks.append(f"\n\n<!-- end input: {child_file} -->\n\n")
        segments.extend(child_segments)
        pos = match.end()
    tail = raw[pos:]
    chunks.append(tail)
    if tail.strip():
        segments.append({"file": filename, "start_line": line_of(raw, pos), "end_line": line_of(raw, len(raw))})
    return "".join(chunks), segments


def protect_inline_math(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def repl(match: re.Match) -> str:
        token = f"@@MATH_{len(protected)}@@"
        protected[token] = match.group(0)
        return token

    # Protect single-dollar math before running any prose-oriented macro cleanup.
    # Display math is handled separately by convert_equation().
    return re.sub(r"(?<!\\)\$(?!\$).*?(?<!\\)\$", repl, text, flags=re.S), protected


def restore_inline_math(text: str, protected: dict[str, str]) -> str:
    for token, math in protected.items():
        text = text.replace(token, math)
    return text


def clean_inline(text: str) -> str:
    text, protected_math = protect_inline_math(text)
    text = (
        text
        .replace("``", "\u201c")
        .replace("''", "\u201d")
        .replace("`", "\u2018")
        .replace("'", "\u2019")
    )
    replacements = {
        r"\dmodel": r"d_{\text{model}}",
        r"\dff": r"d_{\text{ff}}",
        r"\dffn": r"d_{\text{ffn}}",
        r"\mbox": "",
        r"\eg": "e.g.",
        r"\ie": "i.e.",
        r"\&": "&",
        r"\%": "%",
        r"\_": "_",
        r"\{": "{",
        r"\}": "}",
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    text = re.sub(r"\\texttt\{([^{}]*)\}", r"`\1`", text)
    text = re.sub(r"\\emph\{([^{}]*)\}", r"*\1*", text)
    text = re.sub(r"\\textbf\{([^{}]*)\}", r"**\1**", text)
    text = re.sub(r"\\url\{([^{}]*)\}", r"<\1>", text)
    text = re.sub(r"~\\cite[tp]?\{([^{}]+)\}", r" [\1]", text)
    text = re.sub(r"\\cite[tp]?\{([^{}]+)\}", r"[\1]", text)
    text = re.sub(r"\\ref\{([^{}]+)\}", r"\\ref{\1}", text)
    text = re.sub(r"\\label\{[^{}]*\}", "", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    return restore_inline_math(text, protected_math).strip()


def extract_envs(text: str, env_names: list[str]) -> tuple[str, list[dict]]:
    envs = []
    pattern = re.compile(
        r"\\begin\{(" + "|".join(re.escape(name) for name in env_names) + r")\*?\}(.*?)\\end\{\1\*?\}",
        re.S,
    )

    def repl(match: re.Match) -> str:
        token = f"@@ENV_{len(envs)}@@"
        envs.append(
            {
                "token": token,
                "env": match.group(1),
                "raw": match.group(0),
                "body": match.group(2),
                "line": line_of(text, match.start()),
            }
        )
        return f"\n\n{token}\n\n"

    return pattern.sub(repl, text), envs


def caption_from(raw: str) -> str:
    match = re.search(r"\\caption\{(.*?)\}", raw, re.S)
    return clean_inline(match.group(1).replace("\n", " ")) if match else ""


def convert_table(raw: str) -> tuple[str, dict]:
    caption = caption_from(raw)
    tabular = re.search(r"\\begin\{tabular\}.*?\n(.*?)\\end\{tabular\}", raw, re.S)
    rows = []
    if tabular:
        body = tabular.group(1)
        body = re.sub(r"\\(toprule|midrule|bottomrule|hline)", "", body)
        for line in re.split(r"\\\\", body):
            line = re.sub(r"\s+", " ", line).strip()
            if not line:
                continue
            line = re.sub(r"\\multicolumn\{[^{}]+\}\{[^{}]+\}\{([^{}]*)\}", r"\1", line)
            line = re.sub(r"\\multirow\{[^{}]+\}\{[^{}]+\}\{([^{}]*)\}", r"\1", line)
            cells = [clean_inline(cell) for cell in line.split("&")]
            if len(cells) > 1:
                rows.append(cells)
    width = max((len(row) for row in rows), default=0)
    out = []
    if caption:
        out.append(f"**Table.** {caption}")
    if rows and width:
        normalized = [row + [""] * (width - len(row)) for row in rows]
        out.append("| " + " | ".join(normalized[0]) + " |")
        out.append("| " + " | ".join(["---"] * width) + " |")
        for row in normalized[1:]:
            out.append("| " + " | ".join(row) + " |")
    else:
        out.append("```latex\n" + raw.strip() + "\n```")
    return "\n".join(out), {"caption": caption, "rows": len(rows), "columns": width}


def tool_version(command: str) -> str:
    path = shutil.which(command)
    if not path:
        return ""
    result = subprocess.run([path, "--version"], check=False, capture_output=True, text=True)
    return (result.stdout or result.stderr).strip().splitlines()[0] if (result.stdout or result.stderr).strip() else command


def rasterize_pdf_asset(src: Path, dest: Path) -> dict:
    sips = shutil.which("sips")
    if not sips:
        raise RuntimeError("No PDF rasterizer available: expected macOS sips")
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sips, "-s", "format", "png", str(src), "--out", str(dest)], check=True, capture_output=True, text=True)
    return {"tool": "sips", "version": tool_version("sips"), "format": "png"}


def copy_asset(source_dir: Path, output_dir: Path, asset: str) -> tuple[str, dict]:
    src = source_dir / asset
    if not src.exists() and not src.suffix:
        for suffix in [".png", ".pdf", ".jpg", ".jpeg"]:
            if (source_dir / f"{asset}{suffix}").exists():
                src = source_dir / f"{asset}{suffix}"
                break
    rel = Path("assets") / src.relative_to(source_dir)
    dest = output_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    if src.suffix.lower() == ".pdf":
        raster_rel = rel.with_suffix(".png")
        raster_detail = rasterize_pdf_asset(src, output_dir / raster_rel)
        return raster_rel.as_posix(), {
            "copied_source_path": rel.as_posix(),
            "copied_source_sha256": sha256(dest),
            "rasterized_from": rel.as_posix(),
            "rasterizer": raster_detail,
        }
    return rel.as_posix(), {}


def convert_figure(raw: str, source_dir: Path, output_dir: Path) -> tuple[str, dict]:
    caption = caption_from(raw)
    assets = []
    for match in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", raw):
        asset = match.group(1)
        try:
            rel, detail = copy_asset(source_dir, output_dir, asset)
            assets.append({"source": asset, "markdown_path": rel, "sha256": sha256(output_dir / rel), **detail})
        except FileNotFoundError:
            assets.append({"source": asset, "missing": True})
    lines = []
    for asset in assets:
        if asset.get("missing"):
            lines.append(f"![missing source asset: {asset['source']}]()")
        else:
            lines.append(f"![{caption}]({asset['markdown_path']})")
    if caption:
        lines.append(f"*Figure caption:* {caption}")
    return "\n\n".join(lines), {"caption": caption, "assets": assets}


def convert_equation(raw: str) -> tuple[str, dict]:
    body = re.sub(r"^\\begin\{[^}]+\}", "", raw.strip())
    body = re.sub(r"\\end\{[^}]+\}$", "", body.strip())
    return "$$\n" + body.strip() + "\n$$", {"sample": body.strip()[:160]}


def math_token_counts(text: str) -> dict[str, int]:
    return {token: len(re.findall(rf"\\{token}(?![A-Za-z])", text)) for token in MATH_GUARD_TOKENS}


def build_math_guard(expanded_tex: str, markdown: str) -> dict:
    tex_counts = math_token_counts(expanded_tex)
    md_counts = math_token_counts(markdown)
    deltas = {token: md_counts[token] - tex_counts[token] for token in MATH_GUARD_TOKENS}
    failures = [
        {"token": token, "tex": tex_counts[token], "markdown": md_counts[token], "delta": deltas[token]}
        for token in MATH_GUARD_TOKENS
        if deltas[token] != 0
    ]
    guard = {"tokens": MATH_GUARD_TOKENS, "tex_counts": tex_counts, "markdown_counts": md_counts, "deltas": deltas, "failures": failures}
    if failures:
        table = "\n".join(
            f"{item['token']}: tex={item['tex']} markdown={item['markdown']} delta={item['delta']}" for item in failures
        )
        raise RuntimeError(f"math token guard failed:\n{table}")
    return guard


def convert_bibliography(raw: str) -> tuple[str, list[dict]]:
    entries = []
    for match in re.finditer(r"\\bibitem\{([^}]+)\}(.*?)(?=\\bibitem\{|\\end\{thebibliography\})", raw, re.S):
        key = match.group(1)
        body = clean_inline(match.group(2).replace("\\newblock", " ").replace("\n", " "))
        entries.append({"key": key, "text": body})
    lines = ["## References"]
    for entry in entries:
        lines.append(f"- [{entry['key']}] {entry['text']}")
    return "\n".join(lines), entries


def convert_body(text: str, source_dir: Path, output_dir: Path) -> tuple[str, dict]:
    original_text = text
    text = re.sub(r"\A.*?(?=\\begin\{abstract\}|\\section\{Introduction\})", "", text, flags=re.S)
    text, envs = extract_envs(text, ["abstract", "equation", "table", "table*", "figure", "figure*", "thebibliography"])
    env_md: dict[str, str] = {}
    manifest = {"equations": [], "tables": [], "figures": [], "references": [], "footnotes": [], "sections": []}
    for env in envs:
        locator = {"file": "expanded-ms.tex", "line": env["line"]}
        raw = env["raw"]
        if env["env"] == "abstract":
            env_md[env["token"]] = "## Abstract\n\n" + clean_inline(env["body"].replace("\n", " "))
        elif env["env"] == "equation":
            md, detail = convert_equation(raw)
            manifest["equations"].append({"locator": locator, **detail})
            env_md[env["token"]] = md
        elif env["env"].startswith("table"):
            md, detail = convert_table(raw)
            manifest["tables"].append({"locator": locator, **detail})
            env_md[env["token"]] = md
        elif env["env"].startswith("figure"):
            md, detail = convert_figure(raw, source_dir, output_dir)
            manifest["figures"].append({"locator": locator, **detail})
            env_md[env["token"]] = md
        elif env["env"] == "thebibliography":
            md, refs = convert_bibliography(raw)
            manifest["references"] = [{"locator": locator, "key": ref["key"]} for ref in refs]
            env_md[env["token"]] = md

    footnotes = []
    for match in re.finditer(r"\\(?:thanks|footnote)\{(.*?)\}", original_text, re.S):
        footnotes.append({"locator": {"file": "expanded-ms.tex", "line": line_of(original_text, match.start())}, "text": clean_inline(match.group(1))})
    manifest["footnotes"] = footnotes

    def section_repl(match: re.Match) -> str:
        level = 2 if match.group(1) == "section" else 3 if match.group(1) == "subsection" else 4
        title = clean_inline(match.group(3))
        manifest["sections"].append({"level": level, "title": title, "locator": {"file": "expanded-ms.tex", "line": line_of(text, match.start())}})
        return "\n\n" + "#" * level + " " + title + "\n\n"

    text = re.sub(r"\\(section|subsection|subsubsection)(\*)?\{([^{}]+)\}", section_repl, text)
    text = re.sub(r"\\paragraph\{([^{}]+)\}", lambda m: "\n\n#### " + clean_inline(m.group(1)) + "\n\n", text)
    text = re.sub(r"\\title\{([^{}]+)\}", "", text)
    text = re.sub(r"\\author\{.*?\}\s*\\begin\{document\}", r"\\begin{document}", text, flags=re.S)
    text = re.sub(r"\\begin\{document\}|\\end\{document\}|\\maketitle", "", text)
    text = re.sub(r"\\begin\{center\}.*?\\end\{center\}", "", text, flags=re.S)
    text = re.sub(r"\\bibliographystyle\{[^{}]+\}", "", text)
    text = re.sub(r"\\(footnotemark|samethanks)(?:\[[^\]]+\])?", "", text)
    text = re.sub(r"\\thanks\{.*?\}", "", text, flags=re.S)
    for token, md in env_md.items():
        text = text.replace(token, md)
    lines = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        if block.startswith("#") or block.startswith("|") or block.startswith("$$") or block.startswith("![") or block.startswith("**Table") or block.startswith("## References") or block.startswith("- ["):
            lines.append(block)
        elif block.startswith("<!--"):
            continue
        elif block.startswith("\\"):
            lines.append("```latex\n" + block + "\n```")
        else:
            lines.append(clean_inline(block.replace("\n", " ")))
    md = "# Attention Is All You Need\n\n" + "\n\n".join(lines).strip() + "\n"
    return md, manifest


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def text_from_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def parse_abs_metadata(abs_html: str) -> dict:
    def find(pattern: str) -> str:
        match = re.search(pattern, abs_html, re.S)
        return text_from_html(match.group(1)) if match else ""

    authors_block = re.search(r'<div class="authors">.*?</span>(.*?)</div>', abs_html, re.S)
    authors = []
    if authors_block:
        authors = re.findall(r'>([^<>]+)</a>', authors_block.group(1))
    return {
        "dateline": find(r'<div class="dateline">\s*(.*?)</div>'),
        "title": find(r'<h1 class="title mathjax"><span class="descriptor">Title:</span>(.*?)</h1>'),
        "authors": authors,
        "comments": find(r'<td class="tablecell comments mathjax">(.*?)</td>'),
        "subjects": find(r'<td class="tablecell subjects">\s*(.*?)</td>'),
        "cite_as": find(r'<td class="tablecell arxivid"><span class="arxivid">(.*?)</span></td>'),
        "this_version": find(r'<td class="tablecell arxividv">\(or <span class="arxivid">\s*(.*?)</span> for this version\)'),
    }


def make_loss_report(manifest: dict, public: bool) -> str:
    converter = manifest["conversion"]["converter"]
    lines = [
        "# arXiv 1706.03762v7 conversion loss report",
        "",
        f"- Converter: `{converter['name']}` {converter['version']}",
        f"- Runtime: Python {converter['python_version']}",
        "- Scope: one-paper spike for Attention Is All You Need, not a generic TeX importer.",
        "- Input chain: official arXiv abs HTML, e-print TeX source, official PDF.",
        "",
        "## Element Status",
        "",
        f"- Sections: preserved as Markdown headings; count={manifest['counts']['sections']}.",
        f"- Equations: transformed to Markdown display math with raw TeX bodies retained; count={manifest['counts']['equations']}.",
        "- Inline math: single-dollar spans are protected before prose cleanup; guard verified zero token-count delta for "
        + ", ".join(f"`\\{token}`" for token in MATH_GUARD_TOKENS)
        + ".",
        f"- Tables: transformed from LaTeX tabular to Markdown pipe tables when parseable; count={manifest['counts']['tables']}.",
        f"- Figures: source package assets copied and referenced by relative paths; count={manifest['counts']['figures']}, assets={manifest['counts']['figure_assets']}, rasterized_pdf_assets={manifest['counts']['figure_rasterized_assets']}.",
        f"- PDF figure rasterizer: `{manifest['conversion']['rasterizer']['tool']}` {manifest['conversion']['rasterizer']['version'] or 'unavailable'}; Markdown references the generated PNG while the copied source PDF remains listed in the manifest.",
        f"- Footnotes: detected and listed in manifest; count={manifest['counts']['footnotes']}.",
        f"- References: bibliography keys preserved; count={manifest['counts']['references']}.",
        "",
        "## Known Losses And Downgrades",
        "",
        "- TeX macro expansion is partial; unknown macros are preserved or simplified and require manual check.",
        "- The math-token guard checks command counts, not semantic equivalence of rendered mathematics.",
        "- LaTeX labels/cross-references are not resolved to final section, table, equation, or figure numbers.",
        "- Table typography from `booktabs`, `multirow`, `multicolumn`, spacing, and alignment is downgraded to Markdown table text.",
        "- Figure layout options, subfigure grouping, page placement, and original PDF pagination are not preserved.",
        "- PDF vector figure assets are rasterized to PNG for browser display; vector editability and exact PDF-level rendering are not preserved in Markdown.",
        "- Bibliography is flattened to Markdown list entries; citation links are not resolved bidirectionally.",
        "- Author affiliation layout and title footnote markers are simplified.",
        "",
    ]
    if public:
        lines.extend(
            [
                "## Redaction",
                "",
                "This committed report excludes manuscript body text and long captions. Full source locators and samples are in the private data manifest under `apps/review-studio/data/`.",
            ]
        )
    else:
        lines.extend(
            [
                "## Private Locator Detail",
                "",
                "The adjacent manifest includes per-element source locators and short samples for manual audit against the TeX source and PDF.",
            ]
        )
    return "\n".join(lines) + "\n"


def redacted_manifest(manifest: dict) -> dict:
    return {
        "arxiv_id": manifest["arxiv_id"],
        "version": manifest["version"],
        "title": manifest["title"],
        "urls": manifest["urls"],
        "downloaded_at_utc": manifest["downloaded_at_utc"],
        "abs_metadata": manifest["abs_metadata"],
        "input_hashes_sha256": manifest["input_hashes_sha256"],
        "source_package_files": manifest["source_package_files"],
        "counts": manifest["counts"],
        "math_token_guard": manifest["math_token_guard"],
        "conversion": manifest["conversion"],
        "private_outputs": manifest["private_outputs"],
        "redaction_note": "No manuscript body, long captions, images, PDF, or source package content is committed.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("apps/review-studio/data/arxiv-1706.03762v7"))
    parser.add_argument("--public-dir", type=Path, default=Path("docs/review-studio/arxiv-1706.03762v7"))
    parser.add_argument("--downloaded-at-utc", default=None, help="UTC timestamp recorded when the official inputs were downloaded.")
    args = parser.parse_args()

    root = Path.cwd().resolve()
    data_dir = args.data_dir.resolve()
    public_dir = args.public_dir.resolve()
    source_dir = data_dir / "source"
    output_dir = data_dir / "converted"
    output_dir.mkdir(parents=True, exist_ok=True)
    expanded, segments = expand_inputs(source_dir, "ms.tex")
    (output_dir / "expanded-ms.tex").write_text(expanded, encoding="utf-8")
    md, elements = convert_body(expanded, source_dir, output_dir)
    math_guard = build_math_guard(expanded, md)
    source_md = output_dir / "attention-is-all-you-need-source.md"
    source_md.write_text(md, encoding="utf-8")
    stress_md = output_dir / "attention-is-all-you-need-renderer-stress.md"
    stress_md.write_text(
        md
        + "\n\n## Appendix — Comma renderer stress-test (synthetic, not part of arXiv source)\n\n"
        + "```javascript\n"
        + "function scaledDotProductAttention(q, k, v) {\n"
        + "  const scores = matmul(q, transpose(k)).map((x) => x / Math.sqrt(k.length));\n"
        + "  return matmul(softmax(scores), v);\n"
        + "}\n"
        + "```\n",
        encoding="utf-8",
    )

    input_hashes = {
        "abs_html": sha256(data_dir / "abs.html"),
        "source_tar": sha256(data_dir / "source.tar"),
        "pdf": sha256(data_dir / "paper.pdf"),
    }
    abs_metadata = parse_abs_metadata((data_dir / "abs.html").read_text(encoding="utf-8"))
    source_files = []
    for path in sorted(source_dir.rglob("*")):
        if path.is_file():
            source_files.append({"path": path.relative_to(source_dir).as_posix(), "sha256": sha256(path)})
    figure_assets = sum(len(fig.get("assets", [])) for fig in elements["figures"])
    rasterized_assets = sum(
        1
        for fig in elements["figures"]
        for asset in fig.get("assets", [])
        if asset.get("rasterized_from")
    )
    manifest = {
        "arxiv_id": ARXIV_ID,
        "version": VERSION,
        "title": TITLE,
        "urls": {"abs": ABS_URL, "source": SOURCE_URL, "pdf": PDF_URL},
        "downloaded_at_utc": args.downloaded_at_utc
        or dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "input_hashes_sha256": input_hashes,
        "source_package_files": source_files,
        "counts": {
            "sections": len(elements["sections"]),
            "heading_levels": sorted(set(section["level"] for section in elements["sections"])),
            "equations": len(elements["equations"]),
            "tables": len(elements["tables"]),
            "figures": len(elements["figures"]),
            "figure_assets": figure_assets,
            "figure_rasterized_assets": rasterized_assets,
            "footnotes": len(elements["footnotes"]),
            "references": len(elements["references"]),
            "inline_math_spans": len(re.findall(r"(?<!\\)\$(?!\$).*?(?<!\\)\$", expanded, re.S)),
            "inline_citation_commands": len(re.findall(r"\\cite[tp]?\{", expanded)),
        },
        "math_token_guard": math_guard,
        "abs_metadata": abs_metadata,
        "elements": elements,
        "expanded_source_segments": segments,
        "private_outputs": {
            "source_md": source_md.relative_to(root).as_posix(),
            "renderer_stress_md": stress_md.relative_to(root).as_posix(),
            "expanded_tex": (output_dir / "expanded-ms.tex").relative_to(root).as_posix(),
            "assets_dir": (output_dir / "assets").relative_to(root).as_posix(),
        },
        "conversion": {
            "converter": {
                "name": CONVERTER_NAME,
                "version": CONVERTER_VERSION,
                "python_version": ".".join(map(str, __import__("sys").version_info[:3])),
            },
            "rasterizer": {"tool": "sips", "version": tool_version("sips"), "fallback": "pdftoppm not used"},
            "strategy": "recursive TeX input expansion with partial LaTeX-to-Markdown transforms; official PDF retained for audit.",
        },
    }
    write_json(data_dir / "attention-is-all-you-need-private-manifest.json", manifest)
    (data_dir / "attention-is-all-you-need-conversion-loss-report.md").write_text(make_loss_report(manifest, public=False), encoding="utf-8")
    public_dir.mkdir(parents=True, exist_ok=True)
    write_json(public_dir / "manifest-redacted.json", redacted_manifest(manifest))
    (public_dir / "conversion-loss-report.md").write_text(make_loss_report(manifest, public=True), encoding="utf-8")
    print(json.dumps({"source_md": str(source_md), "stress_md": str(stress_md), "counts": manifest["counts"]}, indent=2))


if __name__ == "__main__":
    main()
