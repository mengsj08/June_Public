#!/usr/bin/env python3
"""Offline self-test for feishu-meeting-workflow scripts.

Runs without lark-cli, network, or any external service. Exercises the pure
logic (transcript detection, link extraction, meeting classification) and the
two behaviours that most affect reliability:

  - meeting_case.py must NOT clobber analysis files on re-run (P0-1).
  - render_meeting_html.py must NOT embed Feishu private doc/media URLs.

Usage:
    python3 scripts/selftest.py
Exit code 0 = all passed, 1 = at least one failure.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
FIXTURES = SKILL_DIR / "fixtures"
PY = sys.executable

sys.path.insert(0, str(SCRIPT_DIR))
import _safety as saf  # noqa: E402
import check_lark_profiles as clp  # noqa: E402
import meeting_case as mc  # noqa: E402
import resolve_meeting_source as rms  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def main() -> int:
    ai_notes = (FIXTURES / "sample_ai_notes.md").read_text(encoding="utf-8")
    transcript = (FIXTURES / "sample_transcript.md").read_text(encoding="utf-8")

    # 1. transcript vs ai-notes detection
    check("is_meeting_transcript(transcript) == True", rms.is_meeting_transcript(transcript))
    check("is_meeting_transcript(ai_notes) == False", not rms.is_meeting_transcript(ai_notes))

    # 2. extract the Meeting transcript docx link from AI notes
    link = rms.extract_meeting_transcript_link(ai_notes)
    check(
        "extract_meeting_transcript_link finds transcript docx",
        bool(link) and "/docx/TRANSCRIPT" in (link or ""),
        link or "None",
    )

    # 3. meeting classification
    check("classify_meeting auto -> internal", mc.classify_meeting("内部周会 复盘 排期 迭代", "auto") == "internal")
    check("classify_meeting explicit override wins", mc.classify_meeting("客户拜访 报价", "internal") == "internal")

    # 3b. minutes source detection (P0-2)
    check(
        "extract_minute_token from /minutes/ URL",
        rms.extract_minute_token("https://demo.feishu.cn/minutes/obcnabc123def456") == "obcnabc123def456",
    )
    check(
        "extract_minute_token from minute_token: prefix",
        rms.extract_minute_token("minute_token:obcnxyz789") == "obcnxyz789",
    )
    check("extract_minute_token ignores /docx/ URL", rms.extract_minute_token("https://demo.feishu.cn/docx/abc123") is None)
    check(
        "extract_meeting_transcript_link follows a minutes link",
        rms.extract_meeting_transcript_link(
            "Meeting transcript: [文字记录](https://demo.feishu.cn/minutes/obcnmmm111)"
        ) == "https://demo.feishu.cn/minutes/obcnmmm111",
    )
    check(
        "read_transcript_artifact extracts text from minutes JSON",
        "你好世界" in rms._minutes_json_to_text({"data": {"transcript": {"sentences": [{"text": "你好世界"}]}}}),
    )
    with tempfile.TemporaryDirectory() as art_tmp:
        art_dir = Path(art_tmp)
        (art_dir / "meta.json").write_text("{}", encoding="utf-8")
        (art_dir / "ai_summary.md").write_text("摘要", encoding="utf-8")
        (art_dir / "transcript.md").write_text("逐字稿正文", encoding="utf-8")
        picked = rms.pick_transcript_artifact(art_dir)
        check("pick_transcript_artifact prefers transcript-named file", picked is not None and picked.name == "transcript.md", str(picked))

    # 3c. narrowed secret-file detection (P2-6)
    check("is_secret_file(.env)", saf.is_secret_file("/x/.env"))
    check("is_secret_file(credentials.json)", saf.is_secret_file("/x/credentials.json"))
    check("is_secret_file(id_rsa)", saf.is_secret_file("/x/id_rsa"))
    check("is_secret_file allows normal transcript in secret-named dir", not saf.is_secret_file("/work/secret-projects/transcript.md"))
    check("is_secret_file allows report.html", not saf.is_secret_file("/out/report.html"))

    # 3d. secret-content detection only fires on real secret shapes (P2-6)
    check("has_secret_content(app_secret=...)", saf.has_secret_content("app_secret=abc123"))
    check("has_secret_content(feishu user token)", saf.has_secret_content("u-abcdefghij1234567890wxyz"))
    check("has_secret_content ignores prose 'secret roadmap'", not saf.has_secret_content("we discussed our secret roadmap"))
    check("has_secret_content ignores a feishu docx URL", not saf.has_secret_content("https://demo.feishu.cn/docx/abc123"))

    # 3e. scrub broadened to bare token shapes (P2-7)
    scrubbed = saf.scrub("error: app_secret=TOPSECRETVALUE and token u-zzzzzzzzzzzzzzzzzzzzzz")
    check("scrub removes app_secret value", "TOPSECRETVALUE" not in scrubbed and "[redacted]" in scrubbed)
    check("scrub removes bare user token", "u-zzzzzzzzzzzzzzzzzzzzzz" not in scrubbed)

    # 3f. classify scoring no longer misroutes research meetings to presales (P2-8)
    research = "内部周会 复盘 排期 研发 客户 方案"
    check("classify_meeting research+客户 -> internal", mc.classify_meeting(research, "auto") == "internal", mc.classify_meeting(research, "auto"))
    check("classify_meeting genuine presales -> presales", mc.classify_meeting("客户 拜访 报价", "auto") == "presales")
    check("classify_meeting no signal -> special", mc.classify_meeting("你好 大家", "auto") == "special")

    # 3g. lenient JSON parsing tolerates lark-cli trailing lines (P1-4)
    parsed = clp.loads_lenient('{"appId":"x","users":"June"}\n\nConfig file path: /home/u/.lark-cli/config.json')
    check("loads_lenient parses JSON with trailing text", isinstance(parsed, dict) and parsed.get("users") == "June", str(parsed))
    check("scope_set parses space-separated string", clp.scope_set({"scope": "a:read b:write"}) == {"a:read", "b:write"})
    check("scope_set parses list under identities.user.scopes", clp.scope_set({"identities": {"user": {"scopes": ["x", "y"]}}}) == {"x", "y"})

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        case_root = tmp_path / "meeting-cases"
        runtime_root = tmp_path / "meeting-runtime"
        case_dir = case_root / "selftest-case"
        internal_brief = case_dir / "internal_brief.md"

        base_args = [
            PY,
            str(SCRIPT_DIR / "meeting_case.py"),
            "--case-id", "selftest-case",
            "--title", "自测会议",
            "--source-kind", "manual_text",
            "--input-file", str(FIXTURES / "sample_transcript.md"),
            "--meeting-type", "internal",
            "--case-root", str(case_root),
            "--runtime-root", str(runtime_root),
        ]

        # 4. case creation
        r1 = subprocess.run(base_args, capture_output=True, text=True)
        check("meeting_case.py creates case", r1.returncode == 0 and internal_brief.exists(), r1.stderr[-300:])

        # 5. re-run must NOT clobber analysis (P0-1)
        sentinel = "HUMAN-ANALYSIS-SENTINEL-人工分析请勿覆盖"
        internal_brief.write_text(sentinel, encoding="utf-8")
        r2 = subprocess.run(base_args, capture_output=True, text=True)
        survived = sentinel in internal_brief.read_text(encoding="utf-8")
        check("re-run preserves existing analysis (P0-1)", r2.returncode == 0 and survived, r2.stderr[-300:])

        # 6. --force intentionally regenerates the scaffold
        r3 = subprocess.run(base_args + ["--force"], capture_output=True, text=True)
        regenerated = sentinel not in internal_brief.read_text(encoding="utf-8")
        check("--force regenerates scaffold", r3.returncode == 0 and regenerated, r3.stderr[-300:])

        # 7. render produces HTML and redacts Feishu private URLs
        out_html = tmp_path / "report.html"
        private_analysis = tmp_path / "sample_analysis_with_private_media.md"
        private_media_host = "internal-api-drive-" + "stream.feishu.cn"
        dummy_auth_value = "DUMMY" + "NOTAREALCODE"
        private_auth_query = "auth" + f"code={dummy_auth_value}"
        private_analysis.write_text(
            (FIXTURES / "sample_analysis.md").read_text(encoding="utf-8")
            + f"\n\n![会议截图](https://{private_media_host}/media/xyz?{private_auth_query})\n",
            encoding="utf-8",
        )
        r4 = subprocess.run(
            [
                PY,
                str(SCRIPT_DIR / "render_meeting_html.py"),
                "--input", str(private_analysis),
                "--output", str(out_html),
                "--case", str(case_dir / "case.yaml"),
            ],
            capture_output=True,
            text=True,
        )
        html_text = out_html.read_text(encoding="utf-8") if out_html.exists() else ""
        check("render_meeting_html.py produces HTML", r4.returncode == 0 and "<html" in html_text, r4.stderr[-300:])
        check("private docx URL not embedded", "feishu.cn/docx/" not in html_text)
        check("signed media URL not embedded", "internal-api-drive-stream" not in html_text)
        check("authcode not leaked", "authcode" not in html_text and dummy_auth_value not in html_text)

        # 8. presales cases route to external pre-consult skill and write a full-flow handoff.
        fake_pre_consult = tmp_path / "fake-pre-consult"
        fake_pre_consult.mkdir()
        (fake_pre_consult / "SKILL.md").write_text("---\nname: crm\n---\n# fake crm\n", encoding="utf-8")
        presales_case_root = tmp_path / "presales-cases"
        presales_runtime_root = tmp_path / "presales-runtime"
        presales_case_dir = presales_case_root / "pre-consult-case"
        r5 = subprocess.run(
            [
                PY,
                str(SCRIPT_DIR / "meeting_case.py"),
                "--case-id", "pre-consult-case",
                "--title", "客户拜访 AI 落地咨询",
                "--source-kind", "manual_text",
                "--input-file", str(FIXTURES / "sample_transcript.md"),
                "--source-ref", "primary_transcript: /safe/runtime/source/meeting_transcript.md",
                "--meeting-type", "presales",
                "--customer-short-name", "测试客户",
                "--pre-consult-skill-path", str(fake_pre_consult),
                "--case-root", str(presales_case_root),
                "--runtime-root", str(presales_runtime_root),
            ],
            capture_output=True,
            text=True,
        )
        presales_case_yaml = presales_case_dir / "case.yaml"
        presales_handoff = presales_case_dir / "pre_consult_handoff.md"
        presales_customer = presales_case_dir / "customer_material.md"
        yaml_text = presales_case_yaml.read_text(encoding="utf-8") if presales_case_yaml.exists() else ""
        handoff_text = presales_handoff.read_text(encoding="utf-8") if presales_handoff.exists() else ""
        customer_text = presales_customer.read_text(encoding="utf-8") if presales_customer.exists() else ""
        check("pre-consult case scaffold succeeds", r5.returncode == 0, r5.stderr[-500:])
        check("case.yaml routes to pre_consult", 'customer_page_generator: "pre_consult"' in yaml_text, yaml_text)
        check("case.yaml records full pre-consult flow", 'pre_consult_flow: "full"' in yaml_text, yaml_text)
        check("case.yaml records pre-consult skill path", str(fake_pre_consult.resolve()) in yaml_text, yaml_text)
        check(
            "pre_consult_handoff.md contains five-stage flow",
            all(stage in handoff_text for stage in ["crm 会前", "crm 纪要", "crm 提问", "crm 成果", "crm 问卷"]),
            handoff_text,
        )
        check("pre_consult_handoff.md records output root", "pre-consult/agent_output" in handoff_text, handoff_text)
        check("pre_consult_handoff.md records customer short name", "测试客户" in handoff_text, handoff_text)
        check("pre_consult_handoff.md records transcript path", "sample_transcript.md" in handoff_text, handoff_text)
        check("new pre-consult route does not write crm_handoff.md", not (presales_case_dir / "crm_handoff.md").exists())
        check("customer_material excludes private URLs", "feishu.cn/" not in customer_text and "internal-api-drive-stream" not in customer_text)

    failures = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        suffix = f"  -- {detail}" if (not ok and detail) else ""
        print(f"[{'PASS' if ok else 'FAIL'}] {name}{suffix}")
    print(f"\n{len(RESULTS) - len(failures)}/{len(RESULTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
