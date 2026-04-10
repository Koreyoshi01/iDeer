---
name: hot-first-research-digest
description: "Use when the user wants a hot-first but relevance-aware daily AI research digest that combines platform hot papers, direction-strong picks, X latest/hot dynamics, and GitHub/HuggingFace resource trends, then ends with synthesis and idea candidates."
argument-hint: "[auto|custom] [--email] [--ideas]"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, WebSearch, WebFetch, Agent, AskUserQuestion
---

# Hot-First Research Digest

Adapt the existing iDeer daily-paper workflow into a hot-first, relevance-aware digest.

## Core Principle

Build the candidate pool from what is hot first, then rerank and rewrite based on the reader's research directions.

## Inputs

- `profiles/description.txt`
- `profiles/researcher_profile.md`
- `history/*/{date}/json/*.json`
- Hot-paper or hot-resource sources already supported by the repo

## Output Structure

Always produce the digest in this order:

1. `今日总览`
2. `平台热榜论文`
3. `强相关方向精选`
4. `X 最新 / 热门动态`
5. `GitHub / HuggingFace / 资源趋势`
6. `最后总结`
7. `ideas + initial plans` when requested

## Candidate Pool Policy

Use four candidate buckets:

- `platform_hot_papers`
  - HuggingFace Daily Papers / hot-paper style sources
  - alphaXiv hot/likes when available
- `direction_strong`
  - arXiv / Semantic Scholar / hot-paper items strongly aligned to the profile
- `x_latest_hot`
  - paper shares
  - blog / explainer threads
  - AI news
  - tool demos
  - release posts
- `resource_trends`
  - GitHub trending repos
  - HuggingFace models
  - practical research resources

## Daily / Weekly Policy

- Treat `HuggingFace daily` as a high-priority hot-paper source.
- Treat `HuggingFace weekly` and `alphaXiv 7-day hot` as rolling weekly sources.
- For weekly sources:
  - keep JSON incrementally
  - skip already-existing paper JSON
  - summarize only the newly added items for the new weekly snapshot
  - do not regenerate a full repeated weekly narrative unless explicitly requested

## arXiv Policy

- arXiv is broader and noisier than HuggingFace daily.
- Use arXiv as a direction-first supplement rather than a pure hot-paper source.
- Favor relevant categories and strong profile alignment over raw volume.
- If the candidate pool is large, spend more explanation budget on the highest-quality and highest-relevance items.

## Ranking Policy

Within the final digest:

- Preserve globally hot items even if only weakly related
- Preserve strongly related items even if they are not the most viral
- Prefer fewer, denser, more interpretable items over long low-signal lists
- In cross-source synthesis, deduplicate overlapping papers across alphaXiv, HuggingFace, arXiv, and other paper sources

## Summary Policy

Use `method-first-summary` for every important paper, repo, model, or thread.

If an upstream source already provides a summary:

- keep it only if it already explains the problem and method clearly
- otherwise rewrite it from the original content into the required format

## X Policy

Do not treat X as a simple timeline dump.

Cluster X items into:

- `paper-share`
- `blog-thread`
- `ai-news`
- `tool-demo`
- `release`
- `discussion`

Prefer information-dense items that reveal methods, system changes, engineering practices, or major news.

## Final Synthesis

After the four sections, write a synthesis that:

- connects the sections into a coherent narrative
- highlights transferable ideas from global hot items into the reader's core directions
- explicitly marks what deserves follow-up tomorrow

The synthesis should behave like a trimmed brainstorming pass:

- connect seemingly separate items
- compare at least two possible readings when ambiguity exists
- explicitly prefer the more actionable interpretation
- surface one or two research bottlenecks that the digest repeatedly points to

## Idea Handoff

When idea generation is requested:

- call `idea-plan-from-digest`
- prefer 1-3 high-quality ideas
- only go beyond 3 when there are clearly multiple strong, evidence-backed directions
- if the idea quality is uncertain, run a lightweight external critique or self-review before finalizing
