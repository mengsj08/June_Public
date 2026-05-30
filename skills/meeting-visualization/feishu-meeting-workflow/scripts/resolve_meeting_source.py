#!/usr/bin/env python3
"""Resolve a Feishu meeting source to the original meeting transcript.

If the input is an AI notes doc, the resolver fetches the notes only to locate
the "Meeting transcript" docx link, then fetches that transcript as the primary
source. If the input is already a transcript doc, it fetches it directly.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from check_lark_profiles import (
    infer_source_host,
    infer_source_kind,
    load_config,
    summarize_profile,
    choose_recommended,
    recommended_identity_for,
    run_json,
)
from _safety import is_secret_file


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parents[0]
DEFAULT_CONFIG = SKILL_ROOT / "references" / "lark_profiles.example.json"
DEFAULT_RUNTIME_ROOT = Path.cwd() / "meeting-runtime"

DOC_LINK_RE = re.compile(r"\[([^\]]+)\]\((https://[^)]+/(?:docx|minutes)/[A-Za-z0-9]+)\)")
MINUTES_URL_RE = re.compile(r"/minutes/([a-z0-9]+)")
MINUTE_TOKEN_PREFIX = "minute_token:"
TRANSCRIPT_NAME_HINTS = ("transcript", "文字记录", "纪要", "minute")
TITLE_RE = re.compile(r"<title>(.*?)</title>|^#\s+(.*)$", re.M)


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "meeting-source"


def safe_path(path: Path) -> Path:
    if is_secret_file(path):
        raise SystemExit(f"Refusing secret-like path: {path}")
    return path


def extract_title(markdown: str) -> str:
    match = TITLE_RE.search(markdown)
    if not match:
        return ""
    return (match.group(1) or match.group(2) or "").strip()


def is_meeting_transcript(markdown: str) -> bool:
    title = extract_title(markdown).lower()
    if "meeting transcript" in title or "文字记录" in title:
        return True
    return bool(re.search(r"^Speaker\s+\d+\s+\d{2}:\d{2}:\d{2}", markdown, re.M))


def extract_meeting_transcript_link(markdown: str, original_url: str = "") -> str | None:
    lower = markdown.lower()
    anchor = lower.find("meeting transcript")
    search_area = markdown[anchor:] if anchor >= 0 else markdown
    for _label, url in DOC_LINK_RE.findall(search_area):
        if url != original_url:
            return url
    for label, url in DOC_LINK_RE.findall(markdown):
        if ("transcript" in label.lower() or "文字记录" in label) and url != original_url:
            return url
    return None


def extract_minute_token(source_ref: str) -> str | None:
    """Return the minute token if source_ref is a Feishu minutes URL or token.

    lark-cli requires minute tokens to be lowercase alphanumeric.
    """
    text = (source_ref or "").strip()
    if text.startswith(MINUTE_TOKEN_PREFIX):
        token = text[len(MINUTE_TOKEN_PREFIX):].strip()
        return token if re.fullmatch(r"[a-z0-9]+", token) else None
    match = MINUTES_URL_RE.search(text)
    return match.group(1) if match else None


def pick_transcript_artifact(output_dir: Path) -> Path | None:
    """Pick the most transcript-like artifact written by `lark-cli vc +notes`.

    Prefers a filename hinting at a transcript, then markdown/text over JSON,
    then larger files. The exact artifact filenames are produced by lark-cli and
    are not guaranteed, so an explicit --minutes-artifact override is supported.
    """
    files = [path for path in output_dir.rglob("*") if path.is_file()]
    text_like = [path for path in files if path.suffix.lower() in {".md", ".txt", ".json"}]
    pool = text_like or files
    if not pool:
        return None

    def score(path: Path) -> tuple[int, int, int]:
        name = path.name.lower()
        hinted = 0 if any(hint in name for hint in TRANSCRIPT_NAME_HINTS) else 1
        ext_rank = {".md": 0, ".txt": 1, ".json": 2}.get(path.suffix.lower(), 3)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        return (hinted, ext_rank, -size)

    return sorted(pool, key=score)[0]


def _minutes_json_to_text(payload: Any) -> str:
    """Best-effort extraction of transcript text from an unknown minutes JSON shape."""

    def from_node(node: Any) -> str:
        if isinstance(node, dict):
            for key in ("transcript", "content", "text", "sentences", "paragraphs"):
                if key in node:
                    sub = from_node(node[key])
                    if sub.strip():
                        return sub
            data = node.get("data")
            if isinstance(data, (dict, list)):
                return from_node(data)
            return ""
        if isinstance(node, list):
            parts: list[str] = []
            for item in node:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("sentence") or item.get("content")
                    parts.append(text if isinstance(text, str) else from_node(item))
            return "\n".join(part for part in parts if part)
        if isinstance(node, str):
            return node
        return ""

    return from_node(payload).strip()


def read_transcript_artifact(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        try:
            return _minutes_json_to_text(json.loads(raw))
        except json.JSONDecodeError:
            return ""
    return raw


def run_lark_notes(token: str, identity: str, output_dir: Path, profile: str | None) -> tuple[bool, str | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    argv = [
        "lark-cli",
        "vc",
        "+notes",
        "--minute-tokens",
        token,
        "--as",
        identity or "user",
        "--output-dir",
        str(output_dir),
        "--overwrite",
        "--format",
        "json",
    ]
    if profile:
        argv += ["--profile", profile]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        return False, "lark-cli not found"

    output = completed.stdout.strip() or completed.stderr.strip()
    try:
        data: Any = json.loads(output)
    except json.JSONDecodeError:
        data = None
    wrote_files = any(path.is_file() for path in output_dir.rglob("*"))
    if isinstance(data, dict) and data.get("ok") is False and not wrote_files:
        return False, json.dumps(data.get("error", data), ensure_ascii=False)[:1200]
    if completed.returncode != 0 and not wrote_files:
        return False, output[:1200] or f"exit code {completed.returncode}"
    return True, None


def fetch_minutes_to_markdown(
    token: str,
    profile: str | None,
    identity: str,
    source_dir: Path,
    artifact_override: str | None,
) -> tuple[str, dict[str, Any]]:
    notes_dir = source_dir / "minutes" / token
    if artifact_override:
        artifact = Path(artifact_override).expanduser()
        if not artifact.is_file():
            raise SystemExit(f"--minutes-artifact not found: {artifact}")
    else:
        ok, error = run_lark_notes(token, identity or "user", notes_dir, profile)
        if not ok:
            raise SystemExit(f"lark-cli vc +notes failed for minute token {token}: {error}")
        artifact = pick_transcript_artifact(notes_dir)
        if not artifact:
            raise SystemExit(
                f"vc +notes wrote no readable artifact under {notes_dir}. "
                "Inspect that directory and pass --minutes-artifact <file>, or export the "
                "minutes to a Meeting transcript docx and pass that docx link instead."
            )
    content = read_transcript_artifact(artifact)
    if not content.strip():
        raise SystemExit(
            f"Selected minutes artifact has no extractable transcript text: {artifact}. "
            "Pass --minutes-artifact <file> pointing at the transcript, or use a transcript docx."
        )
    provenance = {
        "minute_token": token,
        "notes_dir": "" if artifact_override else str(notes_dir),
        "artifact_path": str(artifact),
        "command": "lark-cli vc +notes --minute-tokens <token> --as user --output-dir <notes_dir> --overwrite --format json",
    }
    return content, provenance


def run_lark_fetch(doc_url: str, profile: str, identity: str) -> tuple[dict[str, Any] | None, str | None]:
    argv = [
        "lark-cli",
        "docs",
        "+fetch",
        "--api-version",
        "v2",
        "--profile",
        profile,
        "--as",
        identity,
        "--doc",
        doc_url,
        "--doc-format",
        "markdown",
    ]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=45, check=False)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except FileNotFoundError:
        return None, "lark-cli not found"

    output = completed.stdout.strip() or completed.stderr.strip()
    if completed.returncode != 0:
        return None, output[:1200] or f"exit code {completed.returncode}"
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None, output[:1200] or "non-json lark-cli output"
    if not data.get("ok"):
        return None, json.dumps(data.get("error", data), ensure_ascii=False)[:1200]
    return data, None


def fetch_with_readonly_fallback(doc_url: str, profile: str, identity: str) -> tuple[dict[str, Any], str, list[dict[str, str]]]:
    attempts: list[dict[str, str]] = []
    for candidate_identity in [identity, "bot"]:
        if candidate_identity in {attempt["identity"] for attempt in attempts}:
            continue
        for attempt_no in range(1, 3):
            data, error = run_lark_fetch(doc_url, profile, candidate_identity)
            attempts.append(
                {
                    "identity": candidate_identity,
                    "attempt": str(attempt_no),
                    "status": "ok" if data else "error",
                    "error": error or "",
                }
            )
            if data:
                return data, candidate_identity, attempts
            if error and not re.search(r"EOF|timeout|temporarily|network", error, re.I):
                break
    raise SystemExit("Unable to fetch document with user or bot identity: " + json.dumps(attempts, ensure_ascii=False))


def choose_profile_candidates(source_ref: str, config_path: Path) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    config = load_config(config_path)
    source_kind = infer_source_kind(source_ref, "feishu_docx")
    source_host = infer_source_host(source_ref)
    requirements = config["source_requirements"][source_kind]
    configured_profiles = {
        item["name"]: item for item in config.get("profiles", []) if isinstance(item, dict) and item.get("name")
    }
    profile_names = list(configured_profiles.keys())
    if not profile_names:
        profile_list, error = run_json(["lark-cli", "profile", "list"])
        if error:
            raise SystemExit(error)
        profile_names = [item["name"] for item in profile_list or [] if isinstance(item, dict) and item.get("name")]

    summaries = [
        summarize_profile(profile, configured_profiles, requirements, source_host)
        for profile in profile_names
    ]
    profile = choose_recommended(summaries, source_host)
    identity = recommended_identity_for(summaries, profile)

    candidates: list[tuple[str, str]] = []
    if profile and identity:
        candidates.append((profile, identity))

    def sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
        return (
            0 if item.get("source_host_match") else 1,
            0 if item.get("can_use_for_source") and not item.get("needs_auth_refresh") else 1,
            item.get("profile", ""),
        )

    for item in sorted(summaries, key=sort_key):
        item_profile = item.get("profile")
        item_identity = item.get("recommended_identity") or "user"
        if not item_profile or not item.get("can_use_for_source"):
            continue
        candidate = (item_profile, item_identity)
        if candidate not in candidates:
            candidates.append(candidate)

    if not candidates:
        raise SystemExit("No usable lark-cli profile found for source.")

    return candidates, {
        "source_kind": source_kind,
        "source_host": source_host,
        "recommended_profile": profile,
        "recommended_identity": identity,
        "profiles": summaries,
    }


def document_from_response(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("data", {}).get("document", {})


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def resolve_runtime_dir(args: argparse.Namespace, case_id: str) -> Path:
    return safe_path(Path(args.runtime_dir).expanduser() if args.runtime_dir else DEFAULT_RUNTIME_ROOT / case_id)


def resolve_minutes_source(args: argparse.Namespace, token: str) -> dict[str, Any]:
    source_ref = args.source_ref
    profile_check: dict[str, Any] = {}
    if args.profile:
        profile, identity = args.profile, (args.identity or "user")
    else:
        candidates, profile_check = choose_profile_candidates(
            f"{MINUTE_TOKEN_PREFIX}{token}", Path(args.config).expanduser()
        )
        profile, identity = candidates[0]

    case_id = args.case_id or f"{dt.date.today().isoformat()}-{slugify('minutes-' + token[:8])}"
    runtime_dir = resolve_runtime_dir(args, case_id)
    source_dir = runtime_dir / "source"
    transcript_content, minutes_provenance = fetch_minutes_to_markdown(
        token, profile, identity, source_dir, args.minutes_artifact
    )

    title = extract_title(transcript_content) or f"minutes-{token[:8]}"
    transcript_path = source_dir / "meeting_transcript.md"
    resolution_path = source_dir / "source_resolution.json"
    write_text(transcript_path, transcript_content)

    result = {
        "case_id": case_id,
        "source_ref": source_ref,
        "source_kind": "feishu_minutes",
        "source_host": infer_source_host(source_ref),
        "profile": profile,
        "entry_identity": identity,
        "transcript_identity": identity,
        "input_is_transcript": True,
        "ai_notes_document_id": None,
        "ai_notes_revision_id": None,
        "transcript_url": source_ref,
        "transcript_document_id": None,
        "transcript_revision_id": None,
        "transcript_title": title,
        "transcript_path": str(transcript_path),
        "resolution_path": str(resolution_path),
        "minute_token": token,
        "minutes_provenance": minutes_provenance,
        "profile_check": profile_check,
        "attempts": {},
    }
    write_text(resolution_path, json.dumps(result, ensure_ascii=False, indent=2))
    return result


def resolve_source(args: argparse.Namespace) -> dict[str, Any]:
    source_ref = args.source_ref

    direct_token = extract_minute_token(source_ref)
    if direct_token:
        return resolve_minutes_source(args, direct_token)

    profile_check: dict[str, Any] = {}
    if args.profile:
        profile_candidates = [(args.profile, args.identity or "user")]
    else:
        profile_candidates, profile_check = choose_profile_candidates(source_ref, Path(args.config).expanduser())

    errors: list[dict[str, str]] = []
    for profile, identity in profile_candidates:
        try:
            first_data, first_identity, first_attempts = fetch_with_readonly_fallback(source_ref, profile, identity)
            first_doc = document_from_response(first_data)
            first_content = first_doc.get("content", "")
            if not isinstance(first_content, str) or not first_content.strip():
                raise SystemExit("Fetched document has no content.")

            input_is_transcript = is_meeting_transcript(first_content)
            transcript_url = source_ref if input_is_transcript else extract_meeting_transcript_link(first_content, source_ref)

            if not transcript_url:
                raise SystemExit("Input appears to be AI notes, but no Meeting transcript docx/minutes link was found.")

            minutes_link_token = None if input_is_transcript else extract_minute_token(transcript_url)
            if input_is_transcript:
                transcript_doc = first_doc
                transcript_content = first_content
                transcript_identity = first_identity
                transcript_attempts = first_attempts
                ai_notes_doc = None
            elif minutes_link_token:
                # AI notes pointed at a Feishu minutes transcript; fetch deferred until runtime_dir is known.
                transcript_doc = {}
                transcript_content = None
                transcript_identity = first_identity
                transcript_attempts = []
                ai_notes_doc = first_doc
            else:
                transcript_data, transcript_identity, transcript_attempts = fetch_with_readonly_fallback(
                    transcript_url, profile, first_identity
                )
                transcript_doc = document_from_response(transcript_data)
                transcript_content = transcript_doc.get("content", "")
                ai_notes_doc = first_doc
            break
        except SystemExit as exc:
            errors.append({"profile": profile, "identity": identity, "error": str(exc)})
    else:
        raise SystemExit("Unable to fetch transcript with available profiles: " + json.dumps(errors, ensure_ascii=False))

    title = extract_title(transcript_content or "") or extract_title(first_content) or "meeting-transcript"
    case_id = args.case_id or f"{dt.date.today().isoformat()}-{slugify(title)}"
    runtime_dir = resolve_runtime_dir(args, case_id)
    source_dir = runtime_dir / "source"

    minutes_provenance: dict[str, Any] | None = None
    if minutes_link_token:
        transcript_content, minutes_provenance = fetch_minutes_to_markdown(
            minutes_link_token, profile, transcript_identity, source_dir, args.minutes_artifact
        )
        title = extract_title(transcript_content) or title

    if not isinstance(transcript_content, str) or not transcript_content.strip():
        raise SystemExit("Transcript document has no content.")

    transcript_path = source_dir / "meeting_transcript.md"
    resolution_path = source_dir / "source_resolution.json"
    write_text(transcript_path, transcript_content)
    if ai_notes_doc:
        write_text(source_dir / "ai_notes.md", first_content)

    result = {
        "case_id": case_id,
        "source_ref": source_ref,
        "source_kind": "feishu_minutes" if minutes_link_token else "feishu_docx",
        "source_host": infer_source_host(source_ref),
        "profile": profile,
        "entry_identity": first_identity,
        "transcript_identity": transcript_identity,
        "input_is_transcript": input_is_transcript,
        "ai_notes_document_id": ai_notes_doc.get("document_id") if ai_notes_doc else None,
        "ai_notes_revision_id": ai_notes_doc.get("revision_id") if ai_notes_doc else None,
        "transcript_url": transcript_url,
        "transcript_document_id": transcript_doc.get("document_id"),
        "transcript_revision_id": transcript_doc.get("revision_id"),
        "transcript_title": title,
        "transcript_path": str(transcript_path),
        "resolution_path": str(resolution_path),
        "minutes_provenance": minutes_provenance,
        "profile_check": profile_check,
        "attempts": {
            "entry": first_attempts,
            "transcript": transcript_attempts,
        },
    }
    write_text(resolution_path, json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve Feishu AI notes/docx to the original meeting transcript.")
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--identity", choices=["user", "bot"])
    parser.add_argument("--case-id")
    parser.add_argument("--runtime-dir")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument(
        "--minutes-artifact",
        help="For Feishu minutes sources: explicit transcript artifact file to use instead of auto-picking from vc +notes output.",
    )
    args = parser.parse_args()

    result = resolve_source(args)
    print(json.dumps({
        "case_id": result["case_id"],
        "source_kind": result["source_kind"],
        "profile": result["profile"],
        "entry_identity": result["entry_identity"],
        "transcript_identity": result["transcript_identity"],
        "input_is_transcript": result["input_is_transcript"],
        "transcript_url": result["transcript_url"],
        "transcript_document_id": result["transcript_document_id"],
        "transcript_revision_id": result["transcript_revision_id"],
        "transcript_title": result["transcript_title"],
        "transcript_path": result["transcript_path"],
        "resolution_path": result["resolution_path"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
