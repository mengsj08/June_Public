# Third-party services and notices

本项目自身没有运行时第三方 Python 依赖。可选在线 Adapter 会访问使用者自行启用的公共服务：

- NCBI E-utilities / PubMed
- arXiv API
- RSS / Atom feeds selected by the user
- Hacker News Firebase API
- OpenAlex API
- user-configured IMAP servers

这些服务的可用性、速率限制、内容许可、隐私政策和使用条款由对应运营方决定。本项目不缓存或再分发真实上游页面；仓库中的所有测试数据均为合成内容。

使用者应为高频请求配置合适的联系邮箱或 User-Agent，遵守速率限制，并避免把摘要元数据误当成全文再分发许可。
