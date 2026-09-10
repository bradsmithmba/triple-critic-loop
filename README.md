# triple-critic-loop

The three main frontier models each have their own strengths and weaknesses. I started off using them to check and improve each other's work, but manually copying and pasting things back and forth so often was more than a little inefficient. I was tired of being the glue that held multiple models together. It seemed like I should be making them do all the work instead of me running back and forth between them. This loop is a result of that need.

This loop has an orchestrator that launches three sub agents with clean context, one each from Gemini, ChatGPT, and one from Anthropic that is set to be adversarial on purpose. These three agents act as critics to review whatever document or code you send to them. They very often have very different perspectives and having those different perspectives makes this loop much better at finding problems. The three agents report their findings back to the orchestrator. The orchestrator, which has all the relevant context, then ranks and scores these potential changes. Based on thresholds you set, the orchestrator then launches an agent to apply the fixes. This preserves the main orchestrator's context window. The loop then repeats three times or as many as you tell it to.

## What it does

Given a design document (or a directory of documents), the skill runs N review rounds. Each round:

1. Launches three independent critics in parallel:
   - **Gemini** (external, via the Gemini CLI)
   - **OpenAI** (external, via the Codex CLI on your ChatGPT OAuth session; balanced system-level critique: architecture, reliability, security, performance, scalability, operability)
   - **Claude adversarial** (Claude subagent; assumes the design fails: race conditions, concurrency, security bypass, scale failure, hidden assumptions)

   Every critic returns JSON validated against `findings.schema.json`, including a root cause and affected component per finding. An external critic that returns no findings is treated as failed, not as a clean review. For the OpenAI critic, a nonzero exit with no output file means the process died mid-stream; that gets one retry with a fresh invocation before it is treated as a failure. A failed critic is classified before any substitution: an authentication or quota failure (not authenticated, invalid credentials, quota exceeded, rate limit, and similar signatures) is not substituted, since the condition will recur every round, and the run stops as a failed loop naming the critic and the signature. Any other failure (timeout, malformed output, empty findings) is substituted with an Opus subagent taking over that critic's role, so the round still has three critics from at least two model families. If both external critics fail in the same round, the run stops as a failed loop.
2. Merges findings that share a root cause and affected component, preserving every source critic and any disagreement between them.
3. Scores every finding (severity x confidence x agreement x impact weight). Agreement is the number of critics that raised the finding.
4. Applies eligible fixes: a finding is fixed only when at least two critics raised it and its score clears the threshold. A single critic can never trigger an edit, and a low-severity finding is fixed only when all three critics raised it. The orchestrator hands the eligible findings to one apply agent, which composes and applies the edits; critics never edit.
5. Defers architectural reversals and conflicting recommendations for human review instead of applying them.

From round two onward, critics also receive the previous round's diff and verify those fixes before looking for new issues. The loop stops early when a round applies no fixes and no critical or high finding with two-critic agreement remains (convergence), or when such findings remain but cannot be auto-applied (stall).

Every run writes a state directory (`/tmp/triple_critic_*`) holding raw critic output, the scored synthesis, a pre-apply snapshot, and a unified diff per round. It is kept after the run as the audit trail and can be passed back as `STATE_DIR` to resume an interrupted run. The final report gives the run outcome (completed, converged early, stalled, halted, or failed), findings by severity and score, applied changes per round, a severity curve across rounds, a scoring summary, and deferred architectural reversals.

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
| `HIGH_THRESHOLD` | no | `50` | Score at or above which a finding with two-critic agreement is auto-applied. The scale is open-topped and can exceed 100 when all three critics agree. |
| `LOW_THRESHOLD` | no | `33` | Score at or above which a finding is deferred rather than skipped. |
| `APPLY_MODEL` | no | `sonnet` | Model for the single apply agent. It composes edits from the critics' recommendations, so it needs judgment; use `haiku` only for trivial documents. |
| `STATE_DIR` | no | n/a | State directory from an interrupted run, to resume it. |

## Dependencies

- Claude Code with subagent support. The adversarial critic runs on `claude-sonnet-4-6`, fallback critics on `claude-opus-5`, and the apply agent on Sonnet by default (change via the `APPLY_MODEL` input).
- The Gemini CLI for the Gemini critic (`~/.local/bin/agy` in the current configuration). Must support `--output-format json` and `--json-schema`. The document travels inside the prompt because this CLI ignores stdin in schema mode. Invoked with `NO_BROWSER=1 TERM=xterm-256color` so it does not try to open a browser or assume an unsupported terminal in a headless environment.
- `jq`, to extract the Gemini result from its JSON envelope.
- The Codex CLI for the OpenAI critic, signed in with ChatGPT OAuth (`codex login`; verify with `codex login status`). Uses your codex default model at high reasoning effort, no API key required. Must support `--output-schema` and `-c model_reasoning_effort`. If Codex is not authenticated, the run stops as a failed loop instead of falling back, since re-authenticating is required before the critic can run at all.
- GNU coreutils, for `timeout` on the external critic calls. Linux ships it; on macOS install with `brew install coreutils` (provides `timeout` and `gtimeout`). Without it, the external critic commands fail with "command not found".

## Layout

```
triple-critic-loop/
├── SKILL.md              # the skill definition (canonical)
├── findings.schema.json  # JSON schema every critic's output must match
├── versions/
│   └── 1.0/SKILL.md      # originally published skill, preserved
├── README.md
├── LICENSE
└── .gitignore
```

## License

MIT. See [LICENSE](LICENSE).
