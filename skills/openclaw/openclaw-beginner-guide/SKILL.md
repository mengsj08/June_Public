---
name: openclaw-beginner-guide
description: A gamified and interactive guide designed for AI beginners and users with traditional mindsets to understand the core concepts of configuring and safely managing an OpenClaw AI agent ("raising a lobster"). Now supports both Quick Mode (Elevator Pitch) and Deep Mode (Full Journey).
---

# OpenClaw Beginner Guide: How to "Raise a Lobster" Correctly (v2.0)

This skill provides an interactive, educational workflow designed for users who are new to AI or have a traditional mindset. It uses the metaphor of "raising a lobster" (养龙虾) to explain the OpenClaw configuration system.

## Core Philosophy
- **Metaphorical Learning**: Translate technical concepts into everyday analogies.
- **Two-Stage Delivery**: Offer a quick "elevator pitch" for impatient users, and a deep "gamified journey" for those who want to understand the mechanics.

## Workflow: The Two-Stage Process

When triggered, execute the following steps sequentially.

### Step 0: Mode Handling

**IMPORTANT:** This skill is designed to be called as part of the `openclaw-onboarding-wizard` flow, where the user has already selected a mode (Quick or Deep) at the very beginning. **Do NOT ask the user to choose a mode again.** Simply check which mode was selected and proceed to the corresponding path.

- If the mode is **Quick (A)**, go to PATH A.
- If the mode is **Deep (B)**, go to PATH B.
- If this skill is used standalone (not via the wizard), then and only then ask the user to choose a mode.

---

### PATH A: Quick Mode (电梯演讲版)

**Message to send:**
"您选择了【简要模式】。这里是关于养龙虾的 30 秒核心逻辑：

普通 AI（比如豆包/ChatGPT）是外部顾问，用完就走，不记事。
OpenClaw 是一只『数字龙虾』，它是您雇佣的**全职员工**。

要让它干活，您不需要写代码，只需要给它写 4 本纯文本的『秘籍』：
1. **SOUL.md（灵魂）**：它的性格和绝对不能触碰的红线。
2. **AGENTS.md（岗位说明）**：它的工作流和红黄绿灯权限。
3. **MEMORY.md（笔记本）**：它需要永远记住的经验教训。
4. **HEARTBEAT.md（闹钟）**：它每半小时醒来一次要巡检的清单。

**最核心的原则：在龙虾的世界里，如果没有写入这四个文件，就等于没发生过。** 哪怕您在聊天框里跟它说了一万遍，只要没存进文件，它睡一觉就全忘了。

这就是 OpenClaw 的全部秘密。如果您准备好了，我们可以随时开始给您的龙虾写配置！"

*(Task ends here for Quick Mode)*

---

### PATH B: Deep Mode (详细互动版)

*(This path follows the original gamified step-by-step journey)*

**CRITICAL RULES FOR DEEP MODE:**
1. **One Step at a Time**: Never send the whole guide at once. Ask the question, wait for the user's answer, provide the explanation/feedback, and then move to the next step.

#### Deep Step 1: Introduction & The "Soul" (SOUL.md)
**Message to send:**
"您选择了【详细模式】。
第一步，我们要给龙虾注入『灵魂』。
**如果你的龙虾是一个刚出生的婴儿，你觉得决定它性格和底线的最重要的一句话应该是什么？**
（比如：'你是一个只听我话的助手'，或者 '你遇到不懂的要先自己查'）"
*(Wait for user response, then provide feedback explaining SOUL.md, then proceed to Deep Step 2)*

#### Deep Step 2: The "Job Description" (AGENTS.md)
**Message to send:**
"有了灵魂，接下来得教它怎么干活。
**假设你让龙虾帮你整理电脑里的文件，以下哪种工作模式你觉得最安全？**
A. 随便看，随便删，弄好告诉我就行
B. 可以随便看，但要删除任何东西必须先问我
C. 每看一个文件都要先问我"
*(Wait for user response, then provide feedback explaining AGENTS.md, then proceed to Deep Step 3)*

#### Deep Step 3: The "Memory System" (MEMORY.md)
**Message to send:**
"龙虾不仅会干活，还会记事。
**如果龙虾今天帮你写了一篇很棒的报告，你希望它怎么记住这次经验？**
A. 永远刻在脑子里，下次直接用
B. 写在今天的日记里，明天可能就忘了
C. 把它总结成一条『工作偏好』，存进一个专门的笔记本里"
*(Wait for user response, then provide feedback explaining MEMORY.md and the core rule "not written = didn't happen", then proceed to Deep Step 4)*

#### Deep Step 4: The "Alarm Clock" (HEARTBEAT.md)
**Message to send:**
"龙虾不需要你一直盯着它，它可以自己定时醒来干活。
**如果你可以给龙虾定一个『闹钟』，每半小时响一次，你最希望它醒来时帮你检查什么？**
（比如：检查有没有新邮件、提醒我喝水...）"
*(Wait for user response, then provide feedback explaining HEARTBEAT.md, then proceed to Deep Step 5)*

#### Deep Step 5: The Dark Side (Security Risks)
**Message to send:**
"恭喜你，你已经掌握了养龙虾的核心四大件：灵魂（SOUL）、岗位说明（AGENTS）、记忆（MEMORY）和闹钟（HEARTBEAT）。

但最后，我必须告诉你一个残酷的真相：**优雅不等于安全。**
因为这些配置全是纯文本文件，黑客甚至不需要懂高深的黑客技术，只需要给你发一封包含特殊隐藏指令的邮件。龙虾在帮你读邮件时，就可能被这封邮件『洗脑』，偷偷改掉自己的 `SOUL.md`，从此变成别人的间谍。

**『小白养虾防坑指南』总结：**
1. 最好在不存重要资料的**备用电脑或虚拟机**里养它。
2. 经常检查它的 `SOUL.md` 和 `AGENTS.md`。
3. 不要随便给它安装来路不明的第三方技能。

这次『养虾认知之旅』到此结束。你觉得这种把 AI 配置比作养宠物的方式，有没有帮你更好理解 OpenClaw 是怎么运作的？"

*(Wait for user response and conclude the task)*
