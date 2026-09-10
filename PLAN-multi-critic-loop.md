# Plan: Multi-Critic Loop (Add a Grok Critic, Rename from Triple)

> Status 2026-09-10: the Grok critic shipped as an optional fourth critic behind `--grok` with a 300s timeout, and the scoring model now scales agreement by the number of critics that ran, so both three- and four-critic rounds are supported. The rename and the remaining phases below are still proposed, not executed.

Adds a fourth critic (Grok, via the `grok` CLI) to the review loop, moves the scoring model from a raw agreement count to a fractional agreement factor so severity thresholds keep their meaning at N=4, and renames the skill from `triple-critic-loop` to `multi-critic-loop` since "triple" stops being accurate. All facts below were measured on 2026-09-10 against the installed `grok 1.0.5 (5115b46bc909) [stable]` CLI, the current `SKILL.md` at commit `28f2d71`, and a scoring-space enumeration script (`scores4.py`) run against the same formula SKILL.md already uses.

## Decisions

| Decision | Recommendation | Alternative | What changes |
|---|---|---|---|
| Grok `EFFORT` mapping | Pass `--reasoning-effort "$EFFORT"` straight through (low/medium/high), matching the flag's alias `--effort` | Fall back to a model-variant scheme like Gemini's | Determines the grok command block below; **confirmed**: a live run with `--reasoning-effort medium` exited 0 and produced a normal response, see EFFORT mapping section below |
| Grok per-critic timeout `T` | 300s flat, or an inactivity guard if the harness supports one | Keep the shared 180s timeout | The fixture run took ~4 minutes; 180s kills every grok call |
| Fold-in gate at N=4 (critical/high) | Keep raw count >= 2 | Strict majority (> N/2 = 3 of 4) | 2-of-4 changes 10 cells vs today (all low-severity, agreement=3); majority changes 40 cells and demotes two-model-agreed critical findings |
| Fold-in gate at N=4 (medium) | Keep raw count >= 2, same as critical/high | Require 3 of 4 for medium only | Middle option changes 20 cells; recommendation changes none beyond the low-severity change already made |
| Low-severity fold-in unanimity | N-1 of N_ran (3 of 4), not strict unanimity (4 of 4) | Strict unanimity (all 4) | 10 cells differ, all at agreement=3, all low severity |
| Agreement in the score formula | Fractional: `agreement_factor = 3 * raised / N_ran` | Raw count | Raw count inflates N=4 cells >= HIGH from 108/210 to 185/315; fractional holds at 142/315 and keeps a unanimous finding scoring identically at N=3 and N=4 (180 either way) |
| External critic fallback cap | At most one of gemini/openai/grok substituted per round; two failures aborts as `failed_loop` | Allow two substitutions before aborting | Keeps Claude-origin critics (adversarial + substitute) a minority of 2-of-4; two substitutions would let Claude-origin critics alone constitute agreement |
| Degraded-round `N_ran` | Use the count of critics that actually produced usable output this round (not always 4) | Always divide by 4 | 3-of-3 survivors after one unsubstituted failure still scores as unanimous (180), not as 3-of-4 (135) |
| HIGH/LOW thresholds (50/33) | Keep as-is | Retune | Sweep across N=4 shows 202 of 420 cells are threshold-sensitive somewhere in a 40-80 / 20-50 grid; the current pair is doing real work without adjustment |
| Rename `triple-critic-loop` -> `multi-critic-loop` | Proceed, including the GitHub repo rename | Keep the old name, add Grok under the existing name | GitHub redirects the old URL automatically; local symlinks, the Claude Code project memory directory, and the skill directory name all need updating by hand |

## Grok Critic

### Identity and install

Fresh-machine install is `curl -fsSL https://x.ai/cli/install.sh | bash`, confirmed at `~/.grok/README.md` under "Quick Start": "# Install" followed by that exact line. On this machine, `~/.local/bin/grok` resolves (`readlink -f`) to `/Users/bradsmith/.grok/downloads/grok-macos-aarch64`. `~/.grok/version.json` records the installed build: `{"version": "1.0.5", "stable_version": "1.0.5", "checked_at": "2026-08-28T16:56:48.600932Z"}`. Updates run through `grok update`, confirmed via `grok update --help`, which lists `--check` ("Check for updates without installing"), `--json` ("Emit machine-readable JSON output (for --check)"), `--force-reinstall` ("Force re-download and install even if already up to date"), `--version <VERSION>` ("Install a specific version"), `--alpha` / `--stable` (release channel switches), `--debug`, `--debug-file <FILE>`, and `--leader-socket <PATH>`.

### Auth

`help.txt` lists `login` (`Sign in to Grok`) and `logout` (`Sign out and clear cached credentials`) subcommands, so auth is a browser OAuth flow via `grok login`. A credential is already present on this machine (`~/.grok/auth.json`), confirmed by `~/.grok/README.md`: "Credentials are stored in `~/.grok/auth.json` and persist across sessions. Tokens expire after 7 days; Grok will prompt you to re-authenticate when needed." An alternative is the `XAI_API_KEY` environment variable, confirmed in the same README (`export XAI_API_KEY="xai-..."`); neither file contains a real credential value, and none is stated here. Runs are billed per call, confirmed by `total_cost_usd` in the response envelope. For a non-interactive auth check, `grok models` prints a "logged in with" line before listing models; run on this machine it produced:

```
You are logged in with grok.com.

Default model: grok-4.6

Available models:
  * grok-4.6 (default)
  - grok-4.5
```

### Headless invocation

Flags quoted from `help.txt`:

- `-p, --single <PROMPT>`: "Single-turn prompt. Prints the response to stdout and exits"
- `--json-schema <SCHEMA>`: "JSON Schema for structured output. When set, the model is constrained to produce JSON matching this schema. Implies `--output-format json`. Example: `--json-schema '{"type":"object","properties":{"name":{"type":"string"}}}'`": the schema is passed as an inline string, not a file path, per that example
- `--reasoning-effort <EFFORT>`: "Reasoning effort for reasoning models" (alias `--effort`)
- `--sandbox <PROFILE>`: "Sandbox profile for filesystem and network access" (env `GROK_SANDBOX`)
- `--disallowed-tools <TOOLS>`: "Built-in tools to remove (comma-separated)"
- `--max-turns <N>`: "Maximum number of agent turns"
- `--output-format <OUTPUT_FORMAT>`: "Output format for headless mode" (values: `plain`, `json`, `streaming-json`, `streaming-messages-json`; default `plain`)

### Payload delivery

Stdin is not honored as the payload. A test that asked Grok to "follow the instruction on stdin" produced a model turn that tried to locate the instruction with tools instead of reading it (three separate stdin-following attempts were run this session, session titles "Follow Instructions Provided via Standard Input" / "Follow stdin instruction generic command" / "Follow Instructions from Standard Input"). The orchestrator read that run's envelope directly before the recon worker's cleanup removed it: stopReason `cancelled`, num_turns 1, and the response text opening with "I'll start by reading the instruction on stdin", which is the model reaching for a tool instead of receiving the piped content. The payload must go inline in the `-p` prompt, the same workaround already used for the Gemini critic (`agy`).

### Structured output shape

Findings land at `.structuredOutput`, a JSON value, camelCase: note the case difference from Gemini's `.structured_output`. `.text` carries the same JSON serialized as a string; no second parse of `.text` is needed.

### Measured run (fixture, same document as agy and codex)

| Critic | Wall time | Findings | Input tokens | Output tokens | Cost (USD) |
|---|---|---|---|---|---|
| grok (grok-4.6-build) | ~4 min (13:12-13:16) | 10 (3 critical, 5 high, 2 medium) | 17,749 | 13,389 | 0.0197132 |
| agy (Gemini, gemini-3.1-pro-low) | 29-36s | 8 | not reported by CLI | not reported by CLI | not reported by CLI |
| agy (Gemini, gemini-3.1-pro-high) | 44s | 8 | not reported by CLI | not reported by CLI | not reported by CLI |
| agy (Gemini, earlier unpinned runs) | 65-92s | 9 | 14,365 (one unpinned run) | not reported by CLI | not reported by CLI |
| codex (OpenAI, medium effort) | 54-62s | 8-9 | not reported by CLI | not reported by CLI | not reported by CLI |
| codex (OpenAI, high effort) | 64-86s | 9-11 | not reported by CLI | not reported by CLI | not reported by CLI |

Grok is the slowest critic by a wide margin on the same fixture. `stopReason` was `end_turn`, `num_turns` was 1, exit 0. The skill's current 180-second shared timeout would have killed this run before it produced output.

### Proposed SKILL.md command block

Matching the style of the existing `agy` and `openai` blocks:

```bash
SCHEMA_CONTENT=$(cat "$SCHEMA")
timeout "${T}s" ~/.local/bin/grok -p "<prompt>

$(payload)" --output-format json --json-schema "$SCHEMA_CONTENT" --reasoning-effort "$EFFORT" \
  --disallowed-tools "run_terminal_cmd,web_search,web_fetch,search_replace,task" --sandbox read-only --always-approve \
  > "$STATE_DIR/round_$N/grok.raw.json" 2> "$STATE_DIR/round_$N/grok.stderr"
jq '.structuredOutput' "$STATE_DIR/round_$N/grok.raw.json" > "$STATE_DIR/round_$N/grok.json"
```

The measured fixture run did not pass `--reasoning-effort`; adding it is proposed and separately confirmed accepted for `medium` (see EFFORT mapping below), though not yet run together with the fixture document in one call. `--always-approve` is already in the block as a safety net alongside `--disallowed-tools`: the disallowed-tools list removes specific built-in tools, and `--always-approve` prevents any remaining tool call from blocking on an interactive approval prompt in a headless run.

### EFFORT mapping

Propose `--reasoning-effort "$EFFORT"` unchanged (`low`, `medium`, `high` pass straight through), unlike Gemini's model-variant workaround. This is now **confirmed**: running `grok -p "Reply with the single word ready." --reasoning-effort medium --output-format json --sandbox read-only --disallowed-tools "run_terminal_cmd,web_search,web_fetch,search_replace,task" --always-approve` under `timeout 120s` exited 0 and returned a normal JSON envelope (`"stopReason": "end_turn"`, `"reasoning_tokens": 73` in `usage`), with no error about the value. `medium` is accepted. `low` and `high` were not independently tested this session; treat them as accepted by the same mechanism unless a future run shows otherwise.

### Error signature

An invalid model produces stderr:

```
Error: Couldn't set model 'definitely-not-a-real-model-xyz': Invalid params: "unknown model id". Run 'grok models' to see available models.
```

and stdout:

```json
{"type":"error","message":"Couldn't set model 'definitely-not-a-real-model-xyz': Invalid params: \"unknown model id\". Run 'grok models' to see available models."}
```

Confirmed by re-running `grok -p "hi" --model definitely-not-a-real-model-xyz --output-format json` under `timeout 60s`: exit code **1**, with the same `{"type":"error","message":...}` envelope on stdout and the matching `Error:` line on stderr.

Schema must be passed inline, not as a path: `--json-schema "$(cat "$SCHEMA")"`. Confirmed by re-running `grok -p "hi" --json-schema "$SCHEMA" --output-format json` (passing the file path directly, not its contents) under `timeout 30s`: exit 1, stderr `Error: --json-schema: invalid JSON: expected value at line 1 column 1`.

### Classification line (structured error output only)

```bash
{ jq -r 'select(.type=="error") | .message' "$STATE_DIR/round_$N/grok.raw.json"; grep -E '^Error:' "$STATE_DIR/round_$N/grok.stderr"; } \
  | grep -Eiq 'not authenticated|login required|invalid credentials|refresh token|invalid_grant|\b401\b|quota exceeded|rate limit|\b429\b|resource exhausted|usage limit'
```

Same principle as the existing agy/codex checks: match only the structured `type: error` envelope and the stable `^Error:` stderr marker, never free-form model text.

## Scoring Changes

### Why raw agreement breaks at N=4

Today's formula uses `agreement` as a raw count (1, 2, or 3). At N=4, a raw count of 3 (three of four critics) scores identically to a raw count of 3 at N=3 (three of three), even though the two mean different things: one is 75% agreement, the other is unanimous. Enumerating the full score space (`scores4.py`, `out.txt`) confirms the effect: cells scoring >= HIGH_THRESHOLD (50) go from 108 of 210 at N=3 to 185 of 315 at N=4 under raw count, purely from the extra agreement=4 cells being added, not from any real change in severity or confidence.

### Fractional agreement factor

Replace raw agreement with `agreement_factor = 3 * raised / N_ran`, where `raised` is the number of critics whose findings merged into this one and `N_ran` is the number of critics that produced usable output this round. This rescales agreement back onto the 0-3 range the rest of the formula was tuned against. Verified: a unanimous high/high/security finding scores 180 under fractional agreement at both N=3 (3 of 3) and N=4 (4 of 4); under raw count it scores 180 at N=3 but 240 at N=4, a score inflation with no underlying change in evidence. Across the full grid, fractional agreement holds cells >= HIGH(50) at 142 of 315 rather than raw count's 185 of 315.

Regression check: the fractional formula reproduces the prior N=3 baseline exactly: lowest two-critic critical/high at high confidence scores 64.0, highest two-critic low/info scores 60.0, matching the pre-Grok analysis.

### Fold-in gate (raw count, not fractional)

The fold-in gate stays a raw count of critics (`raised >= 2`), not the fractional factor: score already carries the fractional signal; the gate is a separate, coarser check ("did at least two independent models agree at all"). At N=4 this is a genuine decision point:

- **Keep raw 2** (recommended): 10 cells change action vs. the N=3 baseline, all low severity at agreement=3 (three of four critics; these move from fold_in to defer).
- **Strict majority (> N/2 = 3 of 4), applied uniformly**: 40 cells change, including critical/high findings at agreement=2 dropping from fold_in to defer, which demotes findings two independent models agreed on: the behavior the gate exists to protect.
- **Middle option: medium requires 3 of 4, critical/high stay at 2**: 20 cells change.

### Low-severity fold-in

Today's rule folds in low/info findings only when all critics raised them (unanimity). At N=4, recommend relaxing this to N-1 of N_ran (3 of 4) rather than keeping strict unanimity (4 of 4): 10 cells diverge between the two readings, all at agreement=3, all low severity. The unanimous reading defers/skips them; the N-1 reading can fold them in.

### Convergence, stall, and fallback

- `converged_early` / `stalled_no_actionable_fixes` keep tracking "at least 2 critics" on deferred critical/high findings, which stays aligned with the fold-in gate's own `raised >= 2` requirement for critical/high under every gate variant except strict majority, so no drift.
- External critic fallback: with three external critics (gemini, openai, grok) plus one Claude subagent (claude_adversarial), at most one external may fall back to an Opus subagent per round.

  | Externals failed | Claude-origin critics | Of 4 total |
  |---|---|---|
  | 0 | 1 (adversarial only) | 1 of 4 |
  | 1 | 2 (adversarial + 1 substitute) | 2 of 4 |
  | 2 | 3 (adversarial + 2 substitutes) | 3 of 4 |

  Two or more external failures in the same round aborts as `failed_loop`, same principle as today's two-of-two. Allowing two substitutions would put Claude-origin critics at 3 of 4, enough to form agreement among themselves without any external critic, which defeats the purpose of independent-model agreement.

- Degraded rounds: an unsubstituted failure drops `N_ran` to the critics that actually produced usable output. Three surviving critics unanimous still scores as fully unanimous (agreement_factor = 3, score 180 for high/high/security), not diluted toward the N=4 baseline (which would read as 135 at 3-of-4 raised).

### Threshold sweep

HIGH=50 / LOW=33 stay unchanged. A sweep from HIGH 40-80 and LOW 20-50 (step 5, HIGH > LOW) under the recommended gate shows 202 of 420 enumerated cells change action somewhere in that range; the thresholds are doing real discriminating work at N=4 without retuning; current settings sit inside that sensitive range rather than off in a flat zone.

### Exact SKILL.md replacement text

**`scoring_model`**, replace the `agreement` bullet and the score formula:

> - agreement: `agreement_factor = 3 * raised / N_ran`, where raised is the number of critics whose findings merged into this one and N_ran is the number of critics that produced usable output this round (their own output or a substitute's). Fractional, not a raw count, so agreement means the same fraction of participating critics whether N_ran is 3 or 4.
> - `score = round(severity * confidence * agreement_factor * impact * 10, 1)`. Open-topped; thresholds are absolute.

**`synthesis`**, replace step 4's fold-in rule:

> - score >= HIGH_THRESHOLD AND raised >= 2 AND (severity in [critical, high, medium] OR raised >= N_ran - 1): fold_in. A single critic never triggers a fix, whatever its score; the agreement of independent models is the gate. Low-severity findings fold in only when at least N_ran - 1 critics raised them.

**`loop_control`**, no wording change required; `raised >= 2` already matches the fold-in gate's own threshold for critical/high under the recommended gate at any N_ran.

**`external_critic_fallback`**, replace the substitution-count sentence:

> Any other failure (timeout, malformed output, empty findings, nonzero exit without that signature) takes the fallback path: immediately (without waiting for other critics) substitute a Claude subagent on `claude-opus-5`, passed explicitly, taking over that critic's prompt and role. At most one of the three external critics (gemini, openai, grok) may be substituted in a given round; if a second external critic fails in the same round, do not substitute it: abort with run_outcome failed_loop. Record every substitution or auth/quota abort in `notes.json`.

## Rename to multi-critic-loop

Ordered steps, all breaking changes are acceptable (development posture, no external consumers):

1. **Repo contents** (this skill's directory): update every "triple" occurrence outside `versions/`:
   - `SKILL.md`: frontmatter `name`, `description`, `<role_definition>` prose, `STATE_DIR` and `TMPFILE` prefixes (`/tmp/triple_critic_*` -> `/tmp/multi_critic_*`), the `$SCHEMA` path reference.
   - `README.md`: title, state dir example, clone path, `agents/` symlink command, invoke command (`/triple-critic-loop` -> `/multi-critic-loop`), the intent-invocation example, the layout tree.
   - `findings.schema.json`: `title` field.
   - `agents/critic-low.md`, `agents/critic-medium.md`, `agents/critic-high.md`: `description` frontmatter.
   - `versions/1.0/` stays untouched: it is the archived, originally-published skill.
2. **Repo directory name**: rename the working directory `triple-critic-loop` -> `multi-critic-loop`.
3. **GitHub remote**: rename the repo `bradsmithmba/triple-critic-loop` -> `bradsmithmba/multi-critic-loop` via the GitHub UI or `gh repo rename`. GitHub automatically redirects the old URL (`.../triple-critic-loop`) to the new one, including `git clone`/`git fetch` against the old remote URL, so existing local clones' remotes keep working without manual re-pointing, though updating them to the new URL directly is still cleaner.
4. **Skill symlink**: `~/.claude/skills/triple-critic-loop -> ~/Repos/triple-critic-loop` needs to become `~/.claude/skills/multi-critic-loop -> ~/Repos/multi-critic-loop`. Remove the old symlink; create the new one after step 2.
5. **Agent symlinks**: the three agent symlinks under `~/.claude/agents/` currently resolve through the old skill path; recreate them pointing at `~/Repos/multi-critic-loop/agents/critic-*.md` per the README's `ln -s` instructions, after step 2.
6. **Claude Code project memory directory**: the memory directory is keyed to the repo's absolute path (`~/.claude/projects/-Users-bradsmith-Repos-triple-critic-loop/...`). Renaming the repo directory means new sessions key to a new memory directory; the old one is not migrated automatically. Decide whether to carry old session history forward manually or accept a fresh start under the new path. No destructive action is required, the old directory is simply orphaned, not deleted.

**Rollback**: reverse order: restore the GitHub repo name (the redirect means this is optional; both names route to the same repo id until a *new* repo claims the old name), restore the local directory name, recreate the old skill and agent symlinks, revert the content edits. Nothing in this rename touches state directories from past runs, so no run history is at risk either direction.

## Other SKILL.md and README Changes

- **Critic count wording**: every "three critics" / "triple-critic" reference in `<role_definition>`, the README's intro paragraph, and the "What it does" numbered list becomes "four critics" / "multi-critic," including the description frontmatter's "Launches three independent critics (Gemini, OpenAI, Claude adversarial)" -> "Launches four independent critics (Gemini, OpenAI, Grok, Claude adversarial)."
- **Timeout budget per critic**: introduce a per-critic `T`, not a single shared value. Grok needs its own: `T=300` (see Decisions), against the measured ~4-minute fixture run. Keep the existing `180s + 30s per 100KB beyond 200KB` scaling formula for gemini/openai, and apply the same scaling on top of grok's 300s floor rather than its 180s floor.
- **State directory files for grok**: add `round_N/grok.raw.json`, `round_N/grok.json`, `round_N/grok.stderr` to the `<state>` section's per-round file list, alongside the existing gemini/openai/claude entries.
- **`critic_protocol` prompt**: unchanged. It is critic-agnostic already; grok consumes it the same way gemini does (inline in the prompt).
- **Final report sections**: `<final_report>` doesn't hardcode "three" anywhere in the current text, so no edit needed there beyond the general critic-count wording pass above.
- **Description frontmatter data-handling note**: "documents under review are sent to external CLIs (Gemini, OpenAI/Codex)" -> "documents under review are sent to external CLIs (Gemini, OpenAI/Codex, xAI/Grok)."

## Verification Plan

1. **Fixture-based checks per critic**: re-run the fixture document (`../trackA/fixture.md`) through gemini, openai, and grok independently with the finalized command blocks; confirm each produces a schema-valid `findings` array and a nonzero-length `.structuredOutput`/`.structured_output` extraction.
2. **Classification silence check**: run each critic's classification `grep`/`jq` pipeline against its own successful-run artifacts (`fixture_run.json`/`fixture_run.stderr` for grok) and confirm it reports no match: a false positive here would wrongly abort a healthy round.
3. **Scoring regression**: re-run `scores4.py` (or the equivalent for the final chosen gate) and confirm the Q0 regression numbers (64.0 / 60.0) still reproduce, and that the chosen fold-in gate's cell-change counts match this plan's tables.
4. **Full four-critic round (acceptance test)**: run the complete loop against the fixture document with all four critics live, `LOOPS=1`, and confirm: all four `round_1/*.json` files are written, synthesis produces a `synthesis.json` with `N_ran=4` findings scored under the fractional formula, and the final report's `scoring_summary` names any single-critic findings withheld for lack of agreement.

## Open Questions and Risks

- **Grok wall time and cost per round**: one fixture data point (~4 min, $0.02) is not a distribution. Confirm timeout headroom and per-round cost budget across a few more runs before relying on `T=300`.
- **`--json-schema` argv length limits**: both the schema and the payload are passed inline as command-line arguments (not files), per `help.txt`'s own example. Large schemas or large target documents risk hitting OS `ARG_MAX` or grok-internal argument-length limits; not tested at scale this session.
- **`--sandbox read-only` sufficiency**: assumed adequate by analogy to the disallowed-tools list, but not independently verified against grok's sandbox profile semantics; `help.txt` documents the flag's existence, not its exact filesystem/network boundary.
- **The two-of-four fold-in tie**: this plan recommends raw >= 2 for all severities above low, but it is a closer call than the low-severity unanimity question (10 cells either way is a bigger swing on critical/high paths than on low ones, even though the cell count is the same, because critical/high findings are the ones that get auto-applied). Flagged as the primary judgment call in this plan; see Decisions table.

## Execution Order

1. **Phase 1: Grok critic mechanics**: add the grok command block, state files, classification check, and EFFORT confirmation to `SKILL.md`. Gate: fixture run per Verification step 1 and 2 passes for grok alone.
2. **Phase 2: Scoring model**: replace `scoring_model`, `synthesis`, and `external_critic_fallback` text with the exact replacement sentences above. Gate: `scores4.py` regression (Verification step 3) reproduces baseline numbers and this plan's cell-change counts.
3. **Phase 3: Rename**: repo contents, directory, GitHub remote, skill/agent symlinks, in the order listed under Rename. Gate: `/multi-critic-loop` invokable from a fresh Claude Code launch, agent symlinks resolve.
4. **Phase 4: Wording pass**: critic-count wording, timeout budget documentation, state-directory file list, data-handling note. Gate: no remaining "triple" outside `versions/`.
5. **Phase 5: Acceptance**: full four-critic round per Verification step 4. Gate: run completes with a valid final report naming `N_ran=4`.
