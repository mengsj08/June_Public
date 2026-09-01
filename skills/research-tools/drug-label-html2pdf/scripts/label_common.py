#!/usr/bin/env python3
"""Shared safety, rendering, provenance, and verification helpers."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse


TOOL_VERSION = "0.2.2"
DEFAULT_MAX_BYTES = 80 * 1024 * 1024
DEFAULT_OFFICIAL_HOSTS = {
    "dailymed.nlm.nih.gov",
    "accessdata.fda.gov",
    "fda.gov",
    "cde.org.cn",
    "nmpa.gov.cn",
    "ema.europa.eu",
    "ec.europa.eu",
}


class LabelError(RuntimeError):
    """Expected, user-actionable failure."""


@dataclass(frozen=True)
class FetchResult:
    data: bytes
    requested_url: str
    final_url: str
    content_type: str
    headers: dict[str, str]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_slug(value: str, fallback: str = "drug-label") -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value)
    value = value.strip("-")
    return (value[:100] or fallback).strip("-")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def artifact_entry(
    root: Path,
    path: Path,
    *,
    role: str,
    media_type: str,
    derived: bool,
    derived_from: str | None = None,
) -> dict:
    entry = {
        "role": role,
        "path": path.relative_to(root).as_posix(),
        "media_type": media_type,
        "bytes": path.stat().st_size,
        "sha256": sha256_path(path),
        "derived": derived,
    }
    if derived_from:
        entry["derived_from"] = derived_from
    return entry


def _hostname_allowed(hostname: str, allowed_hosts: Iterable[str]) -> bool:
    host = hostname.rstrip(".").lower()
    for allowed in allowed_hosts:
        root = allowed.rstrip(".").lower()
        if host == root or host.endswith("." + root):
            return True
    return False


def validate_https_url(url: str, allowed_hosts: Iterable[str]) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise LabelError("只允许 HTTPS 来源")
    if parsed.username or parsed.password:
        raise LabelError("URL 不得包含用户名或密码")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        raise LabelError("URL 缺少主机名")
    if host == "localhost" or host.endswith(".local"):
        raise LabelError("禁止 localhost 或本地域名")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise LabelError("禁止私网、回环或保留 IP")
    if not _hostname_allowed(host, allowed_hosts):
        raise LabelError(f"域名未获允许: {host}；确认官方来源后用 --allow-host 明确加入")
    return url


def fetch_bytes(
    url: str,
    *,
    allowed_hosts: Iterable[str],
    timeout: float = 35,
    max_bytes: int = DEFAULT_MAX_BYTES,
    redirects: int = 5,
) -> FetchResult:
    try:
        import requests
    except ImportError as exc:
        raise LabelError("缺少 requests；请改用已安装依赖的 Python 运行") from exc

    current = validate_https_url(url, allowed_hosts)
    session = requests.Session()
    headers = {
        "User-Agent": "drug-label-html2pdf/0.2 (+local archival; contact via interactive user)",
        "Accept": "application/pdf, application/xml, application/zip, text/html;q=0.9, */*;q=0.1",
    }
    for _ in range(redirects + 1):
        try:
            response = session.get(
                current,
                headers=headers,
                timeout=(10, timeout),
                stream=True,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise LabelError(f"下载失败: {exc}") from exc

        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise LabelError("重定向响应缺少 Location")
            current = validate_https_url(urljoin(current, location), allowed_hosts)
            continue

        if response.status_code != 200:
            response.close()
            raise LabelError(f"来源返回 HTTP {response.status_code}: {current}")

        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            response.close()
            raise LabelError(f"文件超过大小上限 {max_bytes} bytes")

        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in response.iter_content(1024 * 128):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise LabelError(f"下载内容超过大小上限 {max_bytes} bytes")
                chunks.append(chunk)
        finally:
            response.close()
        data = b"".join(chunks)
        if not data:
            raise LabelError("来源返回空文件")
        normalized_headers = {k.lower(): v for k, v in response.headers.items()}
        return FetchResult(
            data=data,
            requested_url=url,
            final_url=current,
            content_type=normalized_headers.get("content-type", "").split(";", 1)[0].strip().lower(),
            headers=normalized_headers,
        )
    raise LabelError("重定向次数超过上限")


def detect_content_kind(data: bytes, content_type: str = "") -> str:
    head = data[:4096].lstrip()
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"<?xml") or content_type in {"application/xml", "text/xml"}:
        return "xml"
    lowered = head.lower()
    if b"<html" in lowered or b"<!doctype html" in lowered or content_type == "text/html":
        return "html"
    return "unknown"


BASE_CSS = """
@page { size: A4; margin: 18mm 17mm 20mm; }
* { box-sizing: border-box; }
html { background: #f2f4f7; }
body { max-width: 210mm; margin: 0 auto; padding: 16mm 17mm 20mm; background: #fff;
  color: #17202a; font: 10.5pt/1.72 -apple-system, BlinkMacSystemFont, "Noto Sans CJK SC",
  "PingFang SC", "Helvetica Neue", Arial, sans-serif; }
h1 { margin: 0 0 7mm; font-size: 19pt; line-height: 1.3; }
h2 { margin: 8mm 0 3mm; padding-left: 3mm; border-left: 1.2mm solid #1f5f88;
  font-size: 13pt; line-height: 1.4; break-after: avoid; }
h3, h4 { break-after: avoid; }
p { margin: 2mm 0; orphans: 2; widows: 2; }
table { width: 100%; border-collapse: collapse; margin: 4mm 0; font-size: 9.5pt; }
th, td { border: .25mm solid #8896a3; padding: 1.6mm 2mm; vertical-align: top; }
tr { break-inside: avoid; }
img { max-width: 100%; height: auto; break-inside: avoid; }
ul, ol { padding-left: 7mm; }
.provenance { margin: 0 0 8mm; padding: 3.5mm 4mm; border: .3mm solid #a9bbc8;
  border-radius: 2mm; background: #eef5f8; font-size: 8.5pt; line-height: 1.5; }
.provenance strong { color: #124a6b; }
.section { break-inside: auto; }
.page-text { white-space: pre-wrap; font-family: "Noto Sans CJK SC", sans-serif; }
.source-page { break-after: page; }
.source-page:last-child { break-after: auto; }
@media print { html { background: #fff; } body { padding: 0; max-width: none; }
  .provenance a { color: inherit; text-decoration: none; } }
"""


def wrap_html(
    *,
    title: str,
    body_html: str,
    source_url: str | None,
    source_label: str,
    derived_note: str,
    language: str = "zh-CN",
) -> str:
    source_line = ""
    if source_url:
        escaped_url = html.escape(source_url, quote=True)
        source_line = f'<br>来源：<a href="{escaped_url}">{escaped_url}</a>'
    return f"""<!doctype html>
<html lang="{html.escape(language, quote=True)}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><style>{BASE_CSS}</style></head>
<body>
<div class="provenance"><strong>{html.escape(source_label)}</strong> · {html.escape(derived_note)}
{source_line}<br>获取时间（UTC）：{html.escape(utc_now())}</div>
<h1>{html.escape(title)}</h1>
{body_html}
</body></html>"""


def sanitize_external_html(raw: bytes, *, title: str | None, source_url: str) -> tuple[str, str, int]:
    try:
        from bs4 import BeautifulSoup, Comment
    except ImportError as exc:
        raise LabelError("缺少 beautifulsoup4；请改用已安装依赖的 Python 运行") from exc

    soup = BeautifulSoup(raw, "html.parser")
    detected_title = ""
    if soup.title:
        detected_title = soup.title.get_text(" ", strip=True)
    for node in soup.find_all(string=lambda value: isinstance(value, Comment)):
        node.extract()
    for tag in soup.find_all(
        ["script", "style", "noscript", "iframe", "object", "embed", "form", "input", "button", "link", "meta", "svg", "canvas"]
    ):
        tag.decompose()

    candidates = [node for node in [soup.body, *soup.find_all("main"), *soup.find_all("article")] if node is not None]
    root = max(candidates, key=lambda node: len(node.get_text(" ", strip=True))) if candidates else soup
    allowed = {
        "article", "section", "div", "span", "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
        "strong", "b", "em", "i", "u", "sup", "sub", "small", "blockquote", "pre", "code",
        "ul", "ol", "li", "dl", "dt", "dd", "table", "caption", "thead", "tbody", "tfoot", "tr", "th", "td", "a",
    }
    table_attrs = {"colspan", "rowspan", "scope"}
    for tag in list(root.find_all(True)):
        if tag.name not in allowed:
            tag.unwrap()
            continue
        keep: dict[str, str] = {}
        if tag.name in {"td", "th"}:
            for key in table_attrs:
                value = tag.attrs.get(key)
                if value is not None and re.fullmatch(r"[A-Za-z0-9_-]{1,20}", str(value)):
                    keep[key] = str(value)
        tag.attrs = keep

    body_text = root.get_text(" ", strip=True)
    if len(body_text) < 80:
        raise LabelError("HTML 正文过短；可能是验证码、反自动化页面或错误页")
    document_title = title or detected_title or "药品说明书"
    rendered = wrap_html(
        title=document_title,
        body_html=str(root),
        source_url=source_url,
        source_label="外部官方 HTML 的本地净化副本",
        derived_note="已移除脚本、表单、iframe、远程资源和事件属性；不是官方原始版式",
    )
    return rendered, document_title, len(body_text)


def pdf_text_to_html(pdf_path: Path, *, title: str, source_url: str | None) -> tuple[str, int, int]:
    try:
        import pymupdf
    except ImportError as exc:
        raise LabelError("缺少 pymupdf，无法从 PDF 生成 HTML 文字副本") from exc
    try:
        document = pymupdf.open(pdf_path)
    except Exception as exc:
        raise LabelError(f"PDF 无法打开: {exc}") from exc
    blocks: list[str] = []
    total = 0
    for index, page in enumerate(document):
        text_value = page.get_text("text")
        total += len(text_value.strip())
        blocks.append(
            f'<section class="source-page"><h2>第 {index + 1} 页</h2>'
            f'<div class="page-text">{html.escape(text_value)}</div></section>'
        )
    page_count = document.page_count
    document.close()
    if page_count < 1:
        raise LabelError("PDF 没有页面")
    rendered = wrap_html(
        title=title,
        body_html="".join(blocks),
        source_url=source_url,
        source_label="官方 PDF 的文字层派生 HTML",
        derived_note="仅用于检索阅读；版式和图像请以 source/ 中的官方 PDF 为准",
    )
    return rendered, page_count, total


def find_chrome() -> Path:
    candidates = [
        os.environ.get("DRUG_LABEL_CHROME"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return Path(candidate)
    raise LabelError("未找到可执行的 Chrome；可用 DRUG_LABEL_CHROME 指定路径")


def render_html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    chrome = find_chrome()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(chrome),
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        html_path.resolve().as_uri(),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if completed.returncode != 0 or not pdf_path.exists():
        detail = (completed.stderr or completed.stdout or "unknown Chrome error").strip()
        raise LabelError(f"Chrome 生成 PDF 失败: {detail[-1200:]}")
    if not pdf_path.read_bytes().startswith(b"%PDF-"):
        raise LabelError("Chrome 输出不是有效 PDF 签名")


def verify_manifest(root: Path, manifest: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict] = []
    for item in manifest.get("artifacts", []):
        rel = item.get("path", "")
        path = root / rel
        check = {"path": rel, "role": item.get("role"), "exists": path.is_file()}
        if not path.is_file():
            errors.append(f"缺少产物: {rel}")
            checks.append(check)
            continue
        actual_hash = sha256_path(path)
        check["sha256_ok"] = actual_hash == item.get("sha256")
        check["bytes"] = path.stat().st_size
        if not check["sha256_ok"]:
            errors.append(f"SHA-256 不一致: {rel}")
        kind = detect_content_kind(path.read_bytes()[:4096], item.get("media_type", ""))
        check["detected_kind"] = kind

        if item.get("media_type") == "application/pdf":
            if kind != "pdf":
                errors.append(f"PDF 文件签名错误: {rel}")
            else:
                try:
                    import pymupdf

                    document = pymupdf.open(path)
                    text_chars = sum(len(page.get_text("text").strip()) for page in document)
                    check["page_count"] = document.page_count
                    check["text_characters"] = text_chars
                    if document.page_count < 1:
                        errors.append(f"PDF 无页面: {rel}")
                    elif text_chars < 30:
                        warnings.append(f"PDF 文字层很少，可能是扫描版: {rel}")
                    document.close()
                except Exception as exc:
                    errors.append(f"PDF 无法打开 {rel}: {exc}")
        elif item.get("media_type") == "text/html":
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
                forbidden = [tag.name for tag in soup.find_all(["script", "iframe", "object", "embed", "form"])]
                check["text_characters"] = len(soup.get_text(" ", strip=True))
                if item.get("derived"):
                    check["forbidden_tags"] = forbidden
                    if forbidden:
                        errors.append(f"派生 HTML 含禁用标签 {sorted(set(forbidden))}: {rel}")
                else:
                    check["untrusted_active_tags_preserved"] = sorted(set(forbidden))
                threshold = 1500 if item.get("role") == "derived_sanitized_html" else 80
                if check["text_characters"] < threshold:
                    warnings.append(f"HTML 正文较短（{check['text_characters']} 字）: {rel}")
            except Exception as exc:
                errors.append(f"HTML 无法验证 {rel}: {exc}")
        elif item.get("media_type") in {"application/xml", "text/xml"}:
            try:
                from lxml import etree

                parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
                tree = etree.parse(str(path), parser)
                section_count = int(tree.xpath("count(//*[local-name()='section'])"))
                check["section_count"] = section_count
                if section_count < 1:
                    warnings.append(f"XML 未识别到 section: {rel}")
            except Exception as exc:
                errors.append(f"XML 无法解析 {rel}: {exc}")
        checks.append(check)

    status = "fail" if errors else ("warn" if warnings else "pass")
    return {
        "schema_version": 1,
        "verified_at": utc_now(),
        "status": status,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }
