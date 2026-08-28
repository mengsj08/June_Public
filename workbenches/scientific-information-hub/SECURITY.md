# Security

## 默认安全状态

- 离线；
- 不调用 LLM；
- 不发送网络 Sink；
- 不读取浏览器 profile；
- 不扫描用户主目录；
- 不在仓库中保存凭据。

## 报告问题

请勿在公开 Issue 中粘贴 token、邮件、内部 URL、真实日报或个人配置。使用最小合成复现，并说明 Python 版本、命令、错误类型和受影响模块。

## Connector 约束

- HTTP 请求设置超时、User-Agent 和有限重试；
- 只接受 `http` / `https` 外部 URL；
- 文件 Connector 只读取配置中明确给出的路径；
- IMAP 凭据只来自环境变量；
- Webhook endpoint 只来自环境变量，并要求 `--publish`；
- HTML 输出必须转义不可信标题、摘要、标签和 URL。

## 不支持

本项目不提供 cookie 提取、验证码绕过、浏览器 profile 复制、凭据持久化、网站安全警告绕过或无人审核的社交平台发布。
