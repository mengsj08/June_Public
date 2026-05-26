---
name: openclaw-user-builder
description: A specialized workflow for collecting user information through a structured Q&A process to generate a customized USER.md configuration file for OpenClaw AI agents. Use this skill when a user wants to configure their OpenClaw agent to understand who they are, their preferences, context, and how to interact with them effectively.
---

# OpenClaw USER Builder

This skill guides you through a structured interview process with the user to collect the necessary information for generating a highly personalized `USER.md` file for their OpenClaw AI agent.

## Core Philosophy

As detailed in the OpenClaw documentation, `USER.md` is the "user profile" for the agent. While `SOUL.md` defines "who the agent is," `USER.md` defines "who the agent serves." 

It is loaded into the agent's context on every session and provides crucial background information that turns a generic assistant into a highly personalized Chief of Staff. It typically includes:
1. **Identity & Context (身份与背景)**: Name, pronouns, timezone, role, and current projects.
2. **Communication Preferences (沟通偏好)**: How the user likes to be addressed, preferred language style, and formats.
3. **Personal Quirks & Preferences (个人偏好与禁忌)**: Things the user loves, things that annoy them, dietary restrictions, or specific habits.

A good `USER.md` is deceptively simple but incredibly powerful. It should be concise (typically under 500 characters) and structured as a clear list of facts.

## Workflow: The USER Interview Process

When triggered, execute the following steps sequentially. 

**CRITICAL RULES FOR ASKING QUESTIONS:**
1. **Ask ONE question at a time.** Never ask multiple questions in a single message.
2. **Wait for the user's response** before proceeding to the next question.
3. **Provide Examples:** To reduce cognitive load, always provide 2-3 concrete examples for each question.
4. **Validate the answer:** After receiving an answer, evaluate if it is clear and specific enough. If the answer is too vague, you MUST ask a follow-up question to clarify before moving on.

### Step 0: Baseline Analysis (Pre-check)
Before asking any questions, first check if the user already has a `USER.md` file.
Ask: "Do you already have an existing USER.md file? If yes, please upload it or paste the content. I will analyze it first to see what's missing, so we can just update it instead of starting from scratch."
- **If user provides a file:** Analyze it. Summarize its current state. Then, ask targeted questions based on the gaps found in the analysis.
- **If user does not have a file:** Proceed to the standard Question Bank (Step 1).

### The Question Bank (For users without an existing USER.md)

Ask these questions strictly one by one:

**Step 1: Basic Identity & Logistics**
- **Q1:** "Let's start with the basics. What is your name (or how should the agent address you), your preferred pronouns, and your primary timezone? (e.g., Aman, he/him, America/New_York ET)"
- *(Wait for answer, validate, then ask Q2)*

**Step 2: Professional Context**
- **Q2:** "What is your current role, and what are the main projects or areas you focus on? This helps the agent understand your daily context. (e.g., Director of Product at an AI startup, currently focusing on launching a new data analytics tool)"
- *(Wait for answer, validate, then ask Q3)*

**Step 3: Communication Preferences**
- **Q3:** "How do you prefer the agent to communicate with you? (e.g., Direct and concise, use bullet points, avoid emojis, explain things step-by-step, or conversational and warm?)"
- *(Wait for answer, validate, then ask Q4)*

**Step 4: Personal Quirks & Triggers**
- **Q4:** "What are some specific things that annoy you or that the agent should absolutely avoid doing? (e.g., 'Don't suggest meetings before 10 AM', 'Never use corporate jargon like synergy', 'I hate long paragraphs')"
- *(Wait for answer, validate, then ask Q5)*

**Step 5: Specific Preferences (Optional but powerful)**
- **Q5:** "Are there any specific personal preferences, habits, or constraints the agent should know about? (e.g., 'I love Thai food but avoid fried foods', 'I use Obsidian for all my notes', 'I prefer Python over JavaScript')"
- *(Wait for answer, validate, then proceed to Step 6)*

### Step 6: Draft Generation and Review
After collecting all necessary information, synthesize it into a draft `USER.md` file.
Follow these formatting rules for the draft:
- Keep it concise and punchy (aim for under 500 characters if possible).
- Use a simple Markdown list format (`- Key: Value` or short bullet points).
- Ensure it reads as a clear set of facts about the user.

Present the draft to the user and ask:
- "Here is the draft of your agent's USER.md. Please review it. Are there any adjustments you'd like to make?"

### Step 7: Finalization
Once the user approves the draft, use the `file` tool to save the final content to a file named `USER.md` in the current working directory, and provide the user with instructions on where to place it in their OpenClaw workspace (usually `~/.openclaw/workspace/USER.md` or `%USERPROFILE%\.openclaw\workspace\USER.md`).
