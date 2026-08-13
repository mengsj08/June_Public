# Comma Chrome Side Panel

这是 Comma Editor 的 Chrome Manifest V3 Side Panel 外壳。它让使用者在当前网页旁边
打开一个本地 Markdown / 批注面板，并在明确点击后抓取当前页内容。

它不是 Comma Review Studio 的完整 Python 宿主：不提供本地 CLI 模型评审、文件系统
版本中心或服务器端 Review Package。需要完整稿件工作流时，请使用
[`../README.md`](../README.md)。

## 构建

从项目根目录运行：

```bash
npm ci
npm run build:chrome
npm run validate:chrome
```

可加载目录为：

```text
release/chrome-extension/
```

不要直接加载本源码目录，因为 `dist/comma-editor.js` 和打包清单由构建过程生成。

## 在 Chrome 中加载

1. 打开 `chrome://extensions/`；
2. 开启“开发者模式”；
3. 点击“加载已解压的扩展程序”；
4. 选择 `release/chrome-extension/`；
5. 从扩展入口打开 Side Panel。

重新构建后，在扩展管理页点击刷新，再重开 Side Panel。

## 用户动作边界

当前网页内容只会在用户点击 **Capture page** 后提取。扩展不会后台遍历标签页，也不会
自动把页面发给模型。

| 能力 | Side Panel 是否提供 |
| --- | --- |
| 用户触发的当前页提取 | 是 |
| 本地 Markdown 与评论 | 是 |
| `chrome.storage.local` 持久化 | 是 |
| 后台 cookie / profile 读取 | 否 |
| debugger / webRequest 权限 | 否 |
| 远程脚本 | 否 |
| Codex / Claude 模型调用 | 否 |
| Python 宿主版本与导出中心 | 否 |

## 安全设计

- 不申请 persistent host permissions；
- 不读取 cookie、密码、浏览器 profile 或登录数据库；
- 不使用 debugger、webRequest 或远程代码；
- 抓取只发生在当前用户选中的页面和显式点击之后；
- 抓取后的 Markdown、批注与事件保存在 `chrome.storage.local`；
- 清除扩展数据或卸载扩展前，应先导出需要保留的内容。

## 验证

```bash
npm run build:chrome
npm run validate:chrome
```

扩展继承项目根目录的源码许可边界；第三方组件见根目录
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。
