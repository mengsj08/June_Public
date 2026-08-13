# Skills

这里收录的是可以交给 Codex、Claude 等 Agent 执行的公开工作流包。每个 Skill 都以
`SKILL.md` 作为机器可读的执行合同，以 README 作为人的使用入口；脚本、模板和参考资料
只服务于该 Skill，不要求把整个仓库一次性安装。

## Skill 目录

| 领域 | Skill | 适合解决的问题 | 依赖 |
| --- | --- | --- | --- |
| 研究工具 | [Author Literature Map](research-tools/author-literature-map/) | 已确认作者身份后，生成来源可追溯、可检测证据漂移的文献地图 | Python 3.9+；在线补充可选 |
| 内容可视化 | [Article Visualization](ip-operations/article-visualization/) | 文章 / 论文 → 科普长图、小红书卡、公众号封面与短文 | Node.js 21+、Chrome |
| 平台运营 | [小红书自动化 Skills](ip-operations/xiaohongshu-skills/) | 小红书认证、搜索、发布、互动、复合运营与飞书 Base 入库 | Python 3.11+、uv、Chrome 扩展；飞书写入时需 lark-cli |

## 怎么使用

### 方式一：直接交给 Agent

把目标 Skill 目录交给本地 Agent，并明确要求它先阅读合同：

```text
请完整阅读这个目录的 SKILL.md 和 README.md，先检查依赖与账号边界，再按 Skill 规定
执行。任何发布、评论、写入外部系统或大规模下载，都要在动作前让我确认。
```

### 方式二：安装到 Agent 的 Skill 目录

不同 Agent 的发现目录和安装方式并不相同。请先查看所用工具的官方说明，再复制**单个
Skill 目录**。不要把 `skills/` 整棵目录直接塞进系统级发现路径，也不要覆盖已有同名
Skill。

安装前至少检查：

1. `SKILL.md` 的 `name` 与触发描述是否符合预期；
2. 项目需要的 Python / Node / Chrome / CLI 是否存在；
3. 是否会操作账号、发送内容或写入外部系统；
4. 许可证是否允许你的使用方式；
5. 是否存在同名旧版本，需要先比较再替换。

## Skill 与 Workbench 的区别

- **Skill**：告诉 Agent 何时触发、如何执行、何时停下，以及产物放在哪里。
- **Workbench**：提供持续运行的本地服务、浏览器 UI、任务状态和人工交互界面。
- 一个 Workbench 可以带 `SKILL.md` 作为安装/启动入口，但不因此变成纯 Skill。

需要界面操作长文档时，请转到 [`../workbenches/`](../workbenches/)。

## 安全边界

- 本目录不保存账号状态、cookie、token、API key、浏览器 profile 或本地 CLI 配置。
- 发布、评论、点赞、收藏、写入飞书等外部动作必须遵守各 Skill 的人工确认规则。
- 科学、医学和数据类输出必须回到原文或数据源核实，不能用视觉效果替代证据。
- 真实 case、下载图片、运行态 HTML、采集 JSON、未发布草稿与日志应放在仓库外。
- 各 Skill 许可证独立；公开可见不代表自动获得商用或再分发权限。

## 维护者验证

每个 Skill 的测试命令都不同：

- `author-literature-map`：可用合成数据离线构建账本与 HTML。
- `article-visualization`：检查 Node 脚本语法，并用公开样例跑渲染和密度检查。
- `xiaohongshu-skills`：`uv sync --extra dev && PYTHONPATH=scripts uv run pytest`；可另跑 `uv run ruff check .` 查看现存静态检查欠账，真实账号动作不属于离线测试。
