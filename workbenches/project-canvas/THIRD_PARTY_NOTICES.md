# Third-party notices — Project Canvas

本目录不 vendor 第三方源码;以下依赖经包管理器在使用者本机安装,各自保留原许可证。

## Python(`kanban/requirements.txt`,运行时)

| 依赖 | 用途 | 许可证 |
| --- | --- | --- |
| watchdog | git-sync 文件监控(默认关闭) | Apache-2.0 |
| PyYAML | Conversation Map manifest 解析 | MIT |

开发依赖(`kanban/requirements-dev.txt`):pytest(MIT)、pytest-randomly(MIT)。

## Node(`canvas-studio/package.json`,画布前端)

| 依赖 | 用途 | 许可证 |
| --- | --- | --- |
| react / react-dom | UI 框架 | MIT |
| reactflow / @reactflow/node-resizer | 画布节点与连线 | MIT |
| zustand | 状态管理 | MIT |
| react-markdown / remark-gfm / rehype-highlight | Markdown 渲染与高亮 | MIT |
| vite / @vitejs/plugin-react | 构建工具 | MIT |

其余传递依赖见各包 lockfile;`npm ls --all` 可在本机核对完整树。
