# OpenClaw Skills 🦞

欢迎来到 **OpenClaw Skills** 仓库！这里收集了一系列为 OpenClaw 平台设计的「入职与配置向导」技能（Skills）。

这些技能的设计初衷，是将枯燥的 Markdown 配置文件编写过程，转化为有趣、互动、游戏化的对话体验，帮助无论是技术小白还是重度玩家，都能轻松配置出自己的专属「数字龙虾」。

## 🌟 核心设计理念

- **游戏化比喻**：将 AI 智能体比作「数字龙虾」，将配置文件比作「工牌」、「灵魂」、「岗位说明书」和「闹钟」。
- **场景导向 (Scenario-Oriented)**：不再让用户对着空白文件发呆，而是通过「入职面试」的场景引导用户表达需求。
- **双模体验 (Quick / Deep Mode)**：
  - **简要模式 (Quick)**：只需一句话，AI 利用推理能力自动补全所有细节，适合线下快速演示或新手体验。
  - **详细模式 (Deep)**：多步骤深度问答，完全量身定制，适合需要精细控制的重度用户。

## 📦 技能列表 (Skills)

目前包含以下 7 个核心技能：

### 1. 🚀 大一统入职向导 (推荐)
- **`openclaw-onboarding-wizard`**：首席数字员工入职面试。一次对话，5 分钟内自动生成完整的 5 个核心配置文件（USER, IDENTITY, SOUL, AGENTS, HEARTBEAT）。支持 Quick/Deep 双模。**这是新手入门的最佳入口。**

### 2. 🧩 独立配置向导
如果您只需要单独更新某个配置文件，可以使用以下独立向导：

- **`openclaw-beginner-guide`**：龙虾领养指南。用 30 秒电梯演讲或 5 分钟互动游戏，解释 OpenClaw 的核心运作逻辑。
- **`openclaw-soul-collector`**：灵魂注入中心。生成 `SOUL.md`，定义龙虾的核心真理、绝对边界和沟通风格。
- **`openclaw-agents-builder`**：岗位配置中心。生成 `AGENTS.md`，划定工作流和红/黄/绿灯三级权限系统。
- **`openclaw-heartbeat-builder`**：自动巡检配置中心。生成 `HEARTBEAT.md`，设置龙虾的定时巡检任务和日常闹钟。
- **`openclaw-user-builder`**：老板档案收集器。生成 `USER.md`，让龙虾记住你是谁、你的工作背景和个人偏好。
- **`openclaw-identity-builder`**：工牌制作器。生成 `IDENTITY.md`，定义龙虾的对外名称、emoji 和气质。

## 🚀 如何使用

1. 将本仓库克隆或下载到本地。
2. 将需要的技能文件夹（如 `openclaw-onboarding-wizard`）放入您的 OpenClaw 技能目录中（通常是 `~/.openclaw/skills/`）。
3. 在 OpenClaw 聊天界面中，输入指令调用该技能（例如：`/skill openclaw-onboarding-wizard`）。
4. 按照提示完成对话，技能将自动为您生成配置文件草稿。
5. 将生成的 Markdown 内容保存到您的 `~/.openclaw/workspace/` 目录下即可生效。

## 🔄 v2.0 更新说明
- 引入了统一的 **Quick/Deep 双模选择**。
- 将 5 个独立的配置向导整合为 **`openclaw-onboarding-wizard`**，大幅优化了首次配置的体验，避免了重复询问。

---
*Built with ❤️ for OpenClaw*
