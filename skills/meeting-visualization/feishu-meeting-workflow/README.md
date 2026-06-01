# feishu-meeting-workflow

把飞书/Lark 会议材料或本地转录整理成可复用的本地会议 case，并按需要生成内部分析、客户安全材料、HTML 报告或 pre-consult 交接文件。

## When To Use

- 用户给出飞书 AI notes docx、Meeting transcript docx、minutes 链接或本地会议转录。
- 需要把会议材料落到本地 runtime/case 结构中。
- 需要让 AI 基于原始转录写会议总结、行动项、风险、客户可见页面。
- 售前面访需要交给外部 `skill_pre-consult` 做完整五阶段客户洽谈产出。

## Quick Start For AI

先读取 `SKILL.md`。需要配置 Lark CLI 或 pre-consult 依赖时，再读取 `references/guided_setup.md`。

示例提示词：

```text
使用 feishu-meeting-workflow，解析这个飞书 AI notes 链接，创建 case，输出客户安全的会议总结 HTML。
```

```text
使用 feishu-meeting-workflow，这是一场售前面访。请用默认 skill_pre-consult GitHub 源创建 pre_consult_handoff.md，不要把客户产物写入外部 skill 源码目录。
```

## Inputs

- 飞书 AI notes docx URL。
- 飞书 Meeting transcript docx URL。
- 飞书 minutes URL 或 token。
- 本地 Markdown/text/docx 转录文件。
- 输出工作目录。
- 可选：客户简称、会议日期、会议类型。
- 可选：`skill_pre-consult` 本地路径或 GitHub URL。

## Workflow

1. 确认输出目录和输入来源。
2. 使用官方 `lark-cli` 检查 Feishu/Lark profile 和授权。
3. 解析来源到 `source/meeting_transcript.md`。
4. 创建会议 case。
5. AI 读取转录并手写分析材料。
6. 普通会议可渲染 HTML；售前会议优先生成 `pre_consult_handoff.md`，交给外部 pre-consult skill 执行。

## Core Commands

```bash
python3 "$SKILL_DIR/scripts/resolve_meeting_source.py" \
  --source-ref "<feishu-url-or-minutes-token>" \
  --case-id "<case-id>" \
  --runtime-dir "$WORK_DIR/meeting-runtime/<case-id>"
```

```bash
python3 "$SKILL_DIR/scripts/meeting_case.py" \
  --case-id "<case-id>" \
  --title "<meeting-title>" \
  --source-kind "<feishu_docx|feishu_minutes|local_file>" \
  --source-ref "primary_transcript: <path-or-url>" \
  --input-file "<runtime-dir>/source/meeting_transcript.md" \
  --meeting-type presales \
  --customer-short-name "<short-name>" \
  --pre-consult-git-url "https://github.com/jeffzh0802/skill_pre-consult.git" \
  --case-root "$WORK_DIR/meeting-cases" \
  --runtime-root "$WORK_DIR/meeting-runtime"
```

```bash
python3 "$SKILL_DIR/scripts/render_meeting_html.py" \
  --input "<case-dir>/collaboration_analysis.md" \
  --case "<case-dir>/case.yaml" \
  --output "<runtime-dir>/html/report.html"
```

## Outputs

- `source/meeting_transcript.md`
- `source/ai_notes.md` when available
- `source/source_resolution.json`
- `case.yaml`
- `internal_brief.md`
- `customer_material.md`
- `collaboration_analysis.md`
- `pre_consult_handoff.md` for presales pre-consult route
- HTML report under runtime when requested

## Safety

- 原始 Meeting transcript 是主来源，AI notes 只作为入口。
- AI 必须自己读转录并写分析，脚本不生成结论。
- 客户可见材料不得包含飞书 token、签名媒体 URL、原始私密摘录或内部销售判断。
- 不硬编码作者机器路径。
- pre-consult 产物写入当前 case runtime 下的 workspace，不写入外部 skill 源码目录。
