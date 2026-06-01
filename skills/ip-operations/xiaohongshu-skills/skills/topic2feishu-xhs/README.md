# topic2feishu-xhs

小红书关键词采集、文案分析改写并写入飞书 Base 的复合工作流。

## When To Use

- 按关键词采集小红书笔记。
- 获取笔记详情后做文案结构分析。
- 生成标题重写和内容改写。
- 把原始笔记数据与分析结果写入飞书多维表格。

## Quick Start For AI

示例提示词：

```text
使用 topic2feishu-xhs，搜索关键词“AI for science”，采集 5 条笔记，先输出 JSON，不写飞书。
```

```text
使用 topic2feishu-xhs，把采集结果和分析改写写入这个飞书 Base：base_token=...，table_id=...，lark_profile=...
```

## Inputs

- `keyword`：搜索关键词，必填。
- `number`：处理数量，默认 10。
- `base_token`：飞书 Base token，写入时必需。
- `table_id`：飞书 table id 或表名，写入时必需。
- `lark_profile`：本机官方 `lark-cli` profile。
- `lark_as`：`user` 或 `bot`。
- 可选筛选：排序、笔记类型、发布时间、搜索范围、地点。

## Workflow

先采集，不写飞书：

```bash
python scripts/cli.py topic2feishu \
  --keyword "关键词" \
  --number 10 \
  --output-json /abs/path/topic2feishu-collected.json
```

再由 AI 读取 JSON，生成 `analysis-json`，最后写入飞书：

```bash
python scripts/cli.py topic2feishu \
  --input-json /abs/path/topic2feishu-collected.json \
  --analysis-json @/abs/path/topic2feishu-analysis.json \
  --write-feishu \
  --base-token "<base-token>" \
  --table-id "<table-id>" \
  --lark-profile "<profile-name>" \
  --lark-as user
```

## Feishu Check

写入前先验证字段权限：

```bash
lark-cli --profile "<profile-name>" base +field-list \
  --base-token "<base-token>" \
  --table-id "<table-id>" \
  --as user
```

## Safety

- 小红书侧只通过 `python scripts/cli.py topic2feishu`。
- 飞书侧只通过官方 `lark-cli base` 命令。
- 不迁移 `.lark-cli`、Chrome profile、cookies、token 或 app secret。
- 批量详情读取控制频率，默认每 3 篇后等待。
