# xhs-explore

> 搜索、读取和分析小红书公开内容的只读入口。

`xhs-explore` 用于发现候选笔记、读取正文与评论、查看用户主页，并把结果交给 Agent 做结构化分析。它本身不发布、不评论，也不改变点赞或收藏状态。

## 适用场景

- 按关键词和筛选条件搜索笔记；
- 获取当前首页推荐 Feed；
- 读取指定笔记的完整内容、图片信息和评论；
- 查看作者公开主页；
- 为竞品研究、选题研究或内容策略提供证据。

## 快速开始

搜索图文笔记：

```bash
python scripts/cli.py search-feeds \
  --keyword "AI 教育" \
  --sort-by "最多点赞" \
  --note-type "图文"
```

读取首页 Feed：

```bash
python scripts/cli.py list-feeds
```

读取笔记详情与作者主页：

```bash
python scripts/cli.py get-feed-detail \
  --feed-id FEED_ID \
  --xsec-token XSEC_TOKEN

python scripts/cli.py user-profile \
  --user-id USER_ID \
  --xsec-token XSEC_TOKEN
```

## 关键输入

| 输入 | 说明 |
| --- | --- |
| `keyword` | 搜索关键词 |
| 排序与筛选 | 可按排序、笔记类型、发布时间、搜索范围、地点筛选 |
| `feed_id` | 笔记标识 |
| `xsec_token` | 与该笔记结果配套的访问参数；需和 `feed_id` 成对使用 |
| `user_id` | 作者主页标识 |

## 推荐输出格式

对多条笔记做分析时，建议先列证据表，再写推断：

| 标题 | 作者 | 类型 | 点赞/收藏/评论 | 正文结构 | 来源标识 |
| --- | --- | --- | --- | --- | --- |
| … | … | … | … | … | `feed_id` |

无法读取或缺失的数据应标为“未获取”，不能由 Agent 猜测补齐。

## 交给 Agent 使用

```text
使用 xhs-explore 搜索“AI 教育”图文笔记，按最多点赞排序，读取前 5 条详情。用表格区分原始数据和你的分析；控制访问频率，不执行任何互动。
```

## 安全边界

- 只通过 `python scripts/cli.py` 操作，不混用其他小红书工具；
- 批量读取详情时，每处理约 3 篇插入等待，避免连续高频访问；
- 不把 Cookie、登录态或 Token 内容写入公开文档；
- 搜索结果会变化，报告中应记录采集时间和筛选条件；
- 公开可见不等于可任意转载，使用第三方内容时仍需遵守平台规则与版权要求。

## 相关文档

- [复合内容运营](../xhs-content-ops/README.md)
- [采集并写入飞书](../topic2feishu-xhs/README.md)
