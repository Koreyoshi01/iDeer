---
name: method-first-summary
description: "Use when summarizing papers, repos, models, blog threads, or X posts and the user wants TLDR plus concrete method, pipeline, training recipe, novelty, and relevance instead of vague summaries."
argument-hint: "[paper|repo|model|thread|news]"
allowed-tools: Read, Write, Edit, Grep, WebSearch, WebFetch
---

# Method-First Summary

## Goal

Write summaries that are easy to grasp quickly but still leave a concrete technical impression.

## Required Shape

For important technical items, the summary should cover:

1. `一句话结论`
2. `它解决什么问题`
3. `方法核心`
4. `pipeline / training recipe / system workflow`
5. `和已有方法比新在哪`
6. `为什么它值得看`
7. `和用户方向的关系`

## Output Style

- Use Chinese by default for the final summary
- Keep the first sentence short and intuitive
- Make the rest specific
- Avoid generic phrases like “提出了一个新方法” unless followed by concrete mechanism details

## Density Control

Adjust detail level by importance:

- `Low relevance / low quality`
  - still mention the problem and core mechanism
  - keep it compact
- `Medium relevance`
  - explain the problem, method, and at least the main pipeline
- `High relevance / high quality`
  - explain the method and training or system pipeline in more detail
  - spend more attention budget here

## For Papers

Try to identify:

- objective
- model structure
- data flow
- training stages
- inference procedure
- main benchmark / evaluation setup
- when available, note whether the source is already a hot-paper source or a raw paper source

## For Repos / Models / Tools

Try to identify:

- what workflow it enables
- typical usage pipeline
- what system pieces it combines
- what makes it different from adjacent tools

## For X Threads / Blogs / News

Try to identify:

- what event or claim is being made
- whether there is a real method or system insight
- what the operational workflow is
- whether the item is worth following up in the original source

## Cross-Source Rule

If the same paper appears in multiple sources:

- do not summarize it independently in the same final report multiple times
- keep the strongest source framing
- borrow useful metadata from the other source if it helps

## Red Flags

Bad summary patterns:

- only trend talk
- only praise
- only “this is important”
- only restating the title

If the summary feels generic, rewrite it until the method or workflow is visible.
