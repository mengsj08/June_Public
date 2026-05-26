---
name: openclaw-agents-builder
description: A specialized workflow for collecting user information through a structured Q&A process to generate a customized AGENTS.md configuration file for OpenClaw AI agents. Now supports both Quick Mode (for fast onboarding) and Deep Mode (for detailed customization).
---

# OpenClaw AGENTS Builder: 岗位说明书定制向导 (v2.0)

This skill guides you through a structured interview process with the user to collect the necessary information for generating a highly personalized `AGENTS.md` file for their OpenClaw AI agent.

## Core Philosophy

As detailed in the OpenClaw documentation, `AGENTS.md` defines the specific workflows, constraints, and the crucial "Traffic Light Permission System" (红绿灯权限系统) for the digital employee.

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
请告诉我您的职业角色，以及您最担心 AI 犯什么错？
（例如：'我是销售总监，最怕它乱发报价单或删除客户资料'）"

*(Wait for user response. Then use your AI reasoning to automatically deduce the General Workflow and the Traffic Light System (Green/Yellow/Red) based on this single input. Proceed directly to Step 4: Draft Generation.)*

---

### PATH B: Deep Mode (详细模式)

#### Deep Step 1: General Workflow (日常工作流)
**Message to send:**
"您选择了【详细模式】。
第一步，我们来梳理它的**日常工作流（General Workflow）**。
您希望龙虾每天帮您处理哪些具体的业务？（例如：'每天早上帮我整理昨天的会议纪要，并根据我的指示起草邮件回复'）"
*(Wait for user response, validate, then proceed to Deep Step 2)*

#### Deep Step 2: Green & Yellow Lights (绿灯与黄灯)
**Message to send:**
"第二步，设定**绿灯与黄灯权限**。
- 🟢 **绿灯（自己干）**：哪些事它可以不问您，直接自己做决定？（如：搜资料、读文档）
- 🟡 **黄灯（先斩后奏）**：哪些事它可以做，但做完必须告诉您一声？（如：存文件、打标签）"
*(Wait for user response, validate, then proceed to Deep Step 3)*

#### Deep Step 3: Red Light (红灯禁区)
**Message to send:**
"第三步，设定**红灯禁区（Red Light）**。
🔴 **红灯（绝对禁区）**：哪些事（比如发邮件、删文件、动资金）它哪怕天塌下来也必须先请示您？"
*(Wait for user response, validate, then proceed to Step 4)*

---

### Step 4: Draft Generation and Review (Common for both paths)

**Action:** Synthesize the collected information into a draft `AGENTS.md` file.

**Format Rules for Draft:**
- Use clear Markdown headings (`## General Workflow`, `## Traffic Light System`, `## Memory Rules`).
- The Traffic Light System MUST clearly list the three tiers: `Freely Execute`, `Execute & Notify`, `Ask First`.

**Message to send:**
"信息收集完毕！这是为您定制的 `AGENTS.md`（岗位说明书）草稿，请您过目：

```markdown
(Insert generated AGENTS.md draft here)
```

**老板，您看看这份岗位说明书够不够严谨？有没有需要调整或补充的条款？**"

### Step 5: Finalization
Once the user approves the draft, use the `file` tool to save the final content to a file named `AGENTS.md` in the current working directory, and provide the user with instructions on where to place it in their OpenClaw workspace.
