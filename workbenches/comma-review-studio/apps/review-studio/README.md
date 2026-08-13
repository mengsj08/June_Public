# Comma Review Studio · 本地宿主说明

本目录是 Comma Editor Kit 的完整 reference host。编辑器核心只负责 Markdown 渲染、
编辑与锚定评论；本地宿主负责文件系统、CLI provider、评审台账、版本恢复、导入导出和
冲突处理。

普通使用者请先阅读项目根目录的 [`../../README.md`](../../README.md)。本文面向需要
调试、迁移或验证本地宿主的维护者。

## 启动

先在项目根目录安装并构建编辑器：

```bash
npm ci
npm run build
```

然后启动本地宿主：

```bash
COMMA_REVIEW_PORT=8891 python3 apps/review-studio/server.py
```

打开：

```text
http://127.0.0.1:8891/?doc=paper.md
```

使用仓库外私有目录：

```bash
COMMA_REVIEW_DATA_ROOT=/absolute/private/directory \
COMMA_REVIEW_PORT=8891 \
python3 apps/review-studio/server.py
```

`--host` 只接受 `127.0.0.1` 或 `localhost`。v0 不支持 `::1`、wildcard、LAN 地址或远程
Review Studio。

## 宿主负责什么

| 模块 | 责任 |
| --- | --- |
| 文档访问 | 把所有文件访问限制在选定 data root；Markdown 是主稿事实源 |
| Provider 能力 | 探测 Codex、Claude 和可用 Gateway 的版本与只读登录状态 |
| 结构化评审 | 异步运行、取消进程树、保存 run 状态与失败原因 |
| Comment 生命周期 | revision-locked 写回、锚点核验、旧 sidecar 兼容与迁移 |
| Quote 对话 | 选区范围内快速解释、深入讨论、父子消息、显式分叉与评论写回 |
| 版本中心 | 内容寻址快照、命名 checkpoint、恢复时间线与冲突草稿 |
| 导入导出 | DOCX → Markdown；Markdown、带评论 Markdown、Review Package ZIP、可选 DOCX/PDF |
| 数据审计 | 只输出计数、警告码与脱敏路径，不打印稿件或评论正文 |

## Provider 能力探测

`GET /api/runtime/capabilities` 返回 Codex / Claude / Gateway 的安装、版本、登录就绪度和
支持能力。页面头部 badge、快速解释、引用讨论和结构化评审使用同一个 resolver，缺失
provider 会在调用前禁用，而不是返回假成功。

显式指定 CLI：

```bash
COMMA_REVIEW_CODEX_BIN=/absolute/path/to/codex \
COMMA_REVIEW_CLAUDE_BIN=/absolute/path/to/claude \
python3 apps/review-studio/server.py
```

能力探测只运行 `--version` 和只读登录状态命令；认证输出会被丢弃，页面加载不会自动
触发模型。

运行状态包括 `queued`、`running`、`cancelling`、`cancelled`、`completed` 与 `failed`。
队列和活跃进程注册表位于内存：宿主重启不会恢复正在进行的模型调用；启动时会把持久化
的活跃 run 标成带恢复原因的 failed。

## 版本与恢复

每次成功保存都会在 `<data-root>/.comma-review/versions/` 生成内容寻址快照。命名版本只
指向同一不可变内容；恢复某个版本会新增时间线事件，不删除后来历史。

如果保存时乐观 revision 检查失败：

1. 尝试保存的正文进入 `.comma-review/drafts/`；
2. 页面重新载入磁盘最新 revision；
3. 用户可以比较 diff、执行 revision-checked 恢复或放弃草稿。

Review Package ZIP 可包含稿件、文档相对图片、评论、匹配的评审/对话账本、每文档
hash-only `CommentEvent` 账本与版本快照；全局事件账本和原始 AI trace 被排除。

DOCX / PDF 导出依赖本机 LibreOffice。自动探测不合适时：

```bash
COMMA_REVIEW_SOFFICE_BIN=/absolute/path/to/soffice python3 server.py
```

## Comment 迁移

旧 comment sidecar 默认只读兼容，不会因为打开文档而被重写。先对复制的数据目录运行
dry-run：

```bash
python3 migrate_slice_a.py --data-root /absolute/path/to/copied-data
```

只有明确授权后才使用 `--apply`。应用前会验证全部记录，并在第一次规范化写入前，把
sidecar / session 原字节备份到 `.comma-review/migration-backups/`。命令只报告计数和
字段名，不打印正文。

## Store Audit

```bash
python3 review_store_audit.py --data-root /absolute/path/to/data
python3 review_store_audit.py --data-root /absolute/path/to/data --json
```

退出码：

| 退出码 | 含义 |
| --- | --- |
| `0` | 数据结构干净 |
| `1` | 可读但有警告：旧 schema、孤立 sidecar、缺文档、版本/证据不配对、未完成 journal |
| `2` | 数据无法安全读取或解析 |

JSON 与文本输出只包含计数、脱敏路径、warning code 和 error code。

## 验证

从项目根目录运行：

```bash
npm run test:review
CI=true python3 -m pytest apps/review-studio/ -q
```

`pytest` 收集 API、orchestrator 与生命周期合同测试，但不执行 `test_headless.py`；后者是
带 `main()` 的 Playwright 验收脚本。

浏览器验收需要先启动 8891 服务，再运行：

```bash
CI=true COMMA_REVIEW_PORT=8891 python3 apps/review-studio/test_headless.py
CI=true COMMA_REVIEW_PORT=8891 python3 apps/review-studio/test_blocks.py
```

需要 Playwright 和兼容 Chromium。

## 隐私边界

不得提交 data root、真实稿件、comment sidecar、review session、quote conversation、
事件账本、日志、截图、模型原始 trace、migration backup 或恢复草稿。诊断与审计输出也
不得打印私有正文。

API 和写回合同见 [`REVIEW_WORKFLOW.md`](REVIEW_WORKFLOW.md)。`SPIKE_REPORT.md` 只作为
迁移来源保留，不是当前产品说明。
