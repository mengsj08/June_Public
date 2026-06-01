# xhs-explore

小红书内容发现与分析 skill。

## When To Use

- 搜索关键词相关笔记。
- 获取首页推荐 Feed。
- 查看某条笔记的完整内容和评论。
- 查看用户主页信息。

## Quick Start For AI

示例提示词：

```text
使用 xhs-explore，搜索“小红书 AI 教育”图文笔记，按最多点赞排序，整理前 5 条。
```

```text
使用 xhs-explore，读取这条笔记的详情和评论：feed_id=...，xsec_token=...
```

## Commands

```bash
python scripts/cli.py search-feeds --keyword "关键词" --sort-by "最多点赞" --note-type "图文"
python scripts/cli.py list-feeds
python scripts/cli.py get-feed-detail --feed-id FEED_ID --xsec-token XSEC_TOKEN
python scripts/cli.py user-profile --user-id USER_ID --xsec-token XSEC_TOKEN
```

## Inputs

- 搜索关键词。
- 可选筛选：排序、笔记类型、发布时间、搜索范围、地点。
- 详情读取需要成对的 `feed_id` 和 `xsec_token`。

## Output

- 结构化搜索结果。
- 笔记标题、作者、互动数据、正文、图片、评论。
- 用户主页基础信息。

## Safety

- 批量读取详情时，每 3 篇左右插入等待，避免连续高频访问。
- 只通过 `python scripts/cli.py` 操作，不混用其他小红书工具。
- 不把登录态、cookies 或 token 写入公开文档。
