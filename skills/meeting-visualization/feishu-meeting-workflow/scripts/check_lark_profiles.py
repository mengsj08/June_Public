#!/usr/bin/env python3
"""Check which configured lark-cli profile can handle a meeting source.

This script only calls metadata commands: `profile list`, `config show`, and
`auth status`. It does not read the lark-cli config file directly and does not
print secrets or access tokens.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from urllib.parse import urlparse

from _safety import has_secret_content, scrub


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parents[0]
DEFAULT_CONFIG = SKILL_ROOT / "references" / "lark_profiles.example.json"


def infer_source_kind(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    lower = value.lower()
    if "/docx/" in lower or lower.startswith("docx:"):
        return "feishu_docx"
    if "/minutes/" in lower or lower.startswith("minute_token:"):
        return "feishu_minutes"
    if "vc" in lower or "meeting" in lower:
        return "feishu_meeting"
    return fallback


def infer_source_host(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(value.strip())
    return (parsed.netloc or "").lower()


def loads_lenient(text: str) -> Any | None:
    """Parse JSON even when lark-cli appends trailing lines.

    Some commands (e.g. `config show`) print a JSON object followed by a
    human-readable line such as `Config file path: ...`, which breaks a strict
    json.loads. Fall back to decoding the first JSON value found.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for index, char in enumerate(text):
        if char in "{[":
            try:
                obj, _ = json.JSONDecoder().raw_decode(text[index:])
                return obj
            except json.JSONDecodeError:
                continue
    return None


def run_json(argv: list[str]) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=18,
        )
    except FileNotFoundError:
        return None, "lark-cli not found"
    except subprocess.TimeoutExpired:
        return None, "command timed out"

    output = completed.stdout.strip() or completed.stderr.strip()
    if completed.returncode != 0 and not output:
        return None, f"command failed with exit code {completed.returncode}"
    data = loads_lenient(output)
    if data is None:
        return None, scrub(output[:800]) or f"command returned non-JSON output, exit code {completed.returncode}"
    return data, None


def load_config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("Profile config must be a JSON object.")
    return data


def scope_set(auth_status: dict[str, Any]) -> set[str]:
    """Collect granted scopes, tolerating both string and list shapes.

    Verified against lark-cli 1.0.39: `scope` is a space-separated string at both
    the top level and under identities.user. Lists and a `scopes` plural key are
    accepted defensively in case the shape changes.
    """
    user_identity = auth_status.get("identities", {}).get("user", {})
    candidates = [
        auth_status.get("scope"),
        auth_status.get("scopes"),
        user_identity.get("scope") if isinstance(user_identity, dict) else None,
        user_identity.get("scopes") if isinstance(user_identity, dict) else None,
    ]
    result: set[str] = set()
    for candidate in candidates:
        if isinstance(candidate, str):
            result |= {item for item in re.split(r"[\s,]+", candidate) if item}
        elif isinstance(candidate, list):
            result |= {str(item) for item in candidate if item}
    return result


def summarize_profile(
    profile_name: str,
    config_profiles: dict[str, dict[str, str]],
    source_requirement: dict[str, Any],
    source_host: str,
) -> dict[str, Any]:
    config_show, config_error = run_json(["lark-cli", "config", "show", "--profile", profile_name])
    auth_status, auth_error = run_json(["lark-cli", "auth", "status", "--profile", profile_name])

    config_show = config_show if isinstance(config_show, dict) else {}
    auth_status = auth_status if isinstance(auth_status, dict) else {}
    scopes = scope_set(auth_status)
    required_scopes = set(source_requirement.get("required_scopes", []))
    recommended_scopes = set(source_requirement.get("recommended_scopes", []))
    missing_required = sorted(required_scopes - scopes)
    missing_recommended = sorted(recommended_scopes - scopes)
    profile_config = config_profiles.get(profile_name, {})
    source_hosts = [host.lower() for host in profile_config.get("source_hosts", [])]
    host_match = bool(source_host and source_host in source_hosts)
    user_identity = auth_status.get("identities", {}).get("user", {})
    bot_identity = auth_status.get("identities", {}).get("bot", {})
    if not isinstance(user_identity, dict):
        user_identity = {}
    if not isinstance(bot_identity, dict):
        bot_identity = {}
    token_status = auth_status.get("tokenStatus") or user_identity.get("tokenStatus") or "unknown"
    # lark-cli 1.0.39: identities.<id>.status == "ready" + identities.<id>.available == true.
    user_ready = (user_identity.get("available") is True or user_identity.get("status") == "ready") and token_status in {
        "valid",
        "active",
        "ok",
    }
    bot_ready = bot_identity.get("available") is True or bot_identity.get("status") == "ready"
    can_refresh = bool(auth_status.get("refreshExpiresAt") or user_identity.get("refreshExpiresAt"))
    can_use = not missing_required and (user_ready or token_status == "needs_refresh")
    recommended_identity = "user"
    if not user_ready and bot_ready:
        recommended_identity = "bot"

    return {
        "profile": profile_name,
        "label": profile_config.get("label", ""),
        "app_id": config_show.get("appId") or auth_status.get("appId") or "",
        "active_user": config_show.get("users", ""),
        "expected_user": profile_config.get("expected_user", ""),
        "source_hosts": source_hosts,
        "source_host_match": host_match,
        "brand": config_show.get("brand") or auth_status.get("brand") or "",
        "default_as": auth_status.get("defaultAs", ""),
        "identity": auth_status.get("identity", ""),
        "user_status": user_identity.get("status", "unknown"),
        "user_token_status": token_status,
        "user_token_expires_at": auth_status.get("expiresAt") or user_identity.get("expiresAt") or "",
        "refresh_expires_at": auth_status.get("refreshExpiresAt") or user_identity.get("refreshExpiresAt") or "",
        "bot_status": bot_identity.get("status", "unknown"),
        "recommended_identity": recommended_identity,
        "required_scopes_present": sorted(required_scopes & scopes),
        "missing_required_scopes": missing_required,
        "missing_recommended_scopes": missing_recommended,
        "scope_count": len(scopes),
        "can_use_for_source": can_use,
        "needs_auth_refresh": token_status == "needs_refresh",
        "can_refresh": can_refresh,
        "errors": [item for item in [config_error, auth_error] if item],
    }


def choose_recommended(profiles: list[dict[str, Any]], source_host: str = "") -> str | None:
    usable = [profile for profile in profiles if profile["can_use_for_source"]]
    if not usable:
        return None
    if source_host:
        matched = [profile for profile in usable if profile.get("source_host_match")]
        if matched:
            ready_matched = [profile for profile in matched if not profile["needs_auth_refresh"]]
            if ready_matched:
                return ready_matched[0]["profile"]
            return matched[0]["profile"]
        if len(usable) > 1:
            return None
    ready = [profile for profile in usable if not profile["needs_auth_refresh"]]
    if ready:
        return ready[0]["profile"]
    return usable[0]["profile"]


def recommended_identity_for(profiles: list[dict[str, Any]], profile_name: str | None) -> str | None:
    if not profile_name:
        return None
    for profile in profiles:
        if profile["profile"] == profile_name:
            return profile.get("recommended_identity") or "user"
    return None


def print_table(result: dict[str, Any]) -> None:
    print(f"source_kind: {result['source_kind']}")
    print(f"source_host: {result['source_host'] or '-'}")
    print(f"description: {result['description']}")
    print(f"recommended_profile: {result['recommended_profile'] or 'none'}")
    print(f"recommended_identity: {result['recommended_identity'] or 'none'}")
    print("")
    print("| profile | source host | user | user token | bot | identity | required scopes | missing required | recommendation |")
    print("|---|---|---|---|---|---|---|---|---|")
    for profile in result["profiles"]:
        required = ", ".join(profile["required_scopes_present"]) or "-"
        missing = ", ".join(profile["missing_required_scopes"]) or "-"
        if profile["can_use_for_source"] and not profile["needs_auth_refresh"]:
            recommendation = "可直接使用"
        elif profile["can_use_for_source"] and profile["needs_auth_refresh"]:
            recommendation = "可用但需刷新用户授权"
        else:
            recommendation = "缺少必要 scope"
        print(
            "| {profile} | {host} | {user} | {token} | {bot} | {identity} | {required} | {missing} | {recommendation} |".format(
                profile=profile["profile"],
                host="match" if profile.get("source_host_match") else "-",
                user=profile["active_user"] or profile["expected_user"] or "-",
                token=profile["user_token_status"],
                bot=profile["bot_status"],
                identity=profile["recommended_identity"],
                required=required,
                missing=missing,
                recommendation=recommendation,
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Check lark-cli profile permissions for a meeting source.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument(
        "--source-kind",
        default="feishu_minutes",
        choices=["feishu_docx", "feishu_minutes", "feishu_meeting", "local_media"],
    )
    parser.add_argument("--source-ref", help="Optional source reference used only to infer source kind.")
    parser.add_argument("--profile", action="append", help="Profile name to check. Defaults to configured profiles.")
    parser.add_argument("--format", choices=["json", "table"], default="json")
    args = parser.parse_args()

    if args.source_ref and has_secret_content(args.source_ref):
        raise SystemExit("Refusing secret-like source reference.")

    config = load_config(Path(args.config).expanduser())
    source_kind = infer_source_kind(args.source_ref, args.source_kind)
    source_host = infer_source_host(args.source_ref)
    requirements = config.get("source_requirements", {})
    if source_kind not in requirements:
        raise SystemExit(f"No source requirement configured for: {source_kind}")
    source_requirement = requirements[source_kind]

    configured_profiles = {
        item["name"]: item for item in config.get("profiles", []) if isinstance(item, dict) and item.get("name")
    }
    profiles = args.profile or list(configured_profiles.keys())
    if not profiles:
        profile_list, error = run_json(["lark-cli", "profile", "list"])
        if error:
            raise SystemExit(error)
        profiles = [item["name"] for item in profile_list or [] if item.get("name")]

    summaries = [
        summarize_profile(profile, configured_profiles, source_requirement, source_host) for profile in profiles
    ]
    recommended_profile = choose_recommended(summaries, source_host)
    result = {
        "source_kind": source_kind,
        "source_host": source_host,
        "description": source_requirement.get("description", ""),
        "required_scopes": source_requirement.get("required_scopes", []),
        "recommended_scopes": source_requirement.get("recommended_scopes", []),
        "recommended_profile": recommended_profile,
        "recommended_identity": recommended_identity_for(summaries, recommended_profile),
        "profiles": summaries,
    }

    if args.format == "table":
        print_table(result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
