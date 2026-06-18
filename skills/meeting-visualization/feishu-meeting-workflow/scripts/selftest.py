#!/usr/bin/env python3
"""Offline self-test for feishu-meeting-workflow scripts.

Runs without lark-cli, network, or any external service. Exercises the pure
logic (transcript detection, link extraction, meeting classification) and the
two behaviours that most affect reliability:

  - meeting_case.py must NOT clobber analysis files on re-run (P0-1).
  - render_meeting_html.py must NOT embed Feishu private doc/media URLs.
  - route/finalize/return must not pass an unresolved transcript source.

Usage:
    python3 scripts/selftest.py
Exit code 0 = all passed, 1 = at least one failure.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
FIXTURES = SKILL_DIR / "fixtures"
PY = sys.executable

sys.path.insert(0, str(SCRIPT_DIR))
import _safety as saf  # noqa: E402
import check_lark_profiles as clp  # noqa: E402
import meeting_case as mc  # noqa: E402
import finalize_route as fr  # noqa: E402,F401
import return_to_feishu as rtf  # noqa: E402
import resolve_meeting_source as rms  # noqa: E402
import route_context_reply as rcr  # noqa: E402

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
    check("is_getbiji_source detects d.biji.com", rms.is_getbiji_source("https://d.biji.com/GJFm4FSwh4A61OMX"))
    check(
        "getbiji_share_id_from_url extracts share_note id",
        rms.getbiji_share_id_from_url("https://biji.ddmaster.com/note/share_note/QxvWv9gxn4eZP?x=1") == "QxvWv9gxn4eZP",
    )
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

    with tempfile.TemporaryDirectory() as lark_tmp:
        lark_root = Path(lark_tmp)
        output_dir = lark_root / "source" / "minutes" / "obcnabc123"
        captured: dict[str, object] = {}

        class FakeCompleted:
            returncode = 0
            stdout = '{"ok": true}'
            stderr = ""

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["cwd"] = kwargs.get("cwd")
            (output_dir / "artifact" / "transcript.txt").parent.mkdir(parents=True, exist_ok=True)
            (output_dir / "artifact" / "transcript.txt").write_text("Speaker 1 00:00:01 你好", encoding="utf-8")
            return FakeCompleted()

        with mock.patch.object(rms.subprocess, "run", side_effect=fake_run):
            ok, error = rms.run_lark_notes("obcnabc123", "user", output_dir, "demo-profile")
        argv = captured.get("argv") if isinstance(captured.get("argv"), list) else []
        output_arg = argv[argv.index("--output-dir") + 1] if "--output-dir" in argv else ""
        check("run_lark_notes succeeds with fake lark-cli", ok and error is None, str(error))
        check("run_lark_notes passes relative output dir", output_arg == "minutes/obcnabc123", str(output_arg))
        cwd_value = captured.get("cwd")
        cwd_matches = Path(str(cwd_value)).resolve() == (lark_root / "source").resolve()
        check("run_lark_notes sets cwd to source dir", cwd_matches, str(cwd_value))

    with tempfile.TemporaryDirectory() as minutes_tmp:
        captured_minutes: dict[str, str] = {}

        def fake_choose(_source_ref, _config_path):
            return [("demo-profile", "bot")], {"recommended_identity": "bot"}

        def fake_fetch_minutes(_token, profile, identity, source_dir, _artifact):
            captured_minutes["profile"] = profile
            captured_minutes["identity"] = identity
            Path(source_dir).mkdir(parents=True, exist_ok=True)
            return "# Meeting transcript\n\nSpeaker 1 00:00:01 你好", {"ok": True}

        args = mock.Mock(
            source_ref="https://demo.feishu.cn/minutes/obcnabc123",
            profile=None,
            identity=None,
            config=str(SKILL_DIR / "references" / "lark_profiles.example.json"),
            case_id="minutes-identity-selftest",
            runtime_dir=minutes_tmp,
            minutes_artifact=None,
        )
        with mock.patch.object(rms, "choose_profile_candidates", side_effect=fake_choose):
            with mock.patch.object(rms, "fetch_minutes_to_markdown", side_effect=fake_fetch_minutes):
                rms.resolve_minutes_source(args, "obcnabc123")
        check(
            "resolve_minutes_source forces user identity",
            captured_minutes.get("profile") == "demo-profile" and captured_minutes.get("identity") == "user",
            str(captured_minutes),
        )

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
    check("scrub removes lark app/profile id", "cli_abc123" not in saf.scrub("profile cli_abc123"))

    # 3f. classify scoring no longer misroutes research meetings to presales (P2-8)
    research = "内部周会 复盘 排期 研发 客户 方案"
    check("classify_meeting research+客户 -> internal", mc.classify_meeting(research, "auto") == "internal", mc.classify_meeting(research, "auto"))
    check("classify_meeting partner signals -> partner", mc.classify_meeting("合作方 战略伙伴 技术合作", "auto") == "partner")
    check("classify_meeting school cooperation -> partner", mc.classify_meeting("学校合作 市场方向讨论", "auto") == "partner")
    check("classify_meeting genuine presales -> presales", mc.classify_meeting("客户 拜访 报价", "auto") == "presales")
    check("classify_meeting no signal -> special", mc.classify_meeting("你好 大家", "auto") == "special")

    # 3h. context-gate reply classification
    check("route_context_reply 默认 -> agent_default", rcr.classify_reply("默认")["route"] == "agent_default")
    check("route_context_reply 1 -> agent_default", rcr.classify_reply("1")["route"] == "agent_default")
    check("route_context_reply 直接分析 -> agent_default", rcr.classify_reply("直接分析")["route"] == "agent_default")
    check("route_context_reply 补资料 -> supplement", rcr.classify_reply("先补资料")["route"] == "supplement_materials")
    check("route_context_reply 2 -> supplement", rcr.classify_reply("2")["route"] == "supplement_materials")
    check("route_context_reply 查资料 -> supplement", rcr.classify_reply("查资料：团队知识库")["route"] == "supplement_materials")
    check("route_context_reply WOW-Claude -> wow_claude", rcr.classify_reply("WOW-Claude")["route"] == "wow_claude")
    check("route_context_reply 4 -> wow_claude", rcr.classify_reply("4")["route"] == "wow_claude")
    check("route_context_reply Claude -> wow_claude", rcr.classify_reply("Claude")["route"] == "wow_claude")
    check("route_context_reply 5 -> wow_codex", rcr.classify_reply("5")["route"] == "wow_codex")
    check("route_context_reply HTML -> customer_html_prompt", rcr.classify_reply("客户展示HTML")["route"] == "customer_html_prompt")
    check("route_context_reply 3 -> customer_html_prompt", rcr.classify_reply("3")["route"] == "customer_html_prompt")
    check("route_context_reply 客户页 -> customer_html_prompt", rcr.classify_reply("客户页")["route"] == "customer_html_prompt")
    check("route_context_reply 6 -> crm_skill", rcr.classify_reply("6")["route"] == "crm_skill")
    check("route_context_reply 客户洽谈Skill -> crm_skill", rcr.classify_reply("客户洽谈Skill")["route"] == "crm_skill")

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
        check("pre_consult_handoff.md records transcript path", "source/meeting_transcript.md" in handoff_text, handoff_text)
        check("new pre-consult route does not write crm_handoff.md", not (presales_case_dir / "crm_handoff.md").exists())
        check("customer_material excludes private URLs", "feishu.cn/" not in customer_text and "internal-api-drive-stream" not in customer_text)

        getbiji_case_root = tmp_path / "getbiji-cases"
        getbiji_runtime_root = tmp_path / "getbiji-runtime"
        r5b = subprocess.run(
            [
                PY,
                str(SCRIPT_DIR / "meeting_case.py"),
                "--case-id", "getbiji-case",
                "--title", "Get笔记公开来源自测",
                "--source-kind", "getbiji_note",
                "--input-text", "Speaker 1 00:00:01 你好",
                "--meeting-type", "internal",
                "--case-root", str(getbiji_case_root),
                "--runtime-root", str(getbiji_runtime_root),
            ],
            capture_output=True,
            text=True,
        )
        getbiji_yaml = getbiji_case_root / "getbiji-case" / "case.yaml"
        getbiji_yaml_text = getbiji_yaml.read_text(encoding="utf-8") if getbiji_yaml.exists() else ""
        check("meeting_case.py accepts getbiji_note source_kind", r5b.returncode == 0, r5b.stderr[-300:])
        check("case.yaml records getbiji_note", 'source_kind: "getbiji_note"' in getbiji_yaml_text, getbiji_yaml_text)

        # 9. context-gate route helper updates case.json and writes handoff files.
        context_case = tmp_path / "context-case"
        (context_case / "source").mkdir(parents=True)
        (context_case / "analysis").mkdir()
        (context_case / "source" / "meeting_transcript.md").write_text("Speaker 1 00:00:01 你好", encoding="utf-8")
        (context_case / "analysis" / "analysis_request.md").write_text("# request\n", encoding="utf-8")
        (context_case / "case.json").write_text(
            '{"title":"上下文闸口自测","analysis_status":"needs_user_context","analysis_stage":"meeting/context","paths":{"transcript":"source/meeting_transcript.md","analysis_request":"analysis/analysis_request.md"}}\n',
            encoding="utf-8",
        )
        r6 = subprocess.run(
            [
                PY,
                str(SCRIPT_DIR / "route_context_reply.py"),
                "--case-dir", str(context_case),
                "--reply", "默认",
            ],
            capture_output=True,
            text=True,
        )
        updated_case = (context_case / "case.json").read_text(encoding="utf-8")
        handoff = context_case / "analysis" / "agent_handoff.md"
        check("route_context_reply.py succeeds for 默认", r6.returncode == 0, r6.stderr[-300:])
        check("route_context_reply.py updates stage", "meeting/skill_route" in updated_case, updated_case)
        check("route_context_reply.py writes agent_handoff", handoff.exists() and "Default Agent Route" in handoff.read_text(encoding="utf-8"))

        # 10. Feishu return package prepares artifacts without sending.
        return_case = tmp_path / "return-case"
        (return_case / "analysis" / "remote_outputs").mkdir(parents=True)
        (return_case / "source").mkdir(parents=True)
        (return_case / "html").mkdir(parents=True)
        (return_case / "case.json").write_text(
            '{"title":"回传自测","source_kind":"manual_text","paths":{"transcript":"source/meeting_transcript.md","analysis":"analysis/meeting_analysis.md","html":"html/report.html"}}\n',
            encoding="utf-8",
        )
        (return_case / "source" / "source_resolution.json").write_text(
            '{"source_kind":"manual_text","transcript_title":"回传自测 transcript"}\n',
            encoding="utf-8",
        )
        (return_case / "source" / "meeting_transcript.md").write_text("Speaker 1 00:00:01 你好", encoding="utf-8")
        (return_case / "analysis" / "meeting_analysis.md").write_text("# 分析\n\n- 结论\n", encoding="utf-8")
        (return_case / "analysis" / "remote_outputs" / "wow.md").write_text("# WOW 分析\n", encoding="utf-8")
        (return_case / "html" / "report.html").write_text("<!doctype html><html><body>ok</body></html>", encoding="utf-8")
        return_args = type(
            "Args",
            (),
            {
                "case_dir": str(return_case),
                "include_source_transcript": False,
                "profile": "",
                "identity": "bot",
                "message_id": "",
                "chat_id": "",
                "doc": "",
                "folder_token": "",
                "wiki_token": "",
                "send": False,
                "dry_run": False,
                "reply_in_thread": False,
            },
        )()
        manifest = rtf.build_return_package(return_args)
        artifacts = {item["path"] for item in manifest.get("artifacts", [])}
        source_paths_text = (return_case / "analysis" / "source_paths_for_feishu.md").read_text(encoding="utf-8")
        check("return_to_feishu writes manifest", (return_case / "analysis" / "feishu_return_manifest.json").exists())
        check("return_to_feishu includes source path attachment", "analysis/source_paths_for_feishu.md" in artifacts, str(artifacts))
        check("source_paths_for_feishu records resolution source_kind", "- source_kind: `manual_text`" in source_paths_text, source_paths_text)
        check("return_to_feishu includes Feishu index entry", "analysis/feishu_index_entry.md" in artifacts, str(artifacts))
        check("return_to_feishu includes meeting analysis", "analysis/meeting_analysis.md" in artifacts, str(artifacts))
        check("return_to_feishu includes remote output", "analysis/remote_outputs/wow.md" in artifacts, str(artifacts))
        check("return_to_feishu includes html", "html/report.html" in artifacts, str(artifacts))
        check(
            "return_to_feishu writes single Feishu document draft",
            manifest.get("single_document", {}).get("path") == "analysis/feishu_meeting_document.md"
            and (return_case / "analysis" / "feishu_meeting_document.md").exists(),
            str(manifest.get("single_document")),
        )

        fake_lark_cli = tmp_path / "fake-lark-cli"
        fake_lark_cli.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_lark_cli.chmod(0o755)
        with mock.patch.dict(rtf.os.environ, {"LARK_CLI": str(fake_lark_cli)}):
            check("resolve_lark_cli honors LARK_CLI env", rtf.resolve_lark_cli() == str(fake_lark_cli))

        targets_config = tmp_path / "meeting_chain_targets.local.json"
        targets_config.write_text(
            json.dumps(
                {
                    "lark_profile": "zhihui-profile",
                    "wiki": {
                        "space_name": "【内部】脑回路实验室",
                        "space_id": "7610000000000000000",
                        "meeting_pipeline": {
                            "title": "01_会议分析流水线",
                            "node_token": "pipeline_token",
                            "children": {
                                "index": {"title": "01_会议成果索引", "node_token": "idx_token"},
                                "internal_analysis": {"title": "02_内部会议分析", "node_token": "internal_token"},
                                "partner_analysis": {"title": "03_合作方会议分析", "node_token": "partner_token"},
                                "customer_analysis": {"title": "04_客户会议分析", "node_token": "customer_token"},
                                "customer_html": {"title": "05_客户展示页", "node_token": "html_token"},
                                "context_materials": {"title": "06_补资料与背景包", "node_token": "context_token"},
                                "run_logs": {"title": "90_运行记录", "node_token": "logs_token"},
                                "attachments": {"title": "99_附件库", "node_token": "attach_token"},
                            }
                        },
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        typed_args = type(
            "Args",
            (),
            {
                "case_dir": str(return_case),
                "include_source_transcript": False,
                "profile": "",
                "targets_config": str(targets_config),
                "allow_profile_override": False,
                "skip_target_validation": False,
                "identity": "bot",
                "message_id": "",
                "chat_id": "",
                "doc": "",
                "folder_token": "",
                "wiki_token": "",
                "send": False,
                "dry_run": False,
                "reply_in_thread": False,
            },
        )()
        typed_manifest = rtf.build_return_package(typed_args)
        target_roles = {item["path"]: item["target_role"] for item in typed_manifest.get("artifact_targets", [])}
        check("return_to_feishu forces configured archive profile", typed_manifest.get("profile") == "zhihui-profile", str(typed_manifest.get("profile")))
        check(
            "return_to_feishu infers internal audience for neutral default output",
            typed_manifest.get("archive_audience", {}).get("audience") == "internal",
            str(typed_manifest.get("archive_audience")),
        )
        check("return_to_feishu routes index entry to index", target_roles.get("analysis/feishu_index_entry.md") == "index", str(target_roles))
        check("return_to_feishu routes internal html to internal_analysis", target_roles.get("html/report.html") == "internal_analysis", str(target_roles))
        check("return_to_feishu routes meeting analysis to internal_analysis", target_roles.get("analysis/meeting_analysis.md") == "internal_analysis", str(target_roles))
        check("return_to_feishu routes provenance to run_logs", target_roles.get("analysis/source_paths_for_feishu.md") == "run_logs", str(target_roles))
        check(
            "return_to_feishu selects pipeline parent for single-document archive",
            typed_manifest.get("single_document", {}).get("parent_role") == "single_document",
            str(typed_manifest.get("single_document")),
        )
        fake_lark_cli.write_text(
            "#!/bin/sh\nprintf '%s\\n' '{\"data\":{\"space_id\":\"7610000000000000000\",\"document\":{\"url\":\"https://example.feishu.cn/docx/single\"}}}'\n",
            encoding="utf-8",
        )
        typed_send_args = type(
            "Args",
            (),
            {
                "case_dir": str(return_case),
                "include_source_transcript": False,
                "profile": "",
                "targets_config": str(targets_config),
                "allow_profile_override": False,
                "allow_multi_artifact_upload": False,
                "skip_target_validation": False,
                "identity": "bot",
                "message_id": "",
                "chat_id": "",
                "doc": "",
                "folder_token": "",
                "wiki_token": "",
                "send": True,
                "dry_run": True,
                "reply_in_thread": False,
            },
        )()
        with mock.patch.dict(rtf.os.environ, {"LARK_CLI": str(fake_lark_cli)}):
            typed_send_manifest = rtf.build_return_package(typed_send_args)
        action_types = [item.get("type") for item in typed_send_manifest.get("actions", []) if isinstance(item, dict)]
        check("return_to_feishu default send creates one Feishu doc", action_types == ["doc_create_single_document"], str(action_types))
        check("return_to_feishu default send skips drive fanout", "drive_upload" not in action_types, str(action_types))
        check("return_to_feishu default send skips artifact file spam", "im_file" not in action_types, str(action_types))

        customer_return_case = tmp_path / "customer-return-case"
        (customer_return_case / "analysis" / "remote_outputs").mkdir(parents=True)
        (customer_return_case / "source").mkdir(parents=True)
        (customer_return_case / "html").mkdir(parents=True)
        (customer_return_case / "case.json").write_text(
            '{"title":"客户拜访 WOW 输出","source_kind":"getbiji","paths":{"transcript":"source/meeting_transcript.md"}}\n',
            encoding="utf-8",
        )
        (customer_return_case / "source" / "source_resolution.json").write_text(
            '{"source_kind":"getbiji","transcript_title":"客户拜访 transcript"}\n',
            encoding="utf-8",
        )
        (customer_return_case / "source" / "meeting_transcript.md").write_text(
            "客户王总讨论需求、预算、报价、采购流程和后续合作。",
            encoding="utf-8",
        )
        (customer_return_case / "analysis" / "remote_outputs" / "wow_customer.md").write_text(
            "# WOW 客户分析\n\n- 客户需求\n- 报价风险\n",
            encoding="utf-8",
        )
        (customer_return_case / "html" / "wow_customer.html").write_text(
            "<!doctype html><html><body>客户分析</body></html>",
            encoding="utf-8",
        )
        customer_args = type(
            "Args",
            (),
            {
                "case_dir": str(customer_return_case),
                "include_source_transcript": False,
                "profile": "",
                "targets_config": str(targets_config),
                "allow_profile_override": False,
                "skip_target_validation": False,
                "identity": "bot",
                "message_id": "",
                "chat_id": "",
                "doc": "",
                "folder_token": "",
                "wiki_token": "",
                "send": False,
                "dry_run": False,
                "reply_in_thread": False,
            },
        )()
        customer_manifest = rtf.build_return_package(customer_args)
        customer_roles = {item["path"]: item["target_role"] for item in customer_manifest.get("artifact_targets", [])}
        check(
            "return_to_feishu infers customer audience for customer default/WOW output",
            customer_manifest.get("archive_audience", {}).get("audience") == "customer",
            str(customer_manifest.get("archive_audience")),
        )
        check(
            "return_to_feishu routes customer WOW markdown to customer_analysis",
            customer_roles.get("analysis/remote_outputs/wow_customer.md") == "customer_analysis",
            str(customer_roles),
        )
        check(
            "return_to_feishu routes customer WOW html to customer_html",
            customer_roles.get("html/wow_customer.html") == "customer_html",
            str(customer_roles),
        )

        partner_return_case = tmp_path / "partner-return-case"
        (partner_return_case / "analysis").mkdir(parents=True)
        (partner_return_case / "source").mkdir(parents=True)
        (partner_return_case / "html").mkdir(parents=True)
        (partner_return_case / "case.json").write_text(
            '{"title":"战略伙伴合作会议","source_kind":"feishu_docx"}\n',
            encoding="utf-8",
        )
        (partner_return_case / "case.yaml").write_text(
            'meeting_type: "partner"\n',
            encoding="utf-8",
        )
        (partner_return_case / "source" / "meeting_transcript.md").write_text(
            "合作方与战略伙伴讨论技术合作、学校合作和联合开发计划。",
            encoding="utf-8",
        )
        (partner_return_case / "analysis" / "meeting_analysis.md").write_text(
            "# 合作方会议分析\n\n- 技术合作\n- 联合开发\n",
            encoding="utf-8",
        )
        (partner_return_case / "customer_material.md").write_text(
            "# 对外可引用材料\n\n- 合作方确认联合开发方向。\n",
            encoding="utf-8",
        )
        (partner_return_case / "html" / "partner_summary.html").write_text(
            "<!doctype html><html><body>合作方会议摘要</body></html>",
            encoding="utf-8",
        )
        partner_args = type(
            "Args",
            (),
            {
                "case_dir": str(partner_return_case),
                "include_source_transcript": False,
                "profile": "",
                "targets_config": str(targets_config),
                "allow_profile_override": False,
                "skip_target_validation": False,
                "identity": "bot",
                "message_id": "",
                "chat_id": "",
                "doc": "",
                "folder_token": "",
                "wiki_token": "",
                "send": False,
                "dry_run": False,
                "reply_in_thread": False,
            },
        )()
        partner_manifest = rtf.build_return_package(partner_args)
        partner_roles = {item["path"]: item["target_role"] for item in partner_manifest.get("artifact_targets", [])}
        check(
            "return_to_feishu maps meeting_type=partner to partner audience",
            partner_manifest.get("archive_audience", {}).get("audience") == "partner",
            str(partner_manifest.get("archive_audience")),
        )
        check(
            "return_to_feishu routes partner analysis to partner_analysis",
            partner_roles.get("analysis/meeting_analysis.md") == "partner_analysis",
            str(partner_roles),
        )
        check(
            "return_to_feishu routes partner customer_material to partner_analysis",
            partner_roles.get("customer_material.md") == "partner_analysis",
            str(partner_roles),
        )
        check(
            "return_to_feishu routes partner html to partner_analysis",
            partner_roles.get("html/partner_summary.html") == "partner_analysis",
            str(partner_roles),
        )

        partner_heuristic_case = tmp_path / "partner-heuristic-case"
        (partner_heuristic_case / "analysis").mkdir(parents=True)
        (partner_heuristic_case / "source").mkdir(parents=True)
        (partner_heuristic_case / "case.json").write_text(
            '{"title":"学校合作市场方向讨论","source_kind":"feishu_docx"}\n',
            encoding="utf-8",
        )
        (partner_heuristic_case / "source" / "meeting_transcript.md").write_text(
            "学校合作、生态合作和战略伙伴共创方向讨论。",
            encoding="utf-8",
        )
        (partner_heuristic_case / "analysis" / "meeting_analysis.md").write_text(
            "# 合作会议\n\n- 学校合作\n- 生态合作\n",
            encoding="utf-8",
        )
        partner_heuristic_args = type(
            "Args",
            (),
            {
                "case_dir": str(partner_heuristic_case),
                "include_source_transcript": False,
                "profile": "",
                "targets_config": str(targets_config),
                "allow_profile_override": False,
                "skip_target_validation": False,
                "identity": "bot",
                "message_id": "",
                "chat_id": "",
                "doc": "",
                "folder_token": "",
                "wiki_token": "",
                "send": False,
                "dry_run": False,
                "reply_in_thread": False,
            },
        )()
        partner_heuristic_manifest = rtf.build_return_package(partner_heuristic_args)
        check(
            "return_to_feishu infers partner audience from cooperation terms",
            partner_heuristic_manifest.get("archive_audience", {}).get("audience") == "partner",
            str(partner_heuristic_manifest.get("archive_audience")),
        )

        mismatch_args = type(
            "Args",
            (),
            {
                "case_dir": str(return_case),
                "include_source_transcript": False,
                "profile": "fm96",
                "targets_config": str(targets_config),
                "allow_profile_override": False,
                "skip_target_validation": False,
                "identity": "bot",
                "message_id": "",
                "chat_id": "",
                "doc": "",
                "folder_token": "",
                "wiki_token": "",
                "send": False,
                "dry_run": False,
                "reply_in_thread": False,
            },
        )()
        rejected_profile = False
        try:
            rtf.build_return_package(mismatch_args)
        except SystemExit:
            rejected_profile = True
        check("return_to_feishu rejects mismatched archive profile", rejected_profile)

        unresolved_paths_case = tmp_path / "unresolved-paths-case"
        (unresolved_paths_case / "analysis").mkdir(parents=True)
        (unresolved_paths_case / "source").mkdir(parents=True)
        (unresolved_paths_case / "case.json").write_text(
            '{"title":"来源路径 UNRESOLVED 自测","paths":{"analysis":"analysis/meeting_analysis.md"}}\n',
            encoding="utf-8",
        )
        unresolved_paths_doc = rtf.build_source_paths_doc(unresolved_paths_case)
        unresolved_paths_text = unresolved_paths_doc.read_text(encoding="utf-8")
        check("source_paths_for_feishu marks missing resolution UNRESOLVED", "UNRESOLVED" in unresolved_paths_text, unresolved_paths_text)

        unresolved_return_case = tmp_path / "unresolved-return-case"
        (unresolved_return_case / "analysis").mkdir(parents=True)
        (unresolved_return_case / "source").mkdir(parents=True)
        (unresolved_return_case / "case.json").write_text(
            '{"title":"无 provenance 回传阻断","source_kind":"manual_text","paths":{"analysis":"analysis/meeting_analysis.md"}}\n',
            encoding="utf-8",
        )
        (unresolved_return_case / "analysis" / "meeting_analysis.md").write_text("# 分析\n", encoding="utf-8")
        blocked_return = subprocess.run(
            [
                PY,
                str(SCRIPT_DIR / "finalize_route.py"),
                "--case-dir", str(unresolved_return_case),
                "--route", "agent_default",
                "--approve",
                "--scan-case",
            ],
            capture_output=True,
            text=True,
        )
        blocked_route_done = unresolved_return_case / "analysis" / "route_done.json"
        blocked_manifest = unresolved_return_case / "analysis" / "feishu_return_manifest.json"
        check("empty source without negative provenance cannot reach return-package", blocked_return.returncode != 0 and not blocked_manifest.exists(), blocked_return.stderr[-500:])
        check("empty source without negative provenance does not mark review_approved", not blocked_route_done.exists() or "review_approved" not in blocked_route_done.read_text(encoding="utf-8"))

        negative_return_case = tmp_path / "negative-return-case"
        (negative_return_case / "analysis").mkdir(parents=True)
        (negative_return_case / "source").mkdir(parents=True)
        (negative_return_case / "case.json").write_text(
            '{"title":"负向 provenance 阻断","source_kind":"feishu_docx","paths":{"analysis":"analysis/meeting_analysis.md"}}\n',
            encoding="utf-8",
        )
        (negative_return_case / "source" / "source_resolution.json").write_text(
            '{"source_kind":"feishu_docx","transcript_available":false,"reason":"fixture permission denied"}\n',
            encoding="utf-8",
        )
        (negative_return_case / "analysis" / "meeting_analysis.md").write_text("# 分析\n", encoding="utf-8")
        negative_block = subprocess.run(
            [
                PY,
                str(SCRIPT_DIR / "finalize_route.py"),
                "--case-dir", str(negative_return_case),
                "--route", "agent_default",
                "--approve",
                "--scan-case",
            ],
            capture_output=True,
            text=True,
        )
        check("negative provenance blocks review-approved return", negative_block.returncode != 0 and "fixture permission denied" in negative_block.stderr, negative_block.stderr[-500:])

        with tempfile.TemporaryDirectory() as resolve_tmp:
            resolve_args = mock.Mock(
                source_ref="https://demo.feishu.cn/docx/NO_TRANSCRIPT_FIXTURE",
                profile=None,
                identity=None,
                config=str(SKILL_DIR / "references" / "lark_profiles.example.json"),
                case_id="resolve-failure-case",
                runtime_dir=resolve_tmp,
                minutes_artifact=None,
            )

            def fake_profile_candidates(_source_ref, _config_path):
                return [("demo-profile", "user")], {"recommended_profile": "demo-profile"}

            def fake_fetch_failure(_source_ref, _profile, _identity):
                raise SystemExit("fixture fetch denied")

            with mock.patch.object(rms, "choose_profile_candidates", side_effect=fake_profile_candidates):
                with mock.patch.object(rms, "fetch_with_readonly_fallback", side_effect=fake_fetch_failure):
                    failed_resolution = rms.resolve_source(resolve_args)
            failed_resolution_path = Path(resolve_tmp) / "source" / "source_resolution.json"
            failed_resolution_payload = json.loads(failed_resolution_path.read_text(encoding="utf-8")) if failed_resolution_path.exists() else {}
            check("resolve failure returns transcript_available false", failed_resolution.get("transcript_available") is False, str(failed_resolution))
            check("resolve failure writes transcript_available false", failed_resolution_payload.get("transcript_available") is False, str(failed_resolution_payload))
            check("resolve failure records attempted profile", failed_resolution_payload.get("attempted_profiles", [{}])[0].get("profile") == "demo-profile", str(failed_resolution_payload.get("attempted_profiles")))

        # 11. Route finalizer adapts CRM agent_output files into canonical case paths.
        finalize_case = tmp_path / "finalize-case"
        (finalize_case / "analysis").mkdir(parents=True)
        (finalize_case / "source").mkdir(parents=True)
        (finalize_case / "source" / "meeting_transcript.md").write_text("Speaker 1 00:00:01 你好", encoding="utf-8")
        (finalize_case / "source" / "source_resolution.json").write_text(
            '{"source_kind":"getbiji_note","transcript_available":true,"transcript_title":"CRM 收尾自测"}\n',
            encoding="utf-8",
        )
        crm_customer = finalize_case / "agent_output" / "测试客户"
        crm_archive = finalize_case / "agent_output" / "客户档案"
        crm_customer.mkdir(parents=True)
        crm_archive.mkdir(parents=True)
        (crm_customer / "纪要_2026-06-14.html").write_text("<!doctype html><html><body>纪要</body></html>", encoding="utf-8")
        (crm_customer / "成果_2026-06-14.html").write_text("<!doctype html><html><body>成果</body></html>", encoding="utf-8")
        (crm_archive / "测试客户.md").write_text("# 测试客户\n", encoding="utf-8")
        (finalize_case / "case.json").write_text(
            '{"title":"CRM 收尾自测","source_kind":"getbiji_note","paths":{"transcript":"source/meeting_transcript.md"}}\n',
            encoding="utf-8",
        )
        (finalize_case / "case.yaml").write_text(
            "\n".join(
                [
                    'case_id: "finalize-case"',
                    'output_paths:',
                    '  - "agent_output/测试客户/纪要_2026-06-14.html"',
                    '  - "agent_output/客户档案/测试客户.md"',
                    '  - "agent_output/测试客户/成果_2026-06-14.html"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        r7 = subprocess.run(
            [
                PY,
                str(SCRIPT_DIR / "finalize_route.py"),
                "--case-dir", str(finalize_case),
                "--route", "crm_skill",
                "--needs-review",
            ],
            capture_output=True,
            text=True,
        )
        route_done = finalize_case / "analysis" / "route_done.json"
        route_done_text = route_done.read_text(encoding="utf-8") if route_done.exists() else ""
        check("finalize_route.py pauses CRM for review", r7.returncode == 0 and "ready_for_review" in route_done_text, r7.stderr[-300:])
        check("finalize_route.py copies CRM html into html/", (finalize_case / "html" / "crm_纪要_2026-06-14.html").exists())
        check("finalize_route.py copies CRM markdown into analysis/crm/", (finalize_case / "analysis" / "crm" / "测试客户.md").exists())

        r8 = subprocess.run(
            [
                PY,
                str(SCRIPT_DIR / "finalize_route.py"),
                "--case-dir", str(finalize_case),
                "--route", "crm_skill",
                "--approve",
            ],
            capture_output=True,
            text=True,
        )
        finalize_manifest_path = finalize_case / "analysis" / "feishu_return_manifest.json"
        finalize_manifest = json.loads(finalize_manifest_path.read_text(encoding="utf-8")) if finalize_manifest_path.exists() else {}
        finalize_artifacts = {item["path"] for item in finalize_manifest.get("artifacts", [])}
        check("finalize_route.py approved run builds return package", r8.returncode == 0 and finalize_manifest_path.exists(), r8.stderr[-300:])
        check("finalize_route return includes index entry", "analysis/feishu_index_entry.md" in finalize_artifacts, str(finalize_artifacts))
        check("finalize_route return includes crm html", "html/crm_成果_2026-06-14.html" in finalize_artifacts, str(finalize_artifacts))
        check("finalize_route return includes crm markdown", "analysis/crm/测试客户.md" in finalize_artifacts, str(finalize_artifacts))

    failures = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        suffix = f"  -- {detail}" if (not ok and detail) else ""
        print(f"[{'PASS' if ok else 'FAIL'}] {name}{suffix}")
    print(f"\n{len(RESULTS) - len(failures)}/{len(RESULTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
