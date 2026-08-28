# Privacy Boundary

## 公开能力与私有实例分离

本项目公开 Adapter、schema、筛选机制、Profile Engine、LLM 接口、Sink 接口和合成示例。以下实例状态不得进入仓库：

- 真实 profile、主题权重、作者/机构 watchlist；
- 邮件、Feishu/Lark、Stork、浏览器 snapshot；
- cookie、浏览器 profile、OAuth 文件、token、API key；
- 真实日报、state、receipt、日志、阅读/收藏状态；
- webhook、群聊、Base、表格、收件人与发布账号标识；
- 模型输入、输出、trace 和包含私人上下文的缓存；
- 客户、团队、会议、患者或未发表研究材料。

## 正向字段白名单

公开 demo 只允许以下内容字段：

```text
item_id, source_id, source_kind, title, url, published_at,
summary, authors, tags, event_type, provenance,
topic_relevance, method_novelty_hint, reading_tier, freshness_gate,
llm_triage
```

任何额外字段必须先进入 schema 审核；不要依赖删除已知敏感字段的黑名单。

## 凭据

配置只能声明环境变量名称，例如 `SIH_IMAP_PASSWORD`，不得记录其值。诊断工具如需检查环境变量，只能报告是否存在，不能打印内容；当前 `doctor` 不读取凭据环境变量。

## 浏览器与账号型来源

浏览器 Connector 读取使用者显式导出的 snapshot。它不访问 cookie 数据库、profile 目录、密码、历史记录或系统 Keychain。账号型 Connector 默认禁用，需使用者在仓库外配置。

## 网络发送

网络 Sink 需要显式配置与 `--publish`。`--live` 只授权数据抓取，不授权发送；`--llm` 只授权模型调用，不授权发送。
