# Canvas Studio client

本目录暂存从 `canvas-studio` 选择性搬入的 Vite/React 客户端源码与构建配置。

客户端通过同源看板 API 加载与保存画布。默认构建产物位于仓内 `dist/`，由
`../start.sh` 自动构建并挂载到 `/canvas/`。`SystemAlertBadge.tsx` 已随其调用方
一并纳入公开快照；缺少可选系统告警后端时组件会静默隐藏。

安全拓扑只有一种受支持默认：由看板后端在 loopback 上同源托管 `/canvas/` 与
`/api/`。Vite dev proxy 只是开发便利，不是认证或跨源安全边界；独立前端或远程
部署必须另做真实认证、TLS cookie、CSRF 与反向代理评审，本阶段不宣称支持。
