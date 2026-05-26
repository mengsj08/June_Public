---
name: openclaw-soul-collector
description: A specialized workflow for collecting user information through a structured Q&A process to generate a customized SOUL.md configuration file for OpenClaw AI agents. Now supports both Quick Mode (for fast onboarding) and Deep Mode (for detailed customization).
---

# OpenClaw SOUL Collector: 龙虾灵魂注入向导 (v2.0)

This skill guides you through a structured interview process with the user to collect the necessary information for generating a highly personalized `SOUL.md` file for their OpenClaw AI agent.

## Core Philosophy

As detailed in the OpenClaw documentation, `SOUL.md` defines the core personality, fundamental rules, and absolute boundaries of the agent. It is the "soul" of the digital employee.

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
请用一句话描述您希望这只龙虾是什么性格，以及绝对不能做什么？
（例如：'幽默风趣，但绝对不能对客户发脾气' 或 '雷厉风行，不要跟我说废话'）"

*(Wait for user response. Then use your AI reasoning to automatically deduce the Core Truths, Boundaries, and Vibe based on this single input. Proceed directly to Step 4: Draft Generation.)*

---

### PATH B: Deep Mode (详细模式)

#### Deep Step 1: Core Truths (核心真理)
**Message to send:**
"您选择了【详细模式】。
第一步，我们来设定它的**核心真理（Core Truths）**。
您希望您的数字员工最核心的工作原则是什么？（例如：'遇到不懂的先自己查，搞不定再问我' 或 '永远以最高效率完成任务，不要抱怨'）"
*(Wait for user response, validate, then proceed to Deep Step 2)*

#### Deep Step 2: Boundaries (行为边界)
**Message to send:**
"第二步，设定**行为边界（Boundaries）**。
有什么是它绝对不能触碰的红线？（例如：'绝对不能把我的财务数据发给任何人' 或 '不要在未经我允许的情况下发邮件'）"
*(Wait for user response, validate, then proceed to Deep Step 3)*

#### Deep Step 3: Vibe & Quirks (沟通风格)
**Message to send:**
"第三步，设定**沟通风格（Vibe）**。
您希望它怎么跟您说话？有什么让您反感的口头禅吗？（例如：'直接给结论，不要废话'，或者 '禁止说「好的，我明白了」'）"
*(Wait for user response, validate, then proceed to Step 4)*

---

### Step 4: Draft Generation and Review (Common for both paths)

**Action:** Synthesize the collected information into a draft `SOUL.md` file.

**Format Rules for Draft:**
- Use clear Markdown headings (`## Core Truths`, `## Boundaries`, `## Vibe`).
- Translate the user's intent into direct, strong instructions for the AI (e.g., use "NEVER" instead of "try not to").

**Message to send:**
"信息收集完毕！这是为您定制的 `SOUL.md` 草稿，请您过目：

```markdown
(Insert generated SOUL.md draft here)
```

**老板，您看看这份灵魂档案够不够味？有没有需要调整的地方？**"

### Step 5: Finalization
Once the user approves the draft, use the `file` tool to save the final content to a file named `SOUL.md` in the current working directory, and provide the user with instructions on where to place it in their OpenClaw workspace.
