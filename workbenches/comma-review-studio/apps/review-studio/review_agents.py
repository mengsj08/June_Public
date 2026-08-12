#!/usr/bin/env python3
"""Internal Review Agent registry for Comma Review Studio."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MANIFEST_ROOT = Path(__file__).with_name("review_agent_manifests")
BUNDLED_ACADEMIC_RUBRIC_PATH = MANIFEST_ROOT / "rubrics" / "academic-paper-review.md"
ACADEMIC_RUBRIC_PATH = BUNDLED_ACADEMIC_RUBRIC_PATH
ACADEMIC_MANIFEST_PATH = MANIFEST_ROOT / "academic-paper-review.json"
ACADEMIC_ADAPTER_ID = "academic-paper-review"
ACADEMIC_ADAPTER_VERSION = "internal-gate3"
ACADEMIC_PROFILE_ID = "primary"
ACADEMIC_OUTPUT_SCHEMA_VERSION = "academic-paper-review-result/v1"
REVIEW_AGENT_REGISTRY_VERSION = "comma-review-agent-registry/v1"
ACADEMIC_RUBRIC_CANONICAL_SHA256 = "sha256:3b247cac76feb8508445cb3b1eaa8d68f4bbb57a8eed74f47e4c512185352a48"
ACADEMIC_BUNDLED_RUBRIC_SHA256 = "sha256:1d554b019b15ff6c4462e3e6a6b1a6c320b2539ba1a1c06bfda5681424d6d9fe"


class ReviewAgentError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedReviewRequest:
    adapter_id: str
    adapter_version: str
    profile_id: str
    rubric_version: str
    output_schema_version: str
    prompt: str
    output_schema: dict
    review_input: dict
    manifest: dict


def sha256_path(path: str | Path) -> str:
    target = Path(path)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_json_hash(value: Any) -> str:
    return sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _clean_text(value: Any, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _installed_rubric_candidates() -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = []
    workspace_root = _repo_root()
    for root in (workspace_root, *workspace_root.parents):
        candidates.extend([
            (root / ".agents" / "skills" / "academic-paper-review" / "SKILL.md", "installed_skill"),
            (root / ".claude" / "skills" / "academic-paper-review" / "SKILL.md", "installed_skill"),
        ])
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser()
    candidates.extend([
        (codex_home / "skills" / "academic-paper-review" / "SKILL.md", "installed_skill"),
        (home / ".agents" / "skills" / "academic-paper-review" / "SKILL.md", "installed_skill"),
        (home / "skills" / "skills" / "academic-paper-review" / "SKILL.md", "installed_skill"),
        (
            home / "skills" / "skills" / "academic-paper-review-workbench"
            / "references" / "academic-paper-review.md",
            "installed_workbench_reference",
        ),
    ])
    return candidates


def _rubric_lookup_order() -> list[dict]:
    rows = [
        {"mode": mode, "path": str(path)}
        for path, mode in _installed_rubric_candidates()
    ]
    rows.append({
        "mode": "bundled_compatibility_reference",
        "path": str(BUNDLED_ACADEMIC_RUBRIC_PATH),
    })
    return rows


def _rubric_source() -> dict:
    candidates = [
        *_installed_rubric_candidates(),
        (BUNDLED_ACADEMIC_RUBRIC_PATH, "bundled_compatibility_reference"),
    ]
    seen: set[Path] = set()
    mismatches: list[str] = []
    for candidate, mode in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not resolved.is_file():
            continue
        digest = sha256_path(resolved)
        if digest in {ACADEMIC_RUBRIC_CANONICAL_SHA256, ACADEMIC_BUNDLED_RUBRIC_SHA256}:
            return {"path": str(resolved), "sha256": digest, "mode": mode}
        mismatches.append(f"{resolved} ({digest})")
    raise ReviewAgentError(
        "academic-paper-review rubric unavailable or hash mismatch; checked "
        + "; ".join([item["path"] for item in _rubric_lookup_order()])
        + (f"; mismatches: {'; '.join(mismatches)}" if mismatches else "")
    )


def _manifest_rubric_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = MANIFEST_ROOT / path
    return path.resolve()


def _load_manifest(path: Path) -> dict:
    if not path.is_file():
        raise ReviewAgentError(f"adapter manifest not found: {path}")
    with path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ReviewAgentError("adapter manifest must be an object")
    return manifest


def academic_paper_review_manifest() -> dict:
    manifest = _load_manifest(ACADEMIC_MANIFEST_PATH)
    if manifest.get("adapter_id") != ACADEMIC_ADAPTER_ID:
        raise ReviewAgentError("academic adapter manifest id mismatch")
    if manifest.get("adapter_version") != ACADEMIC_ADAPTER_VERSION:
        raise ReviewAgentError("academic adapter manifest version mismatch")
    if manifest.get("profile_id") != ACADEMIC_PROFILE_ID:
        raise ReviewAgentError("academic adapter profile mismatch")
    if manifest.get("output_schema_version") != ACADEMIC_OUTPUT_SCHEMA_VERSION:
        raise ReviewAgentError("academic adapter output schema mismatch")
    bundled = manifest.get("rubric_source") if isinstance(manifest.get("rubric_source"), dict) else {}
    bundled_path = _manifest_rubric_path(str(bundled.get("path") or ""))
    if not bundled_path.is_file():
        raise ReviewAgentError(f"bundled academic rubric not found: {bundled_path}")
    bundled_sha256 = sha256_path(bundled_path)
    if bundled.get("sha256") != bundled_sha256:
        raise ReviewAgentError("academic adapter bundled rubric source mismatch")
    if manifest.get("rubric_version") != ACADEMIC_RUBRIC_CANONICAL_SHA256:
        raise ReviewAgentError("academic adapter rubric version mismatch")
    rubric = _rubric_source()
    return {
        **manifest,
        "rubric_source": rubric,
        "bundled_rubric_source": {
            "path": str(bundled.get("path") or ""),
            "resolved_path": str(bundled_path),
            "sha256": bundled_sha256,
        },
        "rubric_lookup_order": _rubric_lookup_order(),
    }


def review_agent_result_schema() -> dict:
    finding_schema = {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "id": {"type": "string"},
            "section": {"type": "string"},
            "section_id": {"type": "string"},
            "scope_intent": {"type": "string", "enum": ["quote", "section", "document"]},
            "issue_family": {"type": "string"},
            "quote_text": {"type": "string"},
            "context_before": {"type": "string"},
            "context_after": {"type": "string"},
            "evidence_quotes": {"type": "array"},
            "issue": {"type": "string"},
            "action": {"type": "string"},
            "scientific_impact": {"type": "string"},
            "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
            "evidence_requirement": {"type": "string"},
            "rationale": {"type": "string"},
            "no_quote_required": {"type": "boolean"},
        },
        "required": ["issue_family", "issue", "action", "priority", "no_quote_required"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string", "const": ACADEMIC_OUTPUT_SCHEMA_VERSION},
            "summary": {"type": "string"},
            "recommendation": {"type": "string"},
            "confidence": {"type": "string"},
            "structured_sections": {"type": "object"},
            "metrics": {"type": "object"},
            "findings": {"type": "array", "items": finding_schema},
            "derived_artifacts": {"type": "array"},
        },
        "required": [
            "schema_version", "summary", "recommendation", "confidence",
            "structured_sections", "metrics", "findings", "derived_artifacts",
        ],
    }


def _strip_finding_host_state(finding: dict) -> dict:
    clean = dict(finding)
    for key in (
        "finding_state", "lifecycle_state", "workflow", "applied_comment_id",
        "applied_signature", "review_session_id", "review_run_id",
    ):
        clean.pop(key, None)
    return clean


def validate_review_agent_result(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise ReviewAgentError("ReviewAgentResult must be an object")
    if raw.get("schema_version") != ACADEMIC_OUTPUT_SCHEMA_VERSION:
        raise ReviewAgentError("ReviewAgentResult schema_version is unsupported")
    findings = raw.get("findings")
    if not isinstance(findings, list):
        raise ReviewAgentError("ReviewAgentResult findings must be an array")
    normalized_findings = []
    for index, item in enumerate(findings, 1):
        if not isinstance(item, dict):
            raise ReviewAgentError("ReviewAgentResult finding must be an object")
        finding = _strip_finding_host_state(item)
        if not finding.get("id"):
            finding["id"] = f"F{index:03d}"
        if not finding.get("issue") or not finding.get("action"):
            raise ReviewAgentError("ReviewAgentResult finding requires issue and action")
        finding["issue_family"] = _clean_text(finding.get("issue_family") or "other", 80)
        finding["priority"] = _clean_text(finding.get("priority") or "P2", 4)
        finding["scope_intent"] = _clean_text(finding.get("scope_intent") or "quote", 16)
        finding["no_quote_required"] = bool(finding.get("no_quote_required"))
        finding["decision"] = "accepted"
        normalized_findings.append(finding)
    return {
        "schema_version": ACADEMIC_OUTPUT_SCHEMA_VERSION,
        "summary": _clean_text(raw.get("summary"), 8000),
        "recommendation": _clean_text(raw.get("recommendation"), 120),
        "confidence": _clean_text(raw.get("confidence"), 80),
        "structured_sections": raw.get("structured_sections") if isinstance(raw.get("structured_sections"), dict) else {},
        "metrics": raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {},
        "findings": normalized_findings,
        "derived_artifacts": raw.get("derived_artifacts") if isinstance(raw.get("derived_artifacts"), list) else [],
    }


def derive_result_markdown(result: dict) -> str:
    lines = [
        "# Paper Review",
        "",
        "## Executive Summary",
        "",
        result.get("summary") or "",
        "",
        "## Recommendation",
        "",
        f"- Overall assessment: {result.get('recommendation') or 'not specified'}",
        f"- Confidence: {result.get('confidence') or 'not specified'}",
        "",
        "## Structured Sections",
    ]
    for key, value in (result.get("structured_sections") or {}).items():
        lines.extend(["", f"### {key}", "", json.dumps(value, ensure_ascii=False, indent=2)
                      if isinstance(value, (dict, list)) else str(value)])
    lines.extend(["", "## Metrics"])
    metrics = result.get("metrics") or {}
    if metrics:
        for key, value in metrics.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- not provided")
    lines.extend(["", "## Findings"])
    for finding in result.get("findings") or []:
        lines.extend([
            "",
            f"### {finding.get('id')} · {finding.get('priority', 'P2')}",
            "",
            f"- Issue family: {finding.get('issue_family') or 'other'}",
            f"- Issue: {finding.get('issue') or ''}",
            f"- Action: {finding.get('action') or ''}",
            f"- Scientific impact: {finding.get('scientific_impact') or ''}",
        ])
    return "\n".join(lines).strip() + "\n"


def _evidence_summary(evidence_sources: list[dict]) -> str:
    if not evidence_sources:
        return "(no original EvidenceSource was authorized)"
    rows = []
    for source in evidence_sources:
        source_meta = source.get("source") or {}
        rows.append("- " + json.dumps({
            "id": source.get("id"),
            "filename": source_meta.get("filename"),
            "sha256": source_meta.get("sha256"),
            "extraction_status": source.get("extraction_status"),
            "full_text_confirmed": bool(source.get("full_text_confirmed")),
        }, ensure_ascii=False, sort_keys=True))
    return "\n".join(rows)


def _build_prompt(*, document_body: str, document_path: str, document_rev: str,
                  instruction: str, review_input: dict, evidence_sources: list[dict]) -> str:
    rubric = _rubric_source()
    rubric_path = Path(rubric["path"])
    rubric_text = rubric_path.read_text(encoding="utf-8")
    schema_text = json.dumps(review_agent_result_schema(), ensure_ascii=False, indent=2)
    return f"""You are the internal Academic Paper Review agent for Comma Review Studio.
The host, not you, owns provider execution, anchoring, finding state, comments, and writeback.
Do not call tools, shell, web search, public literature lookup, or external connectors.
Return exactly one JSON object matching ReviewAgentResult and no Markdown fence.

Rubric source: {rubric_path}
Rubric sha256: {rubric["sha256"]}
Rubric mode: {rubric.get("mode") or "unknown"}
Output schema version: {ACADEMIC_OUTPUT_SCHEMA_VERSION}

Canonical review input JSON:
{json.dumps(review_input, ensure_ascii=False, indent=2)}

Authorized original EvidenceSources, if any:
{_evidence_summary(evidence_sources)}

ReviewAgentResult JSON schema:
{schema_text}

Rules:
- Include summary, recommendation, confidence, structured_sections, metrics, findings, and derived_artifacts.
- Findings must use resolver-compatible fields: scope_intent, section_id, quote_text, context_before, context_after, evidence_quotes, issue_family, scientific_impact, and no_quote_required.
- Do not output finding_state, lifecycle_state, workflow, comment ids, or writeback decisions.
- Use exact contiguous quotes from the canonical document when scope_intent is quote.
- Set no_quote_required=true only for section/document-level findings that do not need an exact quote.

Author instruction: {instruction or 'none'}

Canonical document: {document_path}; revision: {document_rev}

<ACADEMIC_RUBRIC>
{rubric_text}
</ACADEMIC_RUBRIC>

<DOCUMENT>
{document_body}
</DOCUMENT>"""


class AcademicPaperReviewAdapter:
    def __init__(self):
        self.manifest = academic_paper_review_manifest()

    def prepare_review_request(self, *, document_body: str, document_path: str,
                               document_rev: str, instruction: str,
                               review_input: dict, evidence_sources: list[dict]) -> PreparedReviewRequest:
        prompt = _build_prompt(
            document_body=document_body,
            document_path=document_path,
            document_rev=document_rev,
            instruction=instruction,
            review_input=review_input,
            evidence_sources=evidence_sources,
        )
        return PreparedReviewRequest(
            adapter_id=self.manifest["adapter_id"],
            adapter_version=self.manifest["adapter_version"],
            profile_id=self.manifest["profile_id"],
            rubric_version=self.manifest["rubric_version"],
            output_schema_version=self.manifest["output_schema_version"],
            prompt=prompt,
            output_schema=review_agent_result_schema(),
            review_input=review_input,
            manifest=self.manifest,
        )


class ReviewAgentRegistry:
    def __init__(self):
        self._adapters = {ACADEMIC_ADAPTER_ID: AcademicPaperReviewAdapter()}

    def get(self, adapter_id: str):
        adapter = self._adapters.get(adapter_id)
        if not adapter:
            raise ReviewAgentError(f"unknown review agent adapter: {adapter_id}")
        return adapter

    def manifests(self) -> list[dict]:
        return [adapter.manifest for adapter in self._adapters.values()]


def default_registry() -> ReviewAgentRegistry:
    return ReviewAgentRegistry()
