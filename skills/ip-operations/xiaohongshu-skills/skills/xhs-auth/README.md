# xhs-auth

小红书登录与认证管理 skill。

## When To Use

- 检查当前浏览器中的小红书是否已登录。
- 引导用户扫码或短信验证码登录。
- 清除本地小红书 cookies 并退出登录。

## Quick Start For AI

读取 `SKILL.md` 后，只使用根项目的 CLI：

```bash
python scripts/cli.py check-login
```

示例提示词：

```text
使用 xhs-auth，检查我当前小红书账号是否已经登录。
```

```text
使用 xhs-auth，引导我完成小红书扫码登录。
```

## Commands

| Command | Purpose |
| --- | --- |
| `check-login` | 检查登录状态，未登录时可返回二维码信息 |
| `get-qrcode` | 单独刷新二维码 |
| `wait-login` | 等待扫码完成 |
| `send-code --phone` | 发送短信验证码 |
| `verify-code --code` | 提交验证码 |
| `delete-cookies` | 退出登录并清除 cookies |

## Safety

- 每次短信登录都必须重新向用户确认手机号。
- 不从历史上下文、记忆或文件中自动填入手机号。
- 不频繁重复登录、退出登录，避免触发账号风控。
- 不输出 cookies、token 或本地浏览器 profile 内容。
