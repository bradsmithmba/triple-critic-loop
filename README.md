# triple-critic-loop

A Claude Code skill that orchestrates a scored, multi-round design review using three independent critics.

## What it does

Given a design document (or a directory of documents), the skill runs N review rounds. Each round:

1. Launches three independent critics in parallel:
   - **Gemini** (external, via the Gemini CLI)
   - **Claude balanced** (system-level critique: architecture, reliability, security, performance, scalability, operability)
   - **Claude adversarial** (assumes the design fails: race conditions, concurrency, security bypass, scale failure, hidden assumptions)
2. Deduplicates and synthesizes findings, preserving disagreement between critics.
3. Scores every finding (severity x confidence x critic weight x cross-critic agreement x impact weight).
4. Auto-applies eligible fixes via parallel implementation agents on non-overlapping edit scopes.
5. Defers architectural reversals instead of applying them.

It returns a final report: findings by severity and score, applied changes per round, a severity curve across rounds, a scoring summary, and deferred architectural reversals.

## Install

Standalone skill. Drop the skill folder into your skills directory:

```bash
git clone <repo-url> ~/.claude/skills/triple-critic-loop
```

Claude Code discovers it on next launch.

## Invoke

```
/triple-critic-loop
```

Or let Claude invoke it by intent (e.g. "run a triple-critic design review on this spec").

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `DOCUMENT_PATH` | yes | — | Absolute path to the document or directory under review. |
| `CONTEXT_PATHS` | no | — | Comma-separated reference docs the target must stay consistent with (read-only context). |
| `LOOPS` | no | `3` | Number of review rounds. |
| `HIGH_THRESHOLD` | no | `50` | Normalized score (0-100) at or above which a finding is auto-applied. |
| `LOW_THRESHOLD` | no | `33` | Normalized score at or above which a finding is deferred rather than skipped. |
| `PRIOR_FINDINGS` | no | — | Cumulative findings carried in from prior rounds. |

## Dependencies

- Claude Code with subagent support (Claude critics and implementation agents run on `claude-sonnet-4-6`).
- The Gemini CLI for the external critic (`~/.local/bin/agy` in the current configuration).

## Layout

```
triple-critic-loop/
├── SKILL.md     # the skill definition
├── README.md
└── .gitignore
```
