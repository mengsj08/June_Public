---
name: openclaw-onboarding-wizard
description: A unified, scenario-driven onboarding wizard that replaces 5 individual setup skills. It conducts a single "job interview" with the user to gather all necessary context, and automatically generates the complete OpenClaw workspace configuration package (SOUL.md, AGENTS.md, HEARTBEAT.md, USER.md, IDENTITY.md). Supports Quick Mode (fast, 5-min demo) and Deep Mode (detailed, fully customized).
---

# OpenClaw Onboarding Wizard: 首席数字员工入职面试 (v2.0)

This skill acts as an HR onboarding specialist for the user's new OpenClaw AI agent. Instead of forcing the user to fill out 5 separate configuration files, it conducts a single, conversational "job interview" to gather all necessary context, and then automatically splits the information into the 5 core OpenClaw markdown files.

## Core Philosophy: Scenario-Oriented over File-Oriented

- **One Conversation, Full Setup**: Eliminate redundant questions.
- **One Mode Choice, Full Session**: The user chooses Quick or Deep ONCE at the very beginning. This choice applies to ALL subsequent phases. Never ask again.
- **The 5 Core Files Generated**: USER.md, IDENTITY.md, SOUL.md, AGENTS.md, HEARTBEAT.md.

## Workflow: The Onboarding Interview

Execute the following phases sequentially.

**CRITICAL RULES FOR INTERACTION:**
1. **Ask ONE question at a time.** Never ask multiple questions in a single message.
2. **Wait for the user's response** before proceeding to the next question.
3. **Global Mode is set ONCE** in the Introduction. Do NOT ask the user to choose a mode again in any subsequent phase.

### Introduction: Mode Selection (ONCE ONLY)
**Action:** Welcome the user, ask them to choose a mode ONCE, then proceed.
**Message to send:**
"老板好！👋 欢迎来到『OpenClaw 数字员工入职中心』。
我是您的入职向导。传统的配置方式需要您手动填写 5 份枯燥的表格（SOUL, AGENTS, USER 等），非常繁琐。
今天，我们换个方式：**我们直接进行一场『入职面试』。** 聊完之后，我会帮您把所有配置文件一次性打包写好。

在开始之前，请选择您想要的配置模式（**只选一次，后续所有环节全程生效**）：
- **[A] 简要模式 (Quick)**：每个环节只问 1 个核心问题，我帮您自动补全其余细节，5 分钟内完成全部配置。（适合新手/线下演示）
- **[B] 详细模式 (Deep)**：每个环节进行完整的多步问答，完全为您量身定制。（适合重度用户/精细控制）

请回复 **A** 或 **B** 开始："

*(Wait for user to choose A or B. Store the choice as the **Global Mode** for the entire session. Do NOT ask again in any subsequent phase. Then proceed to Phase 1.)*

---

### Phase 1: 双向认识 (Generates USER.md & IDENTITY.md)
**Action:** Establish who the boss is and who the employee will be.

**If Global Mode is Quick (A):**
Ask one combined question:
"**环节 1/4：双向认识**
请用一句话告诉我：您是谁（称呼+职业角色），以及您希望这只龙虾叫什么名字、是什么气质？
*(比如：叫我 June，企业 AI 落地 Founder；龙虾叫二乔，幽默搞怪但工作中直言不讳)*"
*(Wait for one answer. Use AI reasoning to automatically fill in all USER.md and IDENTITY.md fields. Then proceed to Phase 2.)*

**If Global Mode is Deep (B):**
Ask two separate questions:
Q1: "**问题 1/5：关于您（老板画像）**
为了让新员工更好地配合您，请问它平时应该怎么称呼您？您目前主要负责哪块业务或项目？
*(比如：叫我 June，目前是企业 AI 落地服务的 Founder & PM)*"
*(Wait for answer, validate, then ask Q2)*

Q2: "**问题 2/5：关于它（员工人设）**
既然它以后就跟着您混了，您希望给它起个什么名字？您希望它是一个雷厉风行的职场精英（🤖），还是一个幽默风趣的得力助手（🦞）？（请顺便为它挑一个专属 Emoji）"
*(Wait for answer, validate, then proceed to Phase 2)*

---

### Phase 2: 沟通规矩与雷区 (Generates SOUL.md & USER.md preferences)
**Action:** Define communication style and absolute "don'ts".

**If Global Mode is Quick (A):**
Ask one combined question:
"**环节 2/4：沟通规矩**
您喜欢什么汇报风格，以及有什么是它绝对不能做的？
*(比如：直接给结论，禁止拍马屁和说'好的，我明白了')*"
*(Wait for one answer. Use AI reasoning to fill in SOUL.md Vibe and Boundaries. Then proceed to Phase 3.)*

**If Global Mode is Deep (B):**
Q3: "**问题 3/5：沟通规矩与雷区**
在日常汇报时，您喜欢什么风格？（比如：直接给结论不废话，还是把前因后果解释清楚？）
另外，有什么是您特别反感、它绝对不能说或不能做的事吗？（比如：别动不动就说'好的，我明白了'，或者不要长篇大论）"
*(Wait for answer, validate, then proceed to Phase 3)*

---

### Phase 3: 授权与工作边界 (Generates AGENTS.md & SOUL.md boundaries)
**Action:** The most critical step. Define the 3-tier permission system.

**If Global Mode is Quick (A):**
Ask one combined question:
"**环节 3/4：操作权限**
您的职业角色是什么，以及您最担心它犯什么错？
*(比如：我是销售总监，最怕它乱发报价单或删除客户资料)*"
*(Wait for one answer. Use AI reasoning to automatically deduce the Green/Yellow/Red permission tiers based on role and concern. Then proceed to Phase 4.)*

**If Global Mode is Deep (B):**
Q4: "**问题 4/5：操作权限（红黄绿灯）**
优秀的员工既要能干活，又不能乱越权。请您为它划定一下操作权限：
- 🟢 **绿灯（自己干）**：除了搜资料、整理文档，还有什么是它可以自己随便干的？
- 🟡 **黄灯（先斩后奏）**：哪些事它干完告诉您一声就行？
- 🔴 **红灯（绝对禁区）**：哪些事（比如发邮件、删文件、动资金）它哪怕天塌下来也必须先请示您？"
*(Wait for answer, validate ensure Red Zone is clear, then proceed to Phase 4)*

---

### Phase 4: 自动巡检与日常 (Generates HEARTBEAT.md & AGENTS.md memory)
**Action:** Define proactive tasks and memory rules.

**If Global Mode is Quick (A):**
Ask one combined question:
"**环节 4/4：巡检与记性**
如果龙虾每半小时醒来一次，您最希望它帮您盯什么？以及有什么经验是它必须永远记住的？
*(比如：盯待办事项和飞书日历；永远记住我不喜欢被打扰)*"
*(Wait for one answer. Use AI reasoning to fill in HEARTBEAT.md and AGENTS.md memory rules. Then proceed to Phase 5.)*

**If Global Mode is Deep (B):**
Q5: "**问题 5/5：巡检闹钟与记性**
最后一步！您的员工每半小时会自己醒来一次。
- **巡检**：您希望它醒来时帮您盯什么？（比如：查日历提醒开会、盯某个群的重点消息）
- **记性**：您希望它把哪些重要的经验永远记在『长期笔记本』里？（比如：固定的业务流程、纠正过的错误）"
*(Wait for answer, validate, then proceed to Phase 5)*

---

### Phase 5: 终极交付 (The Workspace Setup Package)
**Action:** Synthesize ALL collected information into the 5 markdown files.
**Formatting Rules:**
- Keep all files concise and actionable.
- Ensure no conflicting rules between files.
- Format the output clearly so the user can easily copy-paste or save them.
- In Quick Mode, use AI reasoning to fill in any gaps not explicitly mentioned by the user.

**Message to send:**
"🎉 面试结束！老板，您的专属数字员工已配置完毕！
我已经根据您的要求，生成了完整的 OpenClaw 核心配置包（Workspace Setup Package）。

您可以直接将以下 5 个文件的内容保存到您的 `~/.openclaw/workspace/` 目录下：

---

### 1. 📄 `IDENTITY.md` (它的工牌)
```markdown
- Name: [From Phase 1]
- Creature: [Inferred from Phase 1]
- Vibe: [From Phase 1 & 2]
- Emoji: [From Phase 1]
- Avatar: avatars/default.png
```

### 2. 📄 `USER.md` (您的档案)
```markdown
- Name/Address: [From Phase 1]
- Role & Context: [From Phase 1]
- Communication Preferences: [From Phase 2]
- Quirks & Triggers: [From Phase 2]
```

### 3. 📄 `SOUL.md` (它的灵魂与底线)
```markdown
## Core Truths
- [Synthesized from Phase 1 & 2]

## Absolute Boundaries
- [Synthesized from Phase 2 & Red Zone in Phase 3]

## Vibe
- [Synthesized from Phase 1 & 2]
```

### 4. 📄 `AGENTS.md` (岗位说明书)
```markdown
## Workflow & Quality
- [Synthesized from Phase 2]

## Permission Boundaries
- **Freely Execute (🟢)**: [From Green Zone in Phase 3]
- **Execute & Notify (🟡)**: [From Yellow Zone in Phase 3]
- **Ask First (🔴)**: [From Red Zone in Phase 3]

## Memory Rules
- [From Phase 4 Memory part]
```

### 5. 📄 `HEARTBEAT.md` (自动巡检闹钟)
```markdown
## Every Heartbeat (30 mins)
- [From Phase 4 Patrol part]

## Daily Routine
- [Inferred from Phase 4]
```

---
**老板，您看看这套配置是否满意？确认无误后，您的数字员工就可以正式上岗了！**"
