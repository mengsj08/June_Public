# topic2feishu-xhs

> 从小红书关键词采集，到 AI 内容分析，再到飞书 Base 入库的一条可审计流水线。

这个子 Skill 适合把零散的内容观察变成结构化研究材料。它把流程拆成“采集”和“写入”两个阶段：先将原始结果保存为 JSON，允许 Agent 或人工检查、分析和改写；确认后再写入指定的飞书多维表格。

## 适用场景

- 按关键词采集一组小红书笔记；
- 比较标题、正文结构、互动数据与内容策略；
- 让 Agent 生成标题重写、内容改写或洞察字段；
- 将原始证据和 AI 分析一并写入飞书 Base；
- 先做只读采集，暂不连接飞书。

## 工作流

```text
关键词与筛选条件
        ↓
采集笔记与详情 → topic2feishu-collected.json
        ↓
Agent / 人工分析 → topic2feishu-analysis.json
        ↓
检查 Base 字段与权限
        ↓
明确确认后写入飞书
```

采集阶段和写入阶段解耦，因此网络失败、字段映射错误或分析结果需要返工时，不必重新访问小红书。

## 快速开始

### 1. 只采集，不写飞书

```bash
python scripts/cli.py topic2feishu \
  --keyword "AI for science" \
  --number 10 \
  --output-json /abs/path/topic2feishu-collected.json
```

### 2. 让 Agent 生成分析 JSON

建议把任务描述得足够具体：

```text
读取 topic2feishu-collected.json。逐条保留原始笔记标识和来源，分析标题钩子、正文结构、目标人群与互动特征，并生成可被 topic2feishu-xhs 消费的 analysis-json。不要编造原文中没有的数据。
```

### 3. 检查飞书字段权限

```bash
lark-cli --profile "<profile-name>" base +field-list \
  --base-token "<base-token>" \
  --table-id "<table-id>" \
  --as user
```

### 4. 确认后写入

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

## 输入参数

| 参数 | 是否必需 | 说明 |
| --- | --- | --- |
| `keyword` | 采集时必需 | 搜索关键词 |
| `number` | 否 | 处理数量，默认 10 |
| `output-json` | 建议 | 保存原始采集结果 |
| `input-json` | 二阶段必需 | 已保存的采集结果 |
| `analysis-json` | 写入分析时必需 | Agent 或人工生成的分析结果 |
| `base-token` | 写飞书时必需 | 飞书 Base 标识；不要提交到 Git |
| `table-id` | 写飞书时必需 | 数据表 ID 或表名 |
| `lark-profile` | 写飞书时必需 | 本机官方 `lark-cli` profile |
| `lark-as` | 否 | `user` 或 `bot` |

搜索阶段还可指定排序、笔记类型、发布时间、搜索范围和地点等筛选条件。

## 交给 Agent 使用

```text
使用 topic2feishu-xhs 搜索关键词“AI for science”，采集 5 条笔记。第一阶段只输出 JSON，不写飞书；列出成功数、失败数和缺失字段，等我确认后再做分析与入库。
```

## 安全边界

- 小红书侧只通过仓库内的 `python scripts/cli.py topic2feishu` 操作；
- 飞书侧只通过官方 `lark-cli base` 命令写入；
- 写入 Base 是外部状态变更，执行前必须确认目标表、记录数量和字段映射；
- 不迁移或公开 `.lark-cli`、浏览器 profile、Cookie、Token 或 App Secret；
- 批量读取详情要控制频率，默认每处理约 3 篇后等待；
- 采集结果可能包含第三方内容，只在合法授权范围内使用和再发布。

## 相关文档

- [小红书技能集合总览](../../README.md)
- [内容发现与分析](../xhs-explore/README.md)
- [复合内容运营](../xhs-content-ops/README.md)
