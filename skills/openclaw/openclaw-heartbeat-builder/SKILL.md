---
name: openclaw-heartbeat-builder
description: A specialized workflow for collecting user information through a structured Q&A process to generate a customized HEARTBEAT.md configuration file for OpenClaw AI agents. Now supports both Quick Mode (for fast onboarding) and Deep Mode (for detailed customization).
---

# OpenClaw HEARTBEAT Builder: 自动巡检闹钟定制向导 (v2.0)

This skill guides you through a structured interview process with the user to collect the necessary information for generating a highly personalized `HEARTBEAT.md` file for their OpenClaw AI agent.

## Core Philosophy

As detailed in the OpenClaw documentation, `HEARTBEAT.md` is the agent's **"Alarm Clock & Patrol Checklist" (闹钟与巡检清单)**. It defines what the agent should proactively do when it "wakes up" on its own schedule (default is every 30 minutes).

## Workflow: The Two-Stage Process

When triggered, execute the following steps sequentially.

**CRITICAL RULES FOR ASKING QUESTIONS:**
1. **Ask ONE question at a time.** Never ask multiple questions in a single message.
2. **Wait for the user's response** before proceeding to the next question.

### Step 0: Mode Handling

**IMPORTANT:** This skill is designed to be called as part of the `openclaw-onboarding-wizard` flow, where the user has already selected a mode (Quick or Deep) at the very beginning. **Do NOT ask the user to choose a mode again.** Simply check which mode was selected and proceed to the corresponding path.

- If the mode is **Quick (A)**, go to PATH A.
- If the mode is **Deep (B)**, go to PATH B.
- If this skill is used standalone (not via the wizard), then and only then ask the user to choose a mode.

---

### PATH A: Quick Mode (简要模式)

#### Quick Step 1: The Core Prompt
**Message to send:**
"您选择了【简要模式】。
如果龙虾每半小时醒来一次，您最希望它帮您盯什么？
（例如：'盯客户群消息和提醒开会'）"

*(Wait for user response. Then use your AI reasoning to automatically deduce the Every Heartbeat tasks and Daily Routine based on this single input. Proceed directly to Step 4: Draft Generation, but make sure to append the standard Security Warning in the draft message.)*

---

### PATH B: Deep Mode (详细模式)

#### Deep Step 1: Communication & Message Monitoring (沟通与消息巡检)
**Message to send:**
"您选择了【详细模式】。
第一步，我们来设置**消息巡检**。
当龙虾每 30 分钟醒来时，您最希望它帮您盯住哪些渠道？（例如：'盯客户邮件' 或 '盯团队群聊里的进度'）"
*(Wait for user response, validate, then proceed to Deep Step 2)*

#### Deep Step 2: Schedule & Task Management (日程与任务管理)
**Message to send:**
"第二步，**日程与任务管理**。
除了盯消息，在时间管理上，您需要它帮您做什么？（例如：'每天早上 8:30 给我发今日待办，开会前 30 分钟提醒我'）"
*(Wait for user response, validate, then proceed to Deep Step 3)*

#### Deep Step 3: Security Warning & Constraints (安全警告与边界)
**Message to send:**
"第三步，**安全红线确认**。
为了您的安全，我必须和您确认：**在接下来的清单里，绝对不能包含任何密码、API 密钥或真实的客户隐私数据。** 所有的操作都必须通过调用本地工具（Tools）或环境变量来完成。
您可以接受这条红线吗？（回复『确认』即可）"
*(Wait for user response. If confirmed, proceed to Step 4.)*

---

### Step 4: Draft Generation and Review (Common for both paths)

**Action:** Synthesize the collected information into a draft `HEARTBEAT.md` file.

**Format Rules for Draft:**
- Use a clear Markdown list structure.
- Group tasks logically (e.g., `## Every Heartbeat (30 mins)`, `## Daily Routine`).
- Keep descriptions actionable for the AI.

**Message to send:**
"信息收集完毕！这是为您定制的 `HEARTBEAT.md`（自动巡检清单）草稿，请您过目：

```markdown
(Insert generated HEARTBEAT.md draft here)
```

**老板，您看看这份巡检清单是否覆盖了您的核心需求？有没有需要调整的频次或增加的场景？**"

### Step 5: Finalization
Once the user approves the draft, use the `file` tool to save the final content to a file named `HEARTBEAT.md` in the current working directory, and provide the user with instructions on where to place it in their OpenClaw workspace.
