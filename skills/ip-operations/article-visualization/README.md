# article-visualization

把文章、研究博客或论文重新设计成给外行也能看懂的科普可视化素材。它不是逐字排版器，而是先提炼事实与叙事，再分流生成长图、小红书图文卡、公众号封面和短文。

## When To Use

| Scenario | Use this skill |
| --- | --- |
| 一篇论文需要转成大众科普图文 | Yes |
| 技术博客需要做成长图或社媒卡片 | Yes |
| 想先确认 Page Plan，再渲染图片 | Yes |
| 只想把 Markdown 原样转成公众号排版 | No |

## Outputs

- 科普长图：连续 HTML 页面和 2x 长图截图。
- 小红书图文卡：一张卡一个观点，支持主题库和密度检查。
- 公众号封面：2.35:1 首图和 1:1 次图。
- 短文素材：适合 X/Twitter 或其他社媒的短文版本。

## Example Prompts

```text
使用 article-visualization，读取这篇论文，先提炼事实清单和受众定位，再给我小红书 Page Plan。
```

```text
使用 article-visualization，把这篇技术博客做成科普长图和公众号封面。主题偏冷静技术风，不要暖色科普风。
```

```text
使用 article-visualization，基于已有 brief.md 渲染小红书卡片，并运行密度检查。
```

## Safety Boundary

公开仓库只保存 skill、模板、脚本、参考说明和可公开示例。真实项目运行材料必须留在使用者本机：

- 不提交真实 case 目录、下载图片、截图、运行态 HTML 或未发布草稿。
- 不提交 API key、cookie、账号状态、浏览器 profile、`.env` 或私有日志。
- 医学、科学和数据类内容必须回到原文核实，不编造数字或图。

核心使用说明见 [`SKILL.md`](SKILL.md)，主题与卡片配方见 [`references/themes.md`](references/themes.md) 和 [`references/xhs-recipes.md`](references/xhs-recipes.md)。
