---
name: ideer-daily-paper
description: "Daily paper/repo digest where YOU are the reader. Fetch items from arXiv/HuggingFace/GitHub/Semantic Scholar, then read, score, summarize, and generate ideas yourself — no external LLM API calls. Use when user says '今日论文', 'daily paper', 'daily digest', '每日推荐', or wants a personalized research briefing."
argument-hint: "[sources: arxiv huggingface github semanticscholar] [--email] [--ideas]"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, WebSearch, WebFetch, Agent
---

# iDeer Daily Paper Skill — Agent-as-Reader

You ARE the LLM. You read papers, score them, write summaries, generate ideas. No external API calls for evaluation.

## Constants

- **PROJECT_DIR** = `~/Documents/daily-recommender`
- **BRIDGE** = `python agent_bridge.py` (run from PROJECT_DIR)
- **DEFAULT_SOURCES** = `arxiv huggingface`
- **MAX_ITEMS_PER_SOURCE** = 30
- **TOP_N_TO_REPORT** = 10 per source

## Workflow

### Phase 1: Load researcher profile

```bash
cat $PROJECT_DIR/profiles/description.txt
cat $PROJECT_DIR/profiles/researcher_profile.md
```

Read both files. Internalize the researcher's interests, active projects, and target venues. This is YOUR scoring criteria.

### Phase 2: Fetch raw items

For each requested source, run the bridge fetcher:

```bash
cd $PROJECT_DIR
python agent_bridge.py fetch arxiv --categories cs.AI cs.CL cs.LG --max 50
python agent_bridge.py fetch huggingface --content_type papers --max 30
python agent_bridge.py fetch github --max 20
python agent_bridge.py fetch semanticscholar --queries "agent safety" "trustworthy AI" --max 30
```

Each command prints JSON to stdout. Save the output to a temp file or read it directly.

**Fallback**: If a fetcher fails (network error, rate limit), use `WebSearch` or `WebFetch` to manually gather items:
- arXiv: `WebFetch https://arxiv.org/list/cs.AI/recent`
- HuggingFace: `WebFetch https://huggingface.co/papers`
- GitHub: `WebFetch https://github.com/trending`

### Phase 3: Read and score (YOU are the LLM)

For each fetched item, YOU read the title and abstract/description, then assign:

```json
{
  "title": "original title",
  "score": 0-10,
  "summary": "your Chinese summary (2-3 sentences)",
  "url": "original URL",
  "highlights": ["highlight 1", "highlight 2"],
  "source": "arxiv/huggingface/github/semanticscholar"
}
```

**Scoring criteria** (based on the researcher profile you loaded):
- 9-10: Directly relevant to an active project, could change research direction
- 7-8: Highly relevant to declared interests, worth reading in full
- 5-6: Tangentially related, interesting but not urgent
- 3-4: Marginally related
- 0-2: Not relevant

**Efficiency**: You don't need to score every item individually. Scan all titles first, identify the clearly relevant ones (score ≥ 6), and only write detailed summaries for those. Skip items scoring below 5.

### Phase 4: Generate summary report

After scoring, compose a structured summary in Chinese covering:

1. **今日总览** — 2-3 sentence overview of today's highlights across all sources
2. **Per interest area** (Agent / Safety / Trustworthy) — top 2-4 items each, with:
   - Title + source badge
   - Score + engagement stats (stars, upvotes, etc.)
   - Why it matters to the researcher (1-2 sentences)
3. **补充观察** — Cross-source trends, surprising connections

Present this summary directly in the conversation.

### Phase 5: Save to history

Save the scored items:

```bash
cd $PROJECT_DIR
echo '$SCORED_ITEMS_JSON' | python agent_bridge.py save-items arxiv
echo '$SCORED_ITEMS_JSON' | python agent_bridge.py save-items huggingface
# etc. for each source
```

### Phase 6: Send email (if requested)

If user requested `--email` or it's a scheduled run:

1. Compose an HTML email body using the summary from Phase 4. Use simple, clean HTML — no need to match the exact template. Include:
   - Summary section at top
   - Item cards with title, score, summary, URL link
   - Footer with date

2. Save and send:
```bash
cd $PROJECT_DIR
echo '$EMAIL_HTML' | python agent_bridge.py send-email --subject "iDeer Daily $(date +%Y/%m/%d)"
```

### Phase 7: Generate research ideas (if requested)

If user requested `--ideas` or the profile has `GENERATE_IDEAS=1`:

1. Look at all items scored ≥ 7
2. Cross-reference with the researcher's active projects
3. Generate 3-5 research ideas, each with:

```json
{
  "title": "中文标题",
  "research_direction": "English one-liner for literature search",
  "hypothesis": "中文假设",
  "connects_to_project": "project name",
  "interest_area": "Agent/Safety/Trustworthy",
  "novelty_estimate": "HIGH/MEDIUM/LOW",
  "feasibility": "HIGH/MEDIUM/LOW",
  "composite_score": 8.5,
  "inspired_by": [{"title": "...", "source": "...", "url": "..."}]
}
```

4. Save:
```bash
cd $PROJECT_DIR
echo '$IDEAS_JSON' | python agent_bridge.py save-ideas
```

5. Present ideas in conversation.

## Scheduling (Claude Code / Codex)

For recurring daily runs, the user can set up:

**Claude Code scheduled trigger:**
```
/schedule daily at 08:00 Beijing: /ideer-daily-paper arxiv huggingface --email --ideas
```

**Codex automation prompt:**
```
Run /ideer-daily-paper with sources arxiv and huggingface.
Score papers against profiles/description.txt.
Save results and send email digest.
Generate 3 research ideas if any items score ≥ 7.
```

## Quick reference

| Action | Command |
|--------|---------|
| Fetch arXiv | `python agent_bridge.py fetch arxiv --categories cs.AI cs.CL --max 50` |
| Fetch HF papers | `python agent_bridge.py fetch huggingface --content_type papers --max 30` |
| Fetch GitHub | `python agent_bridge.py fetch github --max 20` |
| Fetch SS | `python agent_bridge.py fetch semanticscholar --queries "query" --max 30` |
| Save scored items | `echo JSON | python agent_bridge.py save-items SOURCE` |
| Save ideas | `echo JSON | python agent_bridge.py save-ideas` |
| Send email | `echo HTML | python agent_bridge.py send-email --subject "title"` |

## What NOT to do

- Do NOT run `main.py` — that calls external LLM APIs. You ARE the LLM.
- Do NOT call `scripts/run_daily.sh` — same reason.
- Do NOT skip reading the items. You must actually read titles/abstracts to score.
- Do NOT fabricate scores or summaries without reading the content.
