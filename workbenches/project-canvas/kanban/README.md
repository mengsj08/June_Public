# Kanban service

本目录暂存从 `kanban-personal` 选择性搬入的服务端、静态前端、schema 与测试。

身份由配置中的 owner/operator/reviewer 角色映射。路径边界由 `paths`、
`open_allowed_roots` 与明确的集成配置声明；所有外部工作区和兄弟工具默认关闭。
示例成员、demo 扫描路径和完整 opt-in 占位见 `.kanban.config.example.json`。

从仓库根目录运行 `./start.sh`。`DEPLOYMENT.md` 说明本地运行边界及远程部署
尚未满足的安全门槛。
