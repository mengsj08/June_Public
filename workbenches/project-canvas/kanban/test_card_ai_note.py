#!/usr/bin/env python3
"""卡级「给 AI 的常驻说明」：执行时把备注提到 prompt 最前 + 落盘段的增删改。"""

import importlib.util
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('scan_docs', _HERE / 'scan-docs.py')
scan_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_mod)


CARD_WITH_NOTE = (
    "---\n"
    "title: t\n"
    "status: todo\n"
    "---\n\n"
    "## 给 AI 的常驻说明\n"
    "本次只改 foo.py，不要动 bar。\n\n"
    "## 要做什么\n"
    "修复登录 bug。\n"
)


def test_extract_card_note():
    assert scan_mod._extract_card_note(CARD_WITH_NOTE) == "本次只改 foo.py，不要动 bar。"
    assert scan_mod._extract_card_note("---\ntitle: t\n---\n\n## 要做什么\nabc\n") == ""


def test_apply_note_prepends_and_strips():
    out = scan_mod._apply_card_ai_note_to_prompt(CARD_WITH_NOTE)
    assert out.startswith("<执行备注>")
    assert "本次只改 foo.py" in out
    # 备注只出现一次（已从尾部正文剥离，不重复喂给 CLI）
    assert out.count("本次只改 foo.py") == 1
    body_part = out.split("---\n\n", 1)[1]
    assert "## 给 AI 的常驻说明" not in body_part
    assert "## 要做什么" in body_part  # 其余正文保留


def test_apply_note_passthrough_when_absent():
    raw = "---\ntitle: x\n---\n\n## 要做什么\nabc\n"
    assert scan_mod._apply_card_ai_note_to_prompt(raw) == raw


def test_unknown_skill_command_falls_back_to_plain_note():
    # 段内以 /xxx 开头但不是真 skill → 回落为普通备注包裹，不报错
    raw = CARD_WITH_NOTE.replace("本次只改 foo.py，不要动 bar。", "/__definitely_not_a_skill__ do it")
    out = scan_mod._apply_card_ai_note_to_prompt(raw)
    assert out.startswith("<执行备注>")
    assert "/__definitely_not_a_skill__" in out


def test_update_card_note_section_upsert_and_clear(tmp_path):
    rel = "project/个人调度/__test_ai_note__.md"
    fpath = tmp_path / rel
    fpath.parent.mkdir(parents=True)
    fpath.write_text("---\ntitle: 临时\nstatus: todo\n---\n\n## 要做什么\nabc\n", encoding="utf-8")
    try:
        with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
            # 新增
            res, code = scan_mod.update_card_note_section(rel, "只读模式")
        assert code == 200 and res["ok"] and res["ai_note"] == "只读模式"
        txt = fpath.read_text(encoding="utf-8")
        assert "## 给 AI 的常驻说明" in txt and "只读模式" in txt
        assert "## 要做什么" in txt  # 原正文不丢

        # 更新
        with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
            scan_mod.update_card_note_section(rel, "改成可写")
        txt = fpath.read_text(encoding="utf-8")
        assert "改成可写" in txt and "只读模式" not in txt
        assert txt.count("## 给 AI 的常驻说明") == 1  # 不重复成段

        # 清空 → 删除整段
        with patch.object(scan_mod, 'REPO_ROOT', tmp_path):
            res, code = scan_mod.update_card_note_section(rel, "")
        assert code == 200 and res["ai_note"] == ""
        txt = fpath.read_text(encoding="utf-8")
        assert "## 给 AI 的常驻说明" not in txt
        assert "## 要做什么" in txt
    finally:
        if fpath.exists():
            fpath.unlink()
