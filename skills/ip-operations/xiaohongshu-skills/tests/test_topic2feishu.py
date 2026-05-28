import json
import subprocess

import xhs.topic2feishu as topic2feishu
from xhs.topic2feishu import (
    FIELD_ORDER,
    build_lark_batch_payload,
    build_records,
    collect_notes,
    load_analysis_json,
    normalize_note,
    write_feishu_records,
)


def test_normalize_note_uses_detail_and_feed_fallbacks():
    detail = {
        "note": {
            "noteId": "note_1",
            "title": "原始标题",
            "body": "正文",
            "tags": ["#AI", "#工具"],
            "time": 1773030490000,
            "user": {"userId": "user_1", "nickname": "作者"},
            "interactInfo": {
                "likedCount": "1.2万",
                "collectedCount": "345",
                "commentCount": "6",
                "sharedCount": "",
            },
        }
    }
    feed = {
        "id": "note_1",
        "xsecToken": "token_1",
        "displayTitle": "搜索标题",
        "interactInfo": {"sharedCount": "7"},
    }

    note = normalize_note(detail, feed, "AI工具")

    assert note["note_id"] == "note_1"
    assert note["title"] == "原始标题"
    assert note["content"] == "正文"
    assert note["tags"] == ["#AI", "#工具"]
    assert note["like_count"] == 12000
    assert note["share_count"] == 7
    assert note["source_keyword"] == "AI工具"
    assert note["note_url"].startswith("https://www.xiaohongshu.com/explore/note_1")


def test_build_records_requires_analysis_when_requested():
    notes = [{
        "note_id": "note_1",
        "note_url": "https://example.test/note_1",
        "create_time": "2026-03-07 10:00:00",
        "author_nickname": "作者",
        "collect_count": 1,
        "title": "标题",
        "like_count": 2,
        "comment_count": 3,
        "share_count": 4,
        "author_homepage_url": "https://example.test/user",
        "tags": None,
        "content": "正文",
    }]

    records, failures = build_records(notes, require_analysis=True)

    assert records == []
    assert len(failures) == 1
    assert "missing analysis fields" in failures[0]["reason"]


def test_build_lark_payload_preserves_field_order_and_empty_tags():
    notes = [{
        "note_id": "note_1",
        "note_url": "https://example.test/note_1",
        "create_time": "2026-03-07 10:00:00",
        "author_nickname": "作者",
        "collect_count": 1,
        "title": "标题",
        "like_count": 2,
        "comment_count": 3,
        "share_count": 4,
        "author_homepage_url": "https://example.test/user",
        "tags": None,
        "content": "正文",
    }]
    analysis = [{
        "note_id": "note_1",
        "deep_analysis": "分析",
        "title_re": ["标题 A", "标题 B", "标题 C"],
        "rewrite": "改写",
    }]

    records, failures = build_records(notes, analysis, require_analysis=True)
    payload = build_lark_batch_payload(records)

    assert failures == []
    assert payload["fields"] == FIELD_ORDER
    assert payload["rows"][0][FIELD_ORDER.index("笔记标签")] == ""
    assert payload["rows"][0][FIELD_ORDER.index("标题重写")] == "标题 A\n标题 B\n标题 C"


def test_build_records_matches_analysis_by_note_url():
    note_url = "https://example.test/note_1"
    notes = [{
        "note_id": "note_1",
        "note_url": note_url,
        "title": "标题",
        "tags": ["#标签"],
    }]
    analysis = {
        note_url: {
            "deep_analysis": "按 URL 匹配的分析",
            "title_re": "标题1\n标题2\n标题3",
            "rewrite": "改写正文",
        }
    }

    records, failures = build_records(notes, analysis, require_analysis=True)

    assert failures == []
    assert records[0]["深度分析"] == "按 URL 匹配的分析"
    assert records[0]["笔记标签"] == "#标签"


def test_load_analysis_json_supports_at_file(tmp_path):
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps([{"note_id": "note_1", "deep_analysis": "分析"}]), encoding="utf-8")

    assert load_analysis_json(f"@{path}") == [{"note_id": "note_1", "deep_analysis": "分析"}]


def test_collect_notes_filters_duplicates_and_isolates_detail_failures(monkeypatch):
    class FakeFeed:
        def __init__(self, data):
            self.data = data

        def to_dict(self):
            return self.data

    class FakeDetail:
        def __init__(self, feed_id):
            self.feed_id = feed_id

        def to_dict(self):
            return {
                "note": {
                    "noteId": self.feed_id,
                    "title": f"标题 {self.feed_id}",
                    "body": "正文",
                    "tags": [],
                    "user": {"userId": "user_1", "nickname": "作者"},
                }
            }

    def fake_search_feeds(page, keyword, filter_opt):
        assert page == "page"
        assert keyword == "AI工具"
        assert filter_opt.sort_by == "最多点赞"
        return [
            FakeFeed({"id": "hot", "xsecToken": "hot_token", "modelType": "hot_query"}),
            FakeFeed({"id": "note_1", "xsecToken": "token_1", "modelType": "note"}),
            FakeFeed({"id": "note_1", "xsecToken": "token_1_dup", "modelType": "note"}),
            FakeFeed({"id": "note_2", "xsecToken": "token_2", "modelType": "note"}),
        ]

    def fake_get_feed_detail(page, feed_id, xsec_token, **kwargs):
        assert page == "page"
        if feed_id == "note_2":
            raise RuntimeError("detail failed")
        return FakeDetail(feed_id)

    monkeypatch.setattr(topic2feishu, "search_feeds", fake_search_feeds)
    monkeypatch.setattr(topic2feishu, "get_feed_detail", fake_get_feed_detail)

    notes, failures = collect_notes(
        "page",
        keyword="AI工具",
        number=2,
        sort_by="最多点赞",
        detail_wait_min=0,
        detail_wait_max=0,
    )

    assert [note["note_id"] for note in notes] == ["note_1"]
    assert failures == [{"feed_id": "note_2", "title": "", "reason": "detail failed"}]


def test_write_feishu_records_dry_run_uses_relative_payload_and_schema_filter(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_run(cmd, text, capture_output, check):
        calls.append(cmd)
        assert text is True
        assert capture_output is True
        assert check is False
        if "+field-list" in cmd:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps({
                "items": [
                    {"field_name": "标题", "type": "text"},
                    {"field_name": "深度分析", "type": "text"},
                    {"field_name": "只读字段", "type": "formula"},
                    ]
                }),
                stderr="",
            )

        json_arg = cmd[cmd.index("--json") + 1]
        assert json_arg.startswith("@.topic2feishu-runtime/payload-")
        assert not json_arg.startswith("@/")
        payload = json.loads((tmp_path / json_arg[1:]).read_text(encoding="utf-8"))
        assert payload == {
            "fields": ["标题", "深度分析"],
            "rows": [["标题", "分析"]],
        }
        assert "--dry-run" in cmd
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(topic2feishu.subprocess, "run", fake_run)

    result = write_feishu_records(
        records=[{"标题": "标题", "深度分析": "分析", "点赞数": 10}],
        base_token="base_token",
        table_id="tbl_xxx",
        lark_profile="example-profile",
        dry_run=True,
    )

    assert len(calls) == 2
    assert calls[0][:3] == ["lark-cli", "--profile", "example-profile"]
    assert calls[1][:3] == ["lark-cli", "--profile", "example-profile"]
    assert result["dry_run"] is True
    assert result["written"] == 0
    assert "点赞数" in result["ignored_fields"]
    assert result["response"] == {"ok": True}


def test_write_feishu_records_maps_known_field_aliases(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_run(cmd, text, capture_output, check):
        if "+field-list" in cmd:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps({
                    "items": [
                        {"field_name": "笔记标题", "type": "text"},
                        {"field_name": "账号名称", "type": "text"},
                        {"field_name": "发布时间", "type": "datetime"},
                        {"field_name": "分享数", "type": "text"},
                    ]
                }),
                stderr="",
            )

        json_arg = cmd[cmd.index("--json") + 1]
        payload = json.loads((tmp_path / json_arg[1:]).read_text(encoding="utf-8"))
        assert payload == {
            "fields": ["发布时间", "账号名称", "笔记标题", "分享数"],
            "rows": [["2026-01-01 10:00:00", "作者", "标题", "8"]],
        }
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(topic2feishu.subprocess, "run", fake_run)

    result = write_feishu_records(
        records=[{
            "创建时间": "2026-01-01 10:00:00",
            "博主": "作者",
            "标题": "标题",
            "转发数": 8,
        }],
        base_token="base_token",
        table_id="tbl_xxx",
    )

    assert result["written"] == 1
    assert result["ignored_fields"]
