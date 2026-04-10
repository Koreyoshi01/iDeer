---
name: idea-from-daily
description: "Bridge daily recommender ideas to research pipelines. Read history/ideas/{date}/ideas.json OR generate ideas yourself from today's scored items, then route to /idea-creator, /idea-discovery, or /research-pipeline. Use when user says '/idea-from-daily', '从今日推荐启动研究', 'pick idea from daily'."
argument-hint: "[date] [--idea N]"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, Skill
---

# Idea-from-Daily: Bridge Daily Digest → Auto-Research

Read saved ideas or generate them yourself from daily scored items, then launch a research pipeline.

## Constants

- **PROJECT_DIR** = `~/Documents/daily-recommender`
- **IDEAS_DIR** = `$PROJECT_DIR/history/ideas`
- **HISTORY_DIR** = `$PROJECT_DIR/history`

## Arguments

Parse from `$ARGUMENTS`:
- **date** (optional): e.g. `2026-04-10`. Default: today.
- **--idea N** (optional): Select idea N directly. If omitted, show list.

## Workflow

### Step 1: Find ideas

Try to load `$IDEAS_DIR/{date}/ideas.json`.

If not found, check if scored items exist in `$HISTORY_DIR/*/date/json/`. If they do, YOU generate 3-5 ideas by reading the scored items and the researcher profile — same as Phase 7 of `/ideer-daily-paper`. Save with:

```bash
cd $PROJECT_DIR
echo '$IDEAS_JSON' | python agent_bridge.py save-ideas --date {date}
```

If neither ideas nor scored items exist, tell the user and list available dates:
```bash
ls $IDEAS_DIR/
```

### Step 2: Display ideas

Show a numbered table:

```
| #  | Title          | Score | Area       | Project         | Direction (EN)                    |
|----|----------------|-------|------------|-----------------|-----------------------------------|
| 1  | 中文标题        | 8.5   | Safety     | AgentDoG        | One-line English direction...     |
| 2  | ...            | ...   | ...        | ...             | ...                               |
```

### Step 3: Select

If `--idea N` was given, use it. Otherwise ask the user.

### Step 4: Build research direction

From the selected idea, construct:

```
DIRECTION = "{research_direction}. Hypothesis: {hypothesis_en}. Inspired by: {title1} ({url1}), {title2} ({url2})"
```

Show the direction and ask for confirmation.

### Step 5: Choose pipeline

Ask the user:

1. **Quick** → `/idea-creator "$DIRECTION"` — Brainstorm and rank
2. **Full** → `/idea-discovery "$DIRECTION"` — Survey → brainstorm → novelty check → review
3. **End-to-end** → `/research-pipeline "$DIRECTION"` — All the way to paper

Default: Full (`/idea-discovery`).

### Step 6: Launch

Invoke the chosen skill with the constructed direction string.
