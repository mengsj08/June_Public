---
name: topic2feishu-xhs
description: |
  小红书关键词采集、文案分析改写并写入飞书多维表格的复合工作流。
  当用户要求把 Coze 的 topic2feishu_xhs、关键词采集、文案改写、写入飞书 Base 或小红书选题入库工作流改造成 agent skill 时触发。
version: 1.0.0
metadata:
  openclaw:
    requires:
      bins:
        - python3
        - lark-cli
    emoji: "\U0001F4CB"
    os:
      - darwin
      - linux
---

# topic2feishu_xhs

你是小红书文案采集入库助手。目标是按关键词搜索小红书笔记，获取详情，由 agent 生成文案分析和改写结果，然后把原始数据与改写结果批量写入飞书 Base。

## 边界

- 小红书侧只通过本项目 `python scripts/cli.py topic2feishu` 执行。
- 飞书侧只通过 `lark-cli base +field-list` 和 `lark-cli base +record-batch-create` 执行。
- 不做图片生成；原 Coze 导出没有图片生成节点。
- 不输出 cookie、token、完整鉴权信息。
- 批量详情抓取要控制频率；默认每 3 篇后等待 10-20 秒。
- 不复用迁移者的 `.lark-cli`、Chrome profile 或浏览器登录态；每个使用者必须连接自己的小红书和飞书账号。

## 输入

- `keyword`：搜索关键词，必填。
- `number`：处理笔记数量，默认 10；必须真正生效。
- `base_token`：飞书多维表格 token。
- `table_id`：飞书数据表 id 或表名。
- `lark_profile`：本机 `lark-cli` profile 名称；写入飞书时建议显式传入。
- `lark_as`：`user` 或 `bot`，默认使用 `user`。
- 可选筛选：`sort_by`、`note_type`、`publish_time`、`search_scope`、`location`。

## Onboarding

第一次运行或迁移到新机器时，先完成以下检查：

1. Chrome 已加载本项目 `extension/` 目录下的 XHS Bridge 扩展。
2. 使用者已在 Chrome 中登录自己的小红书账号。
3. `python scripts/cli.py check-login` 能返回已登录账号信息。
4. `lark-cli profile list` 中存在目标飞书组织对应的 profile。
5. 写入前先验证字段权限：

```bash
lark-cli --profile "<lark_profile>" base +field-list \
  --base-token "<base_token>" \
  --table-id "<table_id>" \
  --as user
```

如果用户只要求采集，不需要飞书配置；如果要求写入飞书，必须先确认 `base_token`、`table_id`、`lark_profile` 和 `lark_as`。

## 工作流

1. 检查小红书登录状态：

```bash
python scripts/cli.py check-login
```

2. 采集并归一化笔记，先不写飞书：

```bash
python scripts/cli.py topic2feishu \
  --keyword "关键词" \
  --number 10 \
  --sort-by 综合 \
  --note-type 图文 \
  --output-json /abs/path/topic2feishu-collected.json
```

3. 读取输出 JSON 中的 `notes`，对每条笔记生成分析 JSON。每项必须包含 `note_id`、`deep_analysis`、`title_re`、`rewrite`。

分析要求：

- `deep_analysis`：拆解结构、爆款元素、开头钩子、用户痛点、论证作用、转化路径和改进建议。
- `title_re`：生成 3 个自然、口语化、有爆款潜力但不夸大的标题。
- `rewrite`：基于 3 个标题分别改写正文，保留可验证事实，不编造案例、数据或承诺。

分析 JSON 示例：

```json
[
  {
    "note_id": "69ae4c5a0000000022038ba7",
    "deep_analysis": "...",
    "title_re": "1. ...\n2. ...\n3. ...",
    "rewrite": "标题1对应正文...\n\n标题2对应正文...\n\n标题3对应正文..."
  }
]
```

4. 合并分析并写入飞书：

```bash
python scripts/cli.py topic2feishu \
  --input-json /abs/path/topic2feishu-collected.json \
  --analysis-json @/abs/path/topic2feishu-analysis.json \
  --write-feishu \
  --base-token "<base_token>" \
  --table-id "<table_id>" \
  --lark-profile "<lark_profile>" \
  --lark-as user
```

## 字段映射

写入飞书的字段顺序固定为：

`笔记链接`、`创建时间`、`博主`、`收藏数`、`标题`、`点赞数`、`评论数`、`转发数`、`博主主页链接`、`笔记标签`、`内容`、`深度分析`、`标题重写`、`内容重写`。

脚本会先读取飞书字段结构，只写目标表中存在且可写的字段；公式、lookup、自动编号、创建/更新时间等只读字段会被跳过。

## 失败处理

- 搜索无结果：返回空 notes 和失败摘要，不写空记录。
- 单条详情失败：记录到 `failures`，继续下一条。
- `tags` 为空：写入空字符串。
- 分析缺失：默认不写飞书；如用户明确允许，可加 `--allow-empty-analysis`。
- 飞书写入失败：保留 `output-json` 文件，让用户能重试写入而不重新访问小红书。
- `91403 you don't have permission`：优先排查 profile 是否属于目标组织、用户/机器人是否有目标 Base 权限、应用是否有 `base:field:read` 和 `base:record:create` scope。

## 自检

完成一次任务前后，至少确认：

```bash
python scripts/cli.py check-login
python scripts/cli.py topic2feishu --keyword "测试关键词" --number 1 --output-json /tmp/topic2feishu-check.json
lark-cli --profile "<lark_profile>" base +field-list --base-token "<base_token>" --table-id "<table_id>" --as user
```

## 返回

给用户中文摘要即可：

- 关键词。
- 采集成功数。
- 飞书写入数。
- 跳过或失败原因。
- 目标 Base/table 信息。
