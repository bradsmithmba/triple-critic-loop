# triple-critic-loop

The three main frontier models each have their own strengths and weaknesses. I started off using them to check and improve each other's work, but manually copying and pasting things back and forth so often was more than a little inefficient. I was tired of being the glue that held multiple models together. It seemed like I should be making them do all the work instead of me running back and forth between them. This loop is a result of that need.

This loop has an orchestrator that launches three sub agents with clean context, one each from Gemini, ChatGPT, and one from Anthropic that is set to be adversarial on purpose. These three agents act as critics to review whatever document or code you send to them. They very often have very different perspectives and having those different perspectives makes this loop much better at finding problems. The three agents report their findings back to the orchestrator. The orchestrator, which has all the relevant context, then ranks and scores these potential changes. Based on thresholds you set, the orchestrator then launches an agent to apply the fixes. This preserves the main orchestrator's context window. The loop then repeats three times or as many as you tell it to.

## What it does

Given a design document (or a directory of documents), the skill runs N review rounds. Each round:

1. Launches three independent critics in parallel:
   - **Gemini** (external, via the Gemini CLI)
   - **OpenAI** (external, via the Codex CLI on your ChatGPT OAuth session; balanced system-level critique: architecture, reliability, security, performance, scalability, operability)
   - **Claude adversarial** (Claude subagent; assumes the design fails: race conditions, concurrency, security bypass, scale failure, hidden assumptions)

   If one external critic fails to launch in a round, a Sonnet subagent is substituted for its task so every round still has three critics. If both external critics fail in the same round, the run stops as a failed loop.
2. Deduplicates and synthesizes findings, preserving disagreement between critics.
3. Scores every finding (severity x confidence x agreement factor x impact weight); the agreement factor grows with the number of critics that raised the finding.
4. Auto-applies eligible fixes: the orchestrator decides the change set, then a single implementation subagent applies it sequentially (the critics never edit).
5. Defers architectural reversals instead of applying them.

The loop stops early if a round applies no fixes and no critical or high findings remain (convergence). It returns a final report: the run outcome (completed, converged early, stalled, or failed), findings by severity and score, applied changes per round, a severity curve across rounds, a scoring summary, and deferred architectural reversals.

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
| `DOCUMENT_PATH` | yes | n/a | Absolute path to the document or directory under review. |
| `CONTEXT_PATHS` | no | n/a | Comma-separated reference docs the target must stay consistent with (read-only context). |
| `LOOPS` | no | `3` | Maximum number of review rounds; the loop may stop early on convergence. |
| `HIGH_THRESHOLD` | no | `50` | Score at or above which an eligible finding is auto-applied. The scale is open-topped and can exceed 100 when critics agree. |
| `LOW_THRESHOLD` | no | `33` | Score at or above which a finding is deferred rather than skipped. |
| `PRIOR_FINDINGS` | no | n/a | Cumulative findings carried in from prior rounds. |

## Dependencies

- Claude Code with subagent support (the adversarial critic, any fallback critics, and the single implementation subagent run on `claude-sonnet-4-6`).
- The Gemini CLI for the Gemini critic (`~/.local/bin/agy` in the current configuration).
- The Codex CLI for the OpenAI critic, signed in with ChatGPT OAuth (`codex login`; verify with `codex login status`). Uses your codex default model, no API key required. If Codex is not authenticated, that critic falls back to a Sonnet subagent each round.
- GNU coreutils, for `timeout` on the external critic calls. Linux ships it; on macOS install with `brew install coreutils` (provides `timeout` and `gtimeout`). Without it, the external critic commands fail with "command not found".

## Layout

```
triple-critic-loop/
├── SKILL.md            # the skill definition (canonical)
├── versions/
│   └── 1.0/SKILL.md    # originally published skill, preserved
├── README.md
├── LICENSE
└── .gitignore
```

## License

MIT. See [LICENSE](LICENSE).
