# xhs-publish

> 支持图文、视频和长文的“先填入、再预览、后确认发布”工作流。

`xhs-publish` 将准备内容与真正发布拆成两个动作。推荐先使用 `fill-*` 把标题、正文和媒体填入创作服务平台，让用户在浏览器中检查最终预览；只有用户明确确认后，Agent 才能运行 `click-publish`。

## 支持的内容类型

- 图文笔记；
- 视频笔记；
- 长文及模板排版；
- 只填写发布页、不点击发布；
- 可选标签、定时发布、可见性和原创标记。

## 推荐发布流程

```text
准备标题、正文与媒体
        ↓
检查文件存在、格式与标题长度
        ↓
fill-* 填入发布页
        ↓
用户检查浏览器最终预览
  ├─ 修改 / 取消 → 返回编辑，不发布
  └─ 明确确认   → click-publish
                        ↓
                  回报发布结果
```

## 图文发布

先填入：

```bash
python scripts/cli.py fill-publish \
  --title-file /abs/path/title.txt \
  --content-file /abs/path/content.txt \
  --images "/abs/path/image1.jpg" "/abs/path/image2.jpg"
```

确认后发布：

```bash
python scripts/cli.py click-publish
```

## 视频发布

```bash
python scripts/cli.py fill-publish-video \
  --title-file /abs/path/title.txt \
  --content-file /abs/path/content.txt \
  --video "/abs/path/video.mp4"
```

填入成功不等于已经发布。只有随后执行 `click-publish` 才会触发最终外部动作。

## 输入要求

| 输入 | 要求 |
| --- | --- |
| 标题 | 按 `SKILL.md` 的 UTF-16 规则控制在 20 单位以内 |
| 正文 | 建议通过文件传入，便于审阅和保留换行 |
| 图片 | 使用绝对路径或图片 URL；图文发布至少需要图片 |
| 视频 | 使用绝对路径；不能与图文媒体混合 |
| 发布设置 | 标签、时间、可见性、原创标记均应在预览时核对 |

## 交给 Agent 使用

```text
使用 xhs-publish 将下面的标题、正文和图片填入小红书发布页。先不要发布；等我检查浏览器预览并明确说“发布”后，才能点击发布。
```

## 常见问题

**社区页面已登录，但发布页仍不可用？**

创作服务平台可能有独立登录状态，需要单独检查，不能只依据社区页面判断。

**图片是 URL，需要先手动下载吗？**

不需要。按 Skill 约定把 URL 交给脚本处理。

**用户只说“帮我填好”呢？**

只运行 `fill-*`，停在浏览器预览，不运行 `click-publish`。

## 安全边界

- 发布前必须展示并确认标题、正文、媒体和关键发布设置；
- “预览”“填好”“先看看”都不构成发布授权；
- 不混合图文与视频，不使用相对路径；
- 不自动高频发布或绕过平台确认；
- 不输出登录态、Cookie 或 Token；
- 第三方图片、视频和文字必须具有合法使用权限。

## 相关文档

- [登录与认证](../xhs-auth/README.md)
- [复合内容运营](../xhs-content-ops/README.md)
