from ai_run_guard import format_canvas_prompt, nonzero_exit_error, sanitized_cli_env


def test_unresolved_canvas_ref_is_explicit_and_stub_content_is_not_used():
    prompt, count = format_canvas_prompt("读一下这个方案", [{
        "kind": "file",
        "title": "方案.md",
        "status": "missing",
        "path": "方案.md",
        "summary": "浏览器只暴露文件名；保存后再解析",
    }])
    assert count == 1
    assert "未解析，内容不可用" in prompt
    assert "不得据此声称已读取原文件" in prompt
    assert "请先直接读取该路径的文件全文" in prompt
    assert "浏览器只暴露文件名" not in prompt


def test_resolved_canvas_ref_keeps_material_summary():
    prompt, count = format_canvas_prompt("分析", [{
        "kind": "file", "title": "方案.md", "status": "resolved",
        "resolved_path": "/allowed/方案.md", "summary": "真实摘要",
    }])
    assert count == 0
    assert "真实摘要" in prompt
    assert "/allowed/方案.md" in prompt


def test_nonzero_error_prefers_stderr_then_parsed_stdout_then_exit_code():
    assert nonzero_exit_error("stderr truth", "parsed truth", "stdout", 1) == "stderr truth"
    assert nonzero_exit_error("", "Failed to authenticate. API Error: 401 Invalid authentication credentials", "raw", 1).startswith("Failed to authenticate")
    assert nonzero_exit_error("", "", "", 7) == "Exit code 7"


def test_nonzero_error_keeps_tail_with_reason():
    message = "prefix" * 500 + " REAL ROOT CAUSE"
    surfaced = nonzero_exit_error("", message, "", 1, limit=80)
    assert len(surfaced) == 80
    assert surfaced.endswith("REAL ROOT CAUSE")


def test_sanitized_cli_env_strips_host_session_vars_keeps_rest():
    env = {
        "PATH": "/usr/bin",
        "HOME": "/Users/x",
        "ANTHROPIC_BASE_URL": "http://sandbox-gw",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_SESSION_ID": "abc",
        "CLAUDE_EFFORT": "high",
        "DEEPSEEK_API_KEY": "keep-me",
    }
    out = sanitized_cli_env(env)
    assert out["PATH"] == "/usr/bin"
    assert out["HOME"] == "/Users/x"
    assert out["DEEPSEEK_API_KEY"] == "keep-me"
    assert not [k for k in out if k.startswith(("CLAUDE", "ANTHROPIC"))]


def test_sanitized_cli_env_defaults_to_os_environ():
    out = sanitized_cli_env()
    assert not [k for k in out if k.startswith(("CLAUDE", "ANTHROPIC"))]
