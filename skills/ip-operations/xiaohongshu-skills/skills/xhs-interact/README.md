# xhs-interact

> 在人工确认后执行评论、回复、点赞和收藏。

互动操作会直接改变外部账号和平台状态，因此 `xhs-interact` 把“生成建议”和“真正执行”分开。Agent 可以先准备评论或回复文本，但只有用户确认目标与最终内容后才能运行命令。

## 支持的操作

- 给指定笔记发表评论；
- 回复指定评论或用户；
- 点赞或取消点赞；
- 收藏或取消收藏。

## 命令示例

发表评论：

```bash
python scripts/cli.py post-comment \
  --feed-id FEED_ID \
  --xsec-token XSEC_TOKEN \
  --content "经用户确认的评论内容"
```

回复评论：

```bash
python scripts/cli.py reply-comment \
  --feed-id FEED_ID \
  --xsec-token XSEC_TOKEN \
  --comment-id COMMENT_ID \
  --content "经用户确认的回复内容"
```

点赞与收藏：

```bash
python scripts/cli.py like-feed \
  --feed-id FEED_ID \
  --xsec-token XSEC_TOKEN

python scripts/cli.py favorite-feed \
  --feed-id FEED_ID \
  --xsec-token XSEC_TOKEN
```

## 推荐交互

```text
Agent 读取目标内容（只读）
        ↓
生成评论 / 回复草稿
        ↓
向用户展示目标、全文和将执行的动作
        ↓
用户明确确认
  ├─ 修改 / 取消 → 不执行
  └─ 确认       → 执行一次并回报结果
```

示例提示词：

```text
使用 xhs-interact 为这条笔记起草一条评论。先给我看完整评论和目标笔记，不要执行；等我明确说“发送”后再操作。
```

## 输入

| 输入 | 用途 |
| --- | --- |
| `feed_id` + `xsec_token` | 定位目标笔记 |
| `content` | 评论或回复的最终文本 |
| `comment_id` | 回复指定评论时使用 |
| `user_id` | 某些回复路径用于定位用户 |

## 安全边界

- 评论和回复必须逐次确认最终文本与目标；
- 点赞、取消点赞、收藏和取消收藏也需要明确用户意图；
- 不执行高频、批量、无人值守互动；
- 操作后只报告结果，不输出 Cookie、Token 或浏览器状态；
- 如果目标标识失效、登录状态异常或页面变化，停止并让用户重新确认；
- 不使用本项目之外的互动工具绕过限制。

## 相关文档

- [内容发现与分析](../xhs-explore/README.md)
- [复合内容运营](../xhs-content-ops/README.md)
