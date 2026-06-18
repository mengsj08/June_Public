# feishu-meeting-workflow

把飞书/Lark 会议材料、Get笔记/第三方笔记或本地转录整理成可复用的本地会议 case，并按路线生成内部分析、客户安全材料、HTML、WOW/CRM 交接与统一 Feishu 回传包。

## When To Use

- 用户给出飞书 AI notes docx、Meeting transcript docx、minutes 链接、Get笔记/第三方笔记或本地会议转录。
- 需要把会议材料落到本地 runtime/case 结构中。
- 需要让 AI 基于原始转录写会议总结、行动项、风险、客户可见页面。
- 需要选路、收口、生成 Feishu 单文档回传包，或交给外部 `crm` / `skill_pre-consult`。

## Quick Start For AI

先读取 `SKILL.md`。涉及路线/回传时读取 `references/output_contract.md`；需要配置 Lark CLI 或 pre-consult 依赖时，再读取 `references/guided_setup.md`。

示例提示词：

```text
使用 feishu-meeting-workflow，解析这个飞书 AI notes 链接，创建 case，走默认分析并生成 Feishu 回传包。
```

```text
使用 feishu-meeting-workflow，这是一场售前面访。请选择客户洽谈路线，产物先 review，不要把客户产物写入外部 skill 源码目录。
```

## Inputs

- 飞书 AI notes docx URL。
- 飞书 Meeting transcript docx URL。
- 飞书 minutes URL 或 token。
- 本地 Markdown/text/docx 转录文件。
- 输出工作目录。
- 可选：客户简称、会议日期、会议类型。
- 可选：路线、客户简称、会议日期、`skill_pre-consult` 本地路径或 GitHub URL。

## Workflow

1. 确认输出目录、输入来源和路线。
2. 使用官方 `lark-cli` 检查 Feishu/Lark profile 和授权。
3. 创建会议 case；`meeting_case.py` 会在写完 `case.yaml` 后自动解析支持的主来源。
4. 强制 provenance 门要求 `source/meeting_transcript.md` 非空；resolver 失败时也必须写 `source_resolution.json` 的负向记录。
5. AI 读取转录并手写分析材料。
6. `finalize_route.py` 归一化产物；review 通过后才创建 Feishu return package。

## Core Commands

```bash
python3 "$SKILL_DIR/scripts/meeting_case.py" \
  --case-id "<case-id>" \
  --title "<meeting-title>" \
  --source-kind "<feishu_docx|feishu_minutes|getbiji_note|manual_text>" \
  --source-ref "<feishu-url-or-minutes-token>" \
  --meeting-type auto \
  --customer-short-name "<short-name>" \
  --case-root "$WORK_DIR/meeting-cases" \
  --runtime-root "$WORK_DIR/meeting-runtime"
```

```bash
python3 "$SKILL_DIR/scripts/finalize_route.py" \
  --case-dir "<case-dir>" \
  --route "<agent_default|crm_skill|customer_html_prompt|wow_codex|wow_claude>" \
  --scan-case
```

## Outputs

- `source/meeting_transcript.md`
- `source/ai_notes.md` when available
- `source/source_resolution.json`
- `case.yaml`
- `analysis/route_decision.json`
- `analysis/meeting_analysis.md`
- `analysis/route_done.json`
- `analysis/feishu_meeting_document.md`
- `analysis/source_paths_for_feishu.md`
- `analysis/feishu_return_manifest.json`
- HTML or CRM/WOW outputs under `html/`, `analysis/crm/`, or `analysis/remote_outputs/`

## Safety

- 原始 Meeting transcript 是主来源，AI notes 只作为入口。
- 来源解析是强制门：没有非空 `source/meeting_transcript.md` 时，不得分析、不得标 `review_approved`、不得产 return 包。
- resolver 失败必须写 `source_resolution.json`，包含 `transcript_available:false` 和 `reason`，用于可追溯地停止。
- AI 必须自己读转录并写分析，脚本不生成结论。
- 客户可见材料不得包含飞书 token、签名媒体 URL、原始私密摘录或内部销售判断。
- 不硬编码作者机器路径。
- pre-consult 产物写入当前 case runtime 下的 workspace，不写入外部 skill 源码目录。
