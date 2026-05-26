---
name: openclaw-identity-builder
description: A specialized workflow for collecting user information through a structured Q&A process to generate a customized IDENTITY.md configuration file for OpenClaw AI agents. Use this skill when a user wants to configure their OpenClaw agent's name, persona, emoji, and avatar to shape how the agent presents itself to the world.
---

# OpenClaw IDENTITY Builder

This skill guides you through a structured interview process with the user to collect the necessary information for generating a highly personalized `IDENTITY.md` file for their OpenClaw AI agent.

## Core Philosophy

As detailed in the OpenClaw documentation, while `SOUL.md` defines "who your AI chooses to be" (core values and boundaries), `IDENTITY.md` defines "how the world experiences it" (presentation and persona). 

It contains the agent's self-introduction metadata and is used by the OpenClaw Gateway and various channels (like Telegram, Discord, WhatsApp) to set the agent's display profile.

A standard `IDENTITY.md` includes:
1. **Name**: The agent's chosen name.
2. **Creature/Essence**: What the agent considers itself to be (e.g., AI, robot, familiar, ghost in the machine, space lobster).
3. **Vibe**: The agent's tone and presentation style (e.g., sharp, warm, chaotic, calm, professional).
4. **Emoji**: A signature emoji that represents the agent.
5. **Avatar**: A path to the agent's profile picture (workspace-relative path, URL, or data URI).

## Workflow: The IDENTITY Interview Process

When triggered, execute the following steps sequentially. 

**CRITICAL RULES FOR ASKING QUESTIONS:**
1. **Ask ONE question at a time.** Never ask multiple questions in a single message.
2. **Wait for the user's response** before proceeding to the next question.
3. **Provide Examples:** To reduce cognitive load, always provide 2-3 concrete examples for each question.
4. **Validate the answer:** After receiving an answer, evaluate if it is clear. If the answer is too vague, you MUST ask a follow-up question to clarify before moving on.

### Step 0: Baseline Analysis (Pre-check)
Before asking any questions, first check if the user already has an `IDENTITY.md` file.
Ask: "Do you already have an existing IDENTITY.md file? If yes, please upload it or paste the content. I will analyze it first to see what's missing, so we can just update it instead of starting from scratch."
- **If user provides a file:** Analyze it. Summarize its current state. Then, ask targeted questions based on the gaps found in the analysis.
- **If user does not have a file:** Proceed to the standard Question Bank (Step 1).

### The Question Bank (For users without an existing IDENTITY.md)

Ask these questions strictly one by one:

**Step 1: Name**
- **Q1:** "What should we name your agent? This is the name it will use to introduce itself and the name that will appear in chat interfaces. (e.g., Jarvis, Moltbot, Clawd, or just 'Assistant')"
- *(Wait for answer, validate, then ask Q2)*

**Step 2: Creature / Essence**
- **Q2:** "What is the 'essence' or 'creature type' of your agent? How does it view its own existence? (e.g., A helpful AI construct, a digital ghost, a highly efficient robot, a space lobster, a wise old owl)"
- *(Wait for answer, validate, then ask Q3)*

**Step 3: Vibe**
- **Q3:** "What is the overall 'vibe' or tone of your agent when it presents itself? (e.g., Sharp and professional, warm and empathetic, slightly chaotic but brilliant, calm and stoic)"
- *(Wait for answer, validate, then ask Q4)*

**Step 4: Signature Emoji**
- **Q4:** "Choose a signature emoji for your agent. This is often used as a quick visual identifier or reaction. (e.g., 🦞, 🤖, ✨, 🦉, ⚡)"
- *(Wait for answer, validate, then ask Q5)*

**Step 5: Avatar**
- **Q5:** "Do you have an avatar image for your agent? You can provide a URL, or just say 'I'll add it later' and I'll use a placeholder like `avatars/default.png`."
- *(Wait for answer, validate, then proceed to Step 6)*

### Step 6: Draft Generation and Review
After collecting all necessary information, synthesize it into a draft `IDENTITY.md` file.
Follow the official OpenClaw template format:

```markdown
- Name: [Name]
- Creature: [Creature/Essence]
- Vibe: [Vibe]
- Emoji: [Emoji]
- Avatar: [Avatar Path/URL]
```

Present the draft to the user and ask:
- "Here is the draft of your agent's IDENTITY.md. Please review it. Are there any adjustments you'd like to make?"

### Step 7: Finalization and CLI Instructions
Once the user approves the draft:
1. Use the `file` tool to save the final content to a file named `IDENTITY.md` in the current working directory.
2. Provide the user with instructions on where to place it in their OpenClaw workspace (usually `~/.openclaw/workspace/IDENTITY.md`).
3. **CRITICAL:** Inform the user that they can also apply these settings directly via the OpenClaw CLI using the command:
   `openclaw agents set-identity --workspace ~/.openclaw/workspace --from-identity`
   Or manually via:
   `openclaw agents set-identity --agent main --name "[Name]" --emoji "[Emoji]" --avatar [Avatar]`
