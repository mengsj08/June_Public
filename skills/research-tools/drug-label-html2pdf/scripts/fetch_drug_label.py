#!/usr/bin/env python3
"""Fetch authoritative drug labeling and create provenance-preserving HTML/PDF artifacts."""

from __future__ import annotations

import argparse
import html
import io
import json
import mimetypes
import re
import sys
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlencode, urlparse

from label_common import (
    DEFAULT_OFFICIAL_HOSTS,
    LabelError,
    TOOL_VERSION,
    artifact_entry,
    detect_content_kind,
    fetch_bytes,
    pdf_text_to_html,
    render_html_to_pdf,
    safe_slug,
    sanitize_external_html,
    utc_now,
    verify_manifest,
    wrap_html,
    write_bytes,
    write_json,
    write_text,
)


DAILYMED_API = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
HL7_NS = "urn:hl7-org:v3"
NS = {"h": HL7_NS}


class AmbiguousCandidates(LabelError):
    def __init__(self, candidates: list[dict]):
        super().__init__("检索结果不唯一；请确认 SETID 后再下载")
        self.candidates = candidates


def prepare_output(path_value: str) -> Path:
    root = Path(path_value).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise LabelError(f"输出目录不是空目录，拒绝覆盖: {root}")
    root.mkdir(parents=True, exist_ok=True)
    (root / "source").mkdir(exist_ok=True)
    return root


def dailymed_search(query: str, *, name_type: str, limit: int, timeout: float) -> tuple[list[dict], dict]:
    params = {
        "drug_name": query.strip(),
        "name_type": name_type,
        "pagesize": str(max(1, min(limit, 100))),
    }
    url = f"{DAILYMED_API}/spls.json?{urlencode(params)}"
    result = fetch_bytes(url, allowed_hosts=DEFAULT_OFFICIAL_HOSTS, timeout=timeout, max_bytes=8 * 1024 * 1024)
    try:
        payload = json.loads(result.data)
    except json.JSONDecodeError as exc:
        raise LabelError("DailyMed 检索响应不是有效 JSON") from exc
    candidates = payload.get("data") or []
    normalized = []
    for item in candidates:
        if not isinstance(item, dict) or not item.get("setid"):
            continue
        normalized.append(
            {
                "setid": str(item.get("setid")),
                "title": str(item.get("title") or ""),
                "published_date": str(item.get("published_date") or "unknown"),
                "spl_version": str(item.get("spl_version") or "unknown"),
            }
        )
    return normalized, payload.get("metadata") or {}


def dailymed_lookup_setid(setid: str, *, timeout: float) -> tuple[dict, dict]:
    try:
        normalized = str(uuid.UUID(setid))
    except ValueError as exc:
        raise LabelError(f"无效 SETID: {setid}") from exc
    url = f"{DAILYMED_API}/spls.json?{urlencode({'setid': normalized, 'pagesize': '5'})}"
    result = fetch_bytes(url, allowed_hosts=DEFAULT_OFFICIAL_HOSTS, timeout=timeout, max_bytes=4 * 1024 * 1024)
    try:
        payload = json.loads(result.data)
    except json.JSONDecodeError as exc:
        raise LabelError("DailyMed SETID 响应不是有效 JSON") from exc
    candidates = payload.get("data") or []
    if len(candidates) != 1:
        raise LabelError(f"DailyMed 未找到唯一 SETID: {normalized}")
    item = candidates[0]
    return {
        "setid": normalized,
        "title": str(item.get("title") or "Drug Label"),
        "published_date": str(item.get("published_date") or "unknown"),
        "spl_version": str(item.get("spl_version") or "unknown"),
    }, payload.get("metadata") or {}


def print_candidates(candidates: list[dict]) -> None:
    if not candidates:
        print("未找到候选")
        return
    for index, item in enumerate(candidates, 1):
        print(
            f"[{index}] {item['title']}\n"
            f"    SETID: {item['setid']}  SPL version: {item['spl_version']}  published: {item['published_date']}"
        )


def select_candidate(args: argparse.Namespace) -> tuple[dict, dict]:
    if args.setid:
        return dailymed_lookup_setid(args.setid, timeout=args.timeout)
    candidates, metadata = dailymed_search(
        args.query,
        name_type=args.name_type,
        limit=args.limit,
        timeout=args.timeout,
    )
    if not candidates:
        raise LabelError(f"DailyMed 未找到: {args.query}")
    if args.select is not None:
        if args.select < 1 or args.select > len(candidates):
            raise LabelError(f"--select 超出范围 1..{len(candidates)}")
        return candidates[args.select - 1], metadata
    if len(candidates) != 1:
        raise AmbiguousCandidates(candidates)
    return candidates[0], metadata


def parse_spl_xml(xml_bytes: bytes):
    try:
        from lxml import etree
    except ImportError as exc:
        raise LabelError("缺少 lxml；请改用已安装依赖的 Python 运行") from exc
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=False)
    try:
        return etree.fromstring(xml_bytes, parser)
    except etree.XMLSyntaxError as exc:
        raise LabelError(f"SPL XML 无法解析: {exc}") from exc


def spl_metadata(root) -> dict:
    def first(xpath: str) -> str | None:
        values = root.xpath(xpath, namespaces=NS)
        if not values:
            return None
        value = values[0]
        return str(value).strip() or None

    return {
        "document_id": first("./h:id/@root"),
        "setid": first("./h:setId/@root"),
        "version_number": first("./h:versionNumber/@value"),
        "effective_time": first("./h:effectiveTime/@value"),
        "document_code": first("./h:code/@displayName"),
    }


def extract_zip_assets(zip_bytes: bytes, asset_dir: Path) -> tuple[dict[str, str], list[str]]:
    allowed_ext = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    mapping: dict[str, str] = {}
    warnings: list[str] = []
    total_uncompressed = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        infos = archive.infolist()
        if len(infos) > 500:
            raise LabelError("SPL ZIP 文件数超过安全上限")
        image_index = 0
        for info in infos:
            posix = PurePosixPath(info.filename)
            if info.is_dir():
                continue
            if posix.is_absolute() or ".." in posix.parts:
                raise LabelError(f"SPL ZIP 含不安全路径: {info.filename}")
            total_uncompressed += info.file_size
            if info.file_size > 20 * 1024 * 1024 or total_uncompressed > 150 * 1024 * 1024:
                raise LabelError("SPL ZIP 解压大小超过安全上限")
            ext = posix.suffix.lower()
            if ext not in allowed_ext:
                continue
            image_index += 1
            media_type = mimetypes.types_map.get(ext, "application/octet-stream")
            if not media_type.startswith("image/"):
                continue
            raw = archive.read(info)
            stem = safe_slug(posix.stem, fallback=f"image-{image_index}")[:70]
            target_name = f"{image_index:03d}-{stem}{ext}"
            target = asset_dir / target_name
            write_bytes(target, raw)
            mapping[posix.as_posix().lower()] = target_name
            mapping[posix.name.lower()] = target_name
    if not mapping:
        warnings.append("SPL ZIP 未包含可用图片")
    return mapping, warnings


def _local_name(node) -> str:
    tag = getattr(node, "tag", "")
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _render_children(node, media_refs: dict[str, str]) -> str:
    pieces = [html.escape(node.text or "")]
    for child in node:
        pieces.append(_render_narrative(child, media_refs))
        pieces.append(html.escape(child.tail or ""))
    return "".join(pieces)


def _safe_span(value: str | None) -> str | None:
    if value and re.fullmatch(r"[1-9][0-9]{0,2}", value):
        return value
    return None


def _render_narrative(node, media_refs: dict[str, str]) -> str:
    name = _local_name(node)
    inner = _render_children(node, media_refs)
    if name in {"text", "excerpt", "highlight"}:
        return inner
    if name == "paragraph":
        return f"<p>{inner}</p>"
    if name == "br":
        return "<br>"
    if name == "list":
        tag = "ol" if (node.get("listType") or "").lower() == "ordered" else "ul"
        return f"<{tag}>{inner}</{tag}>"
    if name == "item":
        return f"<li>{inner}</li>"
    if name in {"table", "thead", "tbody", "tfoot", "tr", "caption"}:
        return f"<{name}>{inner}</{name}>"
    if name in {"td", "th"}:
        attrs = []
        for key in ("colspan", "rowspan"):
            value = _safe_span(node.get(key))
            if value:
                attrs.append(f' {key}="{value}"')
        return f"<{name}{''.join(attrs)}>{inner}</{name}>"
    if name == "content":
        styles = set((node.get("styleCode") or "").split())
        if "Bold" in styles:
            inner = f"<strong>{inner}</strong>"
        if "Italics" in styles:
            inner = f"<em>{inner}</em>"
        if "Underline" in styles:
            inner = f"<u>{inner}</u>"
        return inner
    if name in {"sup", "sub"}:
        return f"<{name}>{inner}</{name}>"
    if name == "footnote":
        return f"<small>{inner}</small>"
    if name == "footnoteRef":
        return f"<sup>{inner}</sup>"
    if name == "linkHtml":
        return inner
    if name == "renderMultiMedia":
        ref = (node.get("referencedObject") or "").strip()
        path_value = media_refs.get(ref)
        if path_value:
            return f'<figure><img src="{html.escape(path_value, quote=True)}" alt="说明书图像"></figure>'
        return '<p><em>[图像未包含；请查看官方 PDF]</em></p>'
    return inner


def render_spl_html(
    xml_bytes: bytes,
    *,
    title: str,
    source_url: str,
    asset_mapping: dict[str, str],
) -> tuple[str, int, dict]:
    root = parse_spl_xml(xml_bytes)
    media_refs: dict[str, str] = {}
    for media in root.xpath(".//h:observationMedia", namespaces=NS):
        media_id = (media.get("ID") or "").strip()
        refs = media.xpath(".//h:reference/@value", namespaces=NS)
        if not media_id or not refs:
            continue
        source_name = str(refs[0]).replace("\\", "/").lower()
        mapped = asset_mapping.get(source_name) or asset_mapping.get(PurePosixPath(source_name).name.lower())
        if mapped:
            media_refs[media_id] = f"assets/{mapped}"

    sections: list[str] = []
    for section in root.xpath(".//h:section", namespaces=NS):
        text_nodes = section.xpath("./h:text", namespaces=NS)
        if not text_nodes:
            continue
        section_title = " ".join(section.xpath("./h:title//text()", namespaces=NS)).strip()
        body = _render_narrative(text_nodes[0], media_refs).strip()
        if not body or not re.sub(r"<[^>]+>", "", body).strip():
            continue
        heading = f"<h2>{html.escape(section_title)}</h2>" if section_title else ""
        sections.append(f'<section class="section">{heading}{body}</section>')
    if len(sections) < 3:
        raise LabelError(f"SPL 仅解析到 {len(sections)} 个正文节，拒绝生成不完整 HTML")
    document = wrap_html(
        title=title,
        body_html="".join(sections),
        source_url=source_url,
        source_label="DailyMed SPL 的本地派生 HTML",
        derived_note="正文来自官方 XML；版式和图像请以官方 PDF 为准",
        language="en",
    )
    return document, len(sections), spl_metadata(root)


def finalize(root: Path, manifest: dict) -> dict:
    manifest_path = root / "manifest.json"
    write_json(manifest_path, manifest)
    verification = verify_manifest(root, manifest)
    write_json(root / "verification.json", verification)
    print(f"OK 输出目录: {root}")
    print(f"验证状态: {verification['status']}")
    for warning in verification["warnings"]:
        print(f"WARN {warning}")
    if verification["errors"]:
        for error in verification["errors"]:
            print(f"ERROR {error}", file=sys.stderr)
        raise LabelError("产物验证失败；文件已保留供诊断")
    return verification


def command_search(args: argparse.Namespace) -> None:
    candidates, metadata = dailymed_search(
        args.query,
        name_type=args.name_type,
        limit=args.limit,
        timeout=args.timeout,
    )
    if args.json:
        print(json.dumps({"metadata": metadata, "candidates": candidates}, ensure_ascii=False, indent=2))
    else:
        print_candidates(candidates)
        print(f"候选数: {len(candidates)}")


def command_fetch_dailymed(args: argparse.Namespace) -> None:
    candidate, search_meta = select_candidate(args)
    setid = candidate["setid"]
    root = prepare_output(args.out_dir)
    source_dir = root / "source"
    artifacts: list[dict] = []
    source_responses: list[dict] = []
    warnings: list[str] = []

    xml_url = f"{DAILYMED_API}/spls/{setid}.xml"
    xml_result = fetch_bytes(xml_url, allowed_hosts=DEFAULT_OFFICIAL_HOSTS, timeout=args.timeout)
    if detect_content_kind(xml_result.data, xml_result.content_type) != "xml":
        raise LabelError("DailyMed XML 接口返回了非 XML 内容")
    xml_path = source_dir / "label.xml"
    write_bytes(xml_path, xml_result.data)
    artifacts.append(
        artifact_entry(root, xml_path, role="official_spl_xml", media_type="application/xml", derived=False)
    )
    source_responses.append(
        {
            "role": "spl_xml",
            "requested_url": xml_result.requested_url,
            "final_url": xml_result.final_url,
            "content_type": xml_result.content_type,
        }
    )

    asset_mapping: dict[str, str] = {}
    zip_path: Path | None = None
    if args.format in {"html", "both"}:
        zip_url = f"https://dailymed.nlm.nih.gov/dailymed/downloadzipfile.cfm?setId={setid}"
        zip_result = fetch_bytes(zip_url, allowed_hosts=DEFAULT_OFFICIAL_HOSTS, timeout=args.timeout)
        if detect_content_kind(zip_result.data, zip_result.content_type) != "zip":
            raise LabelError("DailyMed ZIP 接口返回了非 ZIP 内容")
        zip_path = source_dir / "label.zip"
        write_bytes(zip_path, zip_result.data)
        artifacts.append(
            artifact_entry(root, zip_path, role="official_spl_zip", media_type="application/zip", derived=False)
        )
        source_responses.append(
            {
                "role": "spl_zip",
                "requested_url": zip_result.requested_url,
                "final_url": zip_result.final_url,
                "content_type": zip_result.content_type,
                "last_updated": zip_result.headers.get("x-dailymed-label-last-updated"),
            }
        )
        asset_mapping, asset_warnings = extract_zip_assets(zip_result.data, root / "assets")
        warnings.extend(asset_warnings)
        for asset_name in sorted(set(asset_mapping.values())):
            asset_path = root / "assets" / asset_name
            media_type = mimetypes.types_map.get(asset_path.suffix.lower(), "application/octet-stream")
            artifacts.append(
                artifact_entry(
                    root,
                    asset_path,
                    role="spl_media_asset",
                    media_type=media_type,
                    derived=True,
                    derived_from="source/label.zip",
                )
            )

    spl_meta = spl_metadata(parse_spl_xml(xml_result.data))
    if args.format in {"html", "both"}:
        html_document, section_count, spl_meta = render_spl_html(
            xml_result.data,
            title=candidate["title"],
            source_url=xml_url,
            asset_mapping=asset_mapping,
        )
        html_path = root / "label.html"
        write_text(html_path, html_document)
        artifacts.append(
            artifact_entry(
                root,
                html_path,
                role="derived_searchable_html",
                media_type="text/html",
                derived=True,
                derived_from="source/label.xml",
            )
        )
        spl_meta["rendered_section_count"] = section_count

    if args.format in {"pdf", "both"}:
        pdf_url = f"https://dailymed.nlm.nih.gov/dailymed/downloadpdffile.cfm?setId={setid}"
        pdf_result = fetch_bytes(pdf_url, allowed_hosts=DEFAULT_OFFICIAL_HOSTS, timeout=max(args.timeout, 60))
        if detect_content_kind(pdf_result.data, pdf_result.content_type) != "pdf":
            raise LabelError("DailyMed PDF 接口返回了非 PDF 内容")
        pdf_path = root / "label.pdf"
        write_bytes(pdf_path, pdf_result.data)
        artifacts.append(
            artifact_entry(root, pdf_path, role="official_pdf", media_type="application/pdf", derived=False)
        )
        source_responses.append(
            {
                "role": "official_pdf",
                "requested_url": pdf_result.requested_url,
                "final_url": pdf_result.final_url,
                "content_type": pdf_result.content_type,
                "content_disposition": pdf_result.headers.get("content-disposition"),
                "last_updated": pdf_result.headers.get("x-dailymed-label-last-updated"),
            }
        )

    manifest = {
        "schema_version": 1,
        "tool": {"name": "drug-label-html2pdf", "version": TOOL_VERSION},
        "created_at": utc_now(),
        "request": {
            "mode": "dailymed",
            "query": args.query,
            "requested_setid": args.setid,
            "selected_candidate_index": args.select,
            "arbitrary_sample_authorized": args.select is not None,
            "format": args.format,
            "name_type": args.name_type,
        },
        "source": {
            "provider": "DailyMed",
            "jurisdiction": "us",
            "authority": "U.S. National Library of Medicine",
            "candidate": candidate,
            "database_published_date": search_meta.get("db_published_date"),
            "spl": spl_meta,
            "extracted_asset_count": len(set(asset_mapping.values())),
            "responses": source_responses,
        },
        "artifacts": artifacts,
        "warnings": warnings,
        "medical_use_boundary": "Archived labeling only; not medical advice and not a substitute for product identity confirmation.",
    }
    finalize(root, manifest)


def host_source_label(host: str) -> str:
    if host.endswith("cde.org.cn"):
        return "CDE 官方来源"
    if host.endswith("nmpa.gov.cn"):
        return "NMPA 官方来源"
    if host.endswith("ema.europa.eu") or host.endswith("ec.europa.eu"):
        return "EMA/EU 官方来源"
    if host.endswith("fda.gov") or host.endswith("nlm.nih.gov"):
        return "FDA/NLM 官方来源"
    return "用户明确授权的官方来源"


def command_fetch_url(args: argparse.Namespace) -> None:
    allowed = set(DEFAULT_OFFICIAL_HOSTS)
    for host in args.allow_host:
        normalized = host.strip().lower().rstrip(".")
        if "://" in normalized or "/" in normalized or not normalized:
            raise LabelError(f"--allow-host 只接受域名: {host}")
        allowed.add(normalized)
    result = fetch_bytes(
        args.url,
        allowed_hosts=allowed,
        timeout=args.timeout,
        max_bytes=args.max_mb * 1024 * 1024,
    )
    kind = detect_content_kind(result.data, result.content_type)
    if kind not in {"pdf", "html", "xml"}:
        raise LabelError(f"不支持的来源类型: {kind} ({result.content_type or 'unknown content-type'})")

    root = prepare_output(args.out_dir)
    artifacts: list[dict] = []
    warnings: list[str] = []
    host = (urlparse(result.final_url).hostname or "unknown").lower()
    source_label = host_source_label(host)
    document_title = args.title or "药品说明书"

    if kind == "pdf":
        pdf_path = root / "label.pdf"
        write_bytes(pdf_path, result.data)
        artifacts.append(
            artifact_entry(root, pdf_path, role="official_pdf", media_type="application/pdf", derived=False)
        )
        if args.format in {"html", "both"}:
            html_document, pages, text_chars = pdf_text_to_html(
                pdf_path,
                title=document_title,
                source_url=result.final_url,
            )
            html_path = root / "label.html"
            write_text(html_path, html_document)
            artifacts.append(
                artifact_entry(
                    root,
                    html_path,
                    role="derived_pdf_text_html",
                    media_type="text/html",
                    derived=True,
                    derived_from="label.pdf",
                )
            )
            if text_chars < 30:
                warnings.append(f"官方 PDF 共 {pages} 页但文字层很少，HTML 可能不完整")
    elif kind == "html":
        source_path = root / "source" / "original.html"
        write_bytes(source_path, result.data)
        artifacts.append(
            artifact_entry(root, source_path, role="official_source_html", media_type="text/html", derived=False)
        )
        html_document, document_title, text_chars = sanitize_external_html(
            result.data,
            title=args.title,
            source_url=result.final_url,
        )
        html_path = root / "label.html"
        write_text(html_path, html_document)
        artifacts.append(
            artifact_entry(
                root,
                html_path,
                role="derived_sanitized_html",
                media_type="text/html",
                derived=True,
                derived_from="source/original.html",
            )
        )
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
        if text_chars < 2000:
            warnings.append(f"官方 HTML 正文只有 {text_chars} 字，请人工确认是否为完整说明书")
    else:
        root_xml = parse_spl_xml(result.data)
        if root_xml.tag != f"{{{HL7_NS}}}document":
            raise LabelError("通用 XML 转换不受支持；请提供 PDF/HTML 或使用 DailyMed 模式")
        source_path = root / "source" / "label.xml"
        write_bytes(source_path, result.data)
        artifacts.append(
            artifact_entry(root, source_path, role="official_spl_xml", media_type="application/xml", derived=False)
        )
        html_document, section_count, _ = render_spl_html(
            result.data,
            title=document_title,
            source_url=result.final_url,
            asset_mapping={},
        )
        html_path = root / "label.html"
        write_text(html_path, html_document)
        artifacts.append(
            artifact_entry(
                root,
                html_path,
                role="derived_searchable_html",
                media_type="text/html",
                derived=True,
                derived_from="source/label.xml",
            )
        )
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
        warnings.append(f"SPL HTML 转换共 {section_count} 节，未取得官方 ZIP 图片")

    manifest = {
        "schema_version": 1,
        "tool": {"name": "drug-label-html2pdf", "version": TOOL_VERSION},
        "created_at": utc_now(),
        "request": {
            "mode": "official_url",
            "url": args.url,
            "title": args.title,
            "jurisdiction": args.jurisdiction,
            "manufacturer": args.manufacturer,
            "approval_number": args.approval_number,
            "format": args.format,
            "explicitly_allowed_hosts": args.allow_host,
        },
        "source": {
            "provider": source_label,
            "jurisdiction": args.jurisdiction,
            "requested_url": result.requested_url,
            "final_url": result.final_url,
            "host": host,
            "content_type": result.content_type,
            "content_disposition": result.headers.get("content-disposition"),
            "last_modified": result.headers.get("last-modified"),
            "detected_kind": kind,
            "product_identity": {
                "title": args.title,
                "manufacturer": args.manufacturer,
                "approval_number": args.approval_number,
            },
        },
        "artifacts": artifacts,
        "warnings": warnings,
        "medical_use_boundary": "Archived labeling only; not medical advice and not a substitute for product identity confirmation.",
    }
    finalize(root, manifest)


def command_doctor(_: argparse.Namespace) -> None:
    checks = []
    for module in ("requests", "bs4", "lxml", "pymupdf"):
        try:
            imported = __import__(module)
            checks.append({"name": module, "status": "ok", "version": getattr(imported, "__version__", "available")})
        except Exception as exc:
            checks.append({"name": module, "status": "missing", "detail": str(exc)})
    try:
        from label_common import find_chrome

        chrome = str(find_chrome())
        checks.append({"name": "chrome", "status": "ok", "path": chrome})
    except LabelError as exc:
        checks.append({"name": "chrome", "status": "optional-missing", "detail": str(exc)})
    print(json.dumps({"tool_version": TOOL_VERSION, "checks": checks}, ensure_ascii=False, indent=2))
    if any(item["status"] == "missing" for item in checks):
        raise LabelError("必需运行依赖缺失")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="检查运行依赖")
    doctor.set_defaults(func=command_doctor)

    search = sub.add_parser("search-dailymed", help="按药名检索 DailyMed 候选")
    search.add_argument("--query", required=True)
    search.add_argument("--name-type", choices=["both", "generic", "brand"], default="both")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--timeout", type=float, default=35)
    search.add_argument("--json", action="store_true")
    search.set_defaults(func=command_search)

    fetch_dm = sub.add_parser("fetch-dailymed", help="下载 DailyMed 官方说明书")
    identity = fetch_dm.add_mutually_exclusive_group(required=True)
    identity.add_argument("--query")
    identity.add_argument("--setid")
    fetch_dm.add_argument(
        "--select",
        type=int,
        help="仅在用户明确授权任意样本测试时，从当前 query 结果按 1 起始序号选择；正常任务优先使用 SETID",
    )
    fetch_dm.add_argument("--name-type", choices=["both", "generic", "brand"], default="both")
    fetch_dm.add_argument("--limit", type=int, default=10)
    fetch_dm.add_argument(
        "--format",
        choices=["html", "pdf", "both"],
        required=True,
        help="用户明确选择的交付格式；不得默认",
    )
    fetch_dm.add_argument("--out-dir", required=True)
    fetch_dm.add_argument("--timeout", type=float, default=35)
    fetch_dm.set_defaults(func=command_fetch_dailymed)

    fetch_url = sub.add_parser("fetch-url", help="下载经过允许的官方 HTTPS PDF/HTML")
    fetch_url.add_argument("--url", required=True)
    fetch_url.add_argument("--title")
    fetch_url.add_argument("--jurisdiction", choices=["cn", "us", "eu", "other"], required=True)
    fetch_url.add_argument("--manufacturer", help="上市许可持有人或生产企业，用于来源清单中的产品身份")
    fetch_url.add_argument("--approval-number", help="批准文号或注册证号；未知时省略")
    fetch_url.add_argument(
        "--format",
        choices=["html", "pdf", "both"],
        required=True,
        help="用户明确选择的交付格式；不得默认",
    )
    fetch_url.add_argument("--out-dir", required=True)
    fetch_url.add_argument("--allow-host", action="append", default=[])
    fetch_url.add_argument("--timeout", type=float, default=35)
    fetch_url.add_argument("--max-mb", type=int, default=80)
    fetch_url.set_defaults(func=command_fetch_url)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
        return 0
    except AmbiguousCandidates as exc:
        print_candidates(exc.candidates)
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    except LabelError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
