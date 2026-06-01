# xhs-interact

小红书互动 skill，用于评论、回复、点赞和收藏。

## When To Use

- 给指定笔记发表评论。
- 回复某条评论或某个用户。
- 点赞或取消点赞。
- 收藏或取消收藏。

## Quick Start For AI

示例提示词：

```text
使用 xhs-interact，给这条笔记发表评论。feed_id=...，xsec_token=...，评论内容先让我确认。
```

```text
使用 xhs-interact，收藏这条笔记：feed_id=...，xsec_token=...
```

## Commands

```bash
python scripts/cli.py post-comment \
  --feed-id FEED_ID \
  --xsec-token XSEC_TOKEN \
  --content "评论内容"

python scripts/cli.py reply-comment \
  --feed-id FEED_ID \
  --xsec-token XSEC_TOKEN \
  --comment-id COMMENT_ID \
  --content "回复内容"

python scripts/cli.py like-feed --feed-id FEED_ID --xsec-token XSEC_TOKEN
python scripts/cli.py favorite-feed --feed-id FEED_ID --xsec-token XSEC_TOKEN
```

## Inputs

- `feed_id`。
- `xsec_token`。
- 评论或回复内容。
- 可选：`comment_id` 或 `user_id`。

## Safety

- 评论和回复必须先经用户确认。
- 控制互动频率，不做高频批量点赞、评论或收藏。
- 点赞和收藏是幂等操作，但仍需确认用户意图。
- 不使用本项目外的小红书互动工具。
