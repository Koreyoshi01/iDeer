---
name: idea-plan-from-digest
description: "Use when the user wants a few high-quality research ideas from today's digest, each with evidence, core insight, and an initial feasible plan, rather than a long list of weak ideas."
argument-hint: "[date] [--max N]"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, AskUserQuestion
---

# Idea Plan From Digest

Adapt the existing `idea-from-daily` flow into a high-quality, low-count idea generator.

## Goal

Produce a small number of strong ideas, each tied back to evidence from the digest and paired with a concrete first-step plan.

## Quantity Policy

- Minimum: `1`
- Preferred: `1-3`
- Maximum: `5`, and only if there are multiple clearly strong ideas

## Evidence Policy

Every idea must include:

- `basis`
  - which papers / repos / X dynamics / hot signals it comes from
- `core insight`
  - what higher-level connection or transfer the idea relies on
- `initial plan`
  - what to build or test first
- `min experiment`
  - the fastest reality check

## Quality Gate

Before keeping an idea:

- ask whether the idea is genuinely more than “apply X to Y”
- check whether there is at least one concrete bottleneck, mismatch, or transfer opportunity supporting it
- prefer 1 strong idea over 3 generic ideas
- if the evidence is weak, drop the idea

## Idea Sources

Ideas may come from:

- strong-related papers from the digest
- globally hot but weakly related papers whose insight transfers well
- X dynamics that reveal practical bottlenecks or emerging workflows
- well-known prior methods that can now be recombined with today’s signals

## Selection Policy

Prefer ideas that are:

- understandable
- non-trivial
- evidence-backed
- feasible for a first experiment
- likely to matter if successful
- grounded in specific digest evidence, not only intuition

## Review Policy

For the strongest idea:

- run `research-review` style critique if available
- then turn it into a concise implementation or experiment plan
- if the critique reveals a missing assumption, repair the idea before final output

## Deliverable Shape

Each idea should contain:

- title
- hypothesis
- basis
- core insight
- initial plan
- min experiment
- novelty
- feasibility
- explicit source attribution
