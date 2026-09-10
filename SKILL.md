---
name: triple-critic-loop
description: "Orchestrates a scored triple-critic design review. Launches three independent critics (Gemini, OpenAI, Claude adversarial), synthesizes and scores findings, applies fixes that at least two critics agree on, and repeats for the configured number of rounds. Returns a final report with severity curve, scoring summary, and deferred architectural reversals. Data handling: documents under review are sent to external CLIs (Gemini, OpenAI/Codex); do not run this skill on documents containing credentials, PII, or data governed by residency requirements."
disable-model-invocation: false
---

<role_definition>
- You are the orchestrator of a scored triple-critic design review.
- Each round: launch three independent critics in parallel, merge and score their findings, decide which findings to fix, and launch ONE apply agent that composes and applies those fixes. Critics never edit. You never edit the target yourself.
- Run up to LOOPS rounds. Exit early only on a loop_control exit condition. Never ask the user questions between rounds.
</role_definition>

<inputs>
- `DOCUMENT_PATH` (required): absolute path to the target. A file, or a directory whose `*.md` and `*.txt` files are reviewed together (each document's quality plus cross-document consistency).
- `CONTEXT_PATHS` (optional): comma-separated absolute paths (files or directories) of reference documents the target must conform to. Critics read them but raise findings only against the target.
- `LOOPS` (optional, default 3): maximum rounds. Integer >= 1.
- `HIGH_THRESHOLD` (optional, default 50): score at or above which an eligible finding is fixed.
- `LOW_THRESHOLD` (optional, default 33): score at or above which a finding is deferred for discussion. Below it, skipped.
- `APPLY_MODEL` (optional, default `sonnet`): model for the apply agent. It composes edits from recommendations, so it needs judgment; downgrade to `haiku` only for trivial documents.
- `STATE_DIR` (optional): path of a state directory from an interrupted run, to resume it. When omitted, a new one is created.

Validate before launching anything: LOOPS >= 1, HIGH_THRESHOLD > LOW_THRESHOLD >= 0, every path absolute and existing. On failure, abort with a clear error.
</inputs>

<state>
At run start, unless resuming: `STATE_DIR=$(mktemp -d /tmp/triple_critic_XXXXXX)`. It holds, per round N:
- `round_N/gemini.json`, `round_N/openai.json`, `round_N/claude.json`: raw critic output, one `findings` array each.
- `round_N/synthesis.json`: merged findings with source critics, agreement count, score, action, and status.
- `round_N/snapshot/`: copy of the target taken before the apply step.
- `round_N/applied.diff`: `diff -ru round_N/snapshot <target>` after the apply step.
- `round_N/notes.json`: fallback substitutions, halts, unapplied findings.

The state directory is never deleted. It is the audit trail, the input to the final report, and the resume point: when STATE_DIR is given, continue from the first round that has no `synthesis.json`. Later rounds read prior_findings and the previous diff from here rather than carrying them in context.
</state>

<critic_protocol>
Shared contract for all three critics.

### Input
- TARGET: the full target under DOCUMENT_PATH. Directories are expanded with `find "$P" -type f \( -name "*.md" -o -name "*.txt" \) -print0 | while IFS= read -r -d '' f; do echo "----- FILE: $f -----"; cat "$f"; done` so findings stay locatable per file.
- REFERENCE CONTEXT (when CONTEXT_PATHS is set): each path, expanded the same way, marked read-only.
- ALREADY_ADDRESSED (round 2 onward): the finding_id, title, root_cause, and affected_component of every finding fixed or deferred in prior rounds, taken from the state directory.
- PREVIOUS_ROUND_DIFF (round 2 onward): `round_{N-1}/applied.diff`.

### Prompt
"Review the TARGET for defects. Treat the REFERENCE CONTEXT, if present, as the authoritative design the target must conform to; raise findings against the target only, including where it contradicts or omits something the reference requires. If PREVIOUS_ROUND_DIFF is present, first check whether each change in it resolves the finding it was meant to fix, and raise a finding only where it does not. Do not re-raise anything in ALREADY_ADDRESSED unless you have new evidence the fix was insufficient. Critique only the provided text; do not read other files or call tools. For every finding give: a stable finding_id, title, severity (critical, high, medium, low, info), confidence (high, medium, low), impact_dimensions, whether it requires an architectural reversal, root_cause as one phrase naming the underlying defect rather than the symptom, affected_component as the section heading (and file when there are several), evidence as a location plus a verbatim quote of at most 40 words, and a recommendation. Respond only with JSON matching the supplied schema."

### Output
JSON matching `findings.schema.json` in this skill's directory (`SCHEMA=~/.claude/skills/triple-critic-loop/findings.schema.json`). Output is usable when it parses and `findings` is a non-empty array whose entries validate against the schema. An empty array is not a clean bill of health; it is a failed critic and triggers external_critic_fallback.

### Payload assembly for the external critics
Build the payload in one function; codex takes it on stdin, Gemini takes it inside the prompt:
```bash
payload() {
  echo "===== TARGET (critique this) ====="; expand "$DOCUMENT_PATH"
  if [ -n "$CONTEXT_PATHS" ]; then
    echo "===== REFERENCE CONTEXT (read-only, do not critique) ====="
    IFS=',' read -ra CTX <<< "$CONTEXT_PATHS"; for p in "${CTX[@]}"; do expand "$p"; done
  fi
  [ -f "$ADDRESSED" ] && { echo "===== ALREADY_ADDRESSED ====="; cat "$ADDRESSED"; }
  [ -f "$PREVDIFF" ] && { echo "===== PREVIOUS_ROUND_DIFF ====="; cat "$PREVDIFF"; }
}
```
where `expand` cats a file or applies the directory expansion above. Quote every variable. Timeout: 180s, plus 30s per 100KB of payload beyond 200KB.
</critic_protocol>

<agents>
### gemini (external)
The Gemini CLI ignores stdin in schema mode, so the payload goes inside the prompt, and `--print` must be the last flag because it consumes the next token as its prompt:
```bash
timeout "${T}s" ~/.local/bin/agy --sandbox --output-format json --json-schema "$SCHEMA" --print "<prompt>

$(payload)" > "$STATE_DIR/round_$N/gemini.raw.json"
jq '.structured_output' "$STATE_DIR/round_$N/gemini.raw.json" > "$STATE_DIR/round_$N/gemini.json"
```
The findings live at `.structured_output`, already a JSON value. Ignore `.response`; it is a string that can hold concatenated fragments. Do not summarize or filter.

### openai (external)
Runs on the user's ChatGPT OAuth session and default codex model. Everything must run in ONE shell invocation:
```bash
TMPFILE=$(mktemp /tmp/triple_critic_openai_XXXXXX.json); trap 'rm -f "$TMPFILE"' EXIT
payload | timeout "${T}s" codex exec --skip-git-repo-check -s read-only --ephemeral --color never --output-schema "$SCHEMA" -o "$TMPFILE" "<prompt> Perform a balanced system-level critique across architecture, reliability, security, performance, scalability, and operability."
cp "$TMPFILE" "$STATE_DIR/round_$N/openai.json"
```

### claude_adversarial (Claude subagent, model `claude-sonnet-4-6`, passed explicitly)
Follows critic_protocol; reads the target and context with its own tools and writes `round_N/claude.json`. Prompt suffix: "Assume the design will fail. Challenge every mitigation until proven sufficient. Do not soften findings." Pick the focus list for the document type and include it: for systems and code, race conditions, concurrency, security bypass, scale failure, hidden assumptions, week-one production failures; for product and process documents, unstated assumptions, missing failure paths, unowned decisions, unmeasurable success criteria, and contradictions with the reference context.

### external_critic_fallback
An external critic fails when its command exits non-zero, times out, or its output is not usable per critic_protocol. On detecting a failure, immediately (without waiting for other critics) substitute a Claude subagent on `claude-opus-5`, passed explicitly, taking over that critic's prompt and role. Opus rather than Sonnet keeps the critic set model-diverse, since the adversarial critic is already Sonnet. If both external critics fail in the same round, do not substitute: abort with run_outcome failed_loop. Record every substitution in `notes.json`.

### apply agent (Claude subagent, model APPLY_MODEL, passed explicitly)
Receives the target path and the list of fold_in findings: finding_id, affected_component, evidence, recommendation, and the merged recommendations of all source critics. For each finding it composes the minimal edit that implements the recommendation and applies it with exact-match edits, one finding at a time. It changes nothing outside the affected component, never touches reference documents, and reports each finding as applied or unapplied with a reason. It never spawns subagents.
</agents>

<scoring_model>
- severity: critical 5, high 4, medium 3, low 2, info 1
- confidence: high 1.0, medium 0.7, low 0.4
- agreement: number of critics whose findings merged into this one (1, 2, or 3)
- impact: the highest weight among the listed impact_dimensions. correctness 1.3, security 1.5, reliability 1.4, scalability 1.2, operability 1.1, maintainability 1.0, clarity 0.8. The max, not the mean, so a critic that lists an extra low-weight dimension is not penalized for thoroughness; score inflation from a single critic is already contained by the agreement gate.
- `score = round(severity * confidence * agreement * impact * 10, 1)`. Open-topped; thresholds are absolute.
</scoring_model>

<synthesis>
1. Load the three critic files. Two findings merge when their root_cause names the same defect AND their affected_component is the same section or file. Title or evidence similarity alone never merges.
2. A merged finding keeps every source critic, the maximum severity, the highest confidence unless the evidence conflicts, and the union of impact_dimensions. Recommendations combine when compatible; when they conflict, keep both verbatim and mark `conflicting_recommendations: true`. Do not judge which is safer.
3. Score every merged finding per scoring_model. Preserve unique findings and disagreements; drop nothing.
4. Assign an action, first rule that matches wins:
   - `architectural_reversal` true: defer. Never auto-applied, never stops the loop, surfaced in the final report only.
   - `conflicting_recommendations` true: defer.
   - score >= HIGH_THRESHOLD AND agreement >= 2 AND (severity in [critical, high, medium] OR agreement == 3): fold_in. A single critic never triggers a fix, whatever its score; the agreement of independent models is the gate. Low-severity findings fold in only when all three critics raised them.
   - score >= LOW_THRESHOLD: defer.
   - otherwise: skip.
5. Write `synthesis.json`. A round with an incomplete synthesis is invalid; halt it.

An architectural reversal is a finding that changes a core architecture decision, adds an unplanned external dependency, changes a public API or interface contract, or invalidates a locked design premise.
</synthesis>

<round_execution>
1. Create `round_N/`. Launch all three critics in parallel; apply external_critic_fallback on any failure. Each critic sees the full target and nothing from any other critic.
2. Run synthesis.
3. If no finding has action fold_in, record zero applied fixes and go to step 6.
4. Copy the target to `round_N/snapshot/`. Launch the single apply agent with the fold_in findings.
5. After it returns, write `applied.diff`. Review the diff: every hunk must map to a fold_in finding's affected_component, and the document must still be well-formed (balanced XML tags, or Markdown heading structure intact). If either check fails, restore the snapshot over the target, record the halt in `notes.json`, and stop with run_outcome halted_on_invariant. Findings the agent reported unapplied are recorded as such.
6. Update `notes.json`, then evaluate loop_control.
</round_execution>

<loop_control>
Evaluated after each round, in order:
- failed_loop: both external critics failed this round. Stop. Earlier rounds' edits stand.
- converged_early: zero fixes applied this round and no deferred finding of severity critical or high with agreement >= 2. Stop.
- stalled_no_actionable_fixes: zero fixes applied this round but at least one deferred critical or high finding with agreement >= 2 remains. Stop; the document has unresolved high-severity issues that cannot be auto-applied.
- Otherwise continue until LOOPS rounds are complete: completed_all_rounds.
</loop_control>

<final_report>
Assemble from the state directory. State the STATE_DIR path at the top. Required sections:
- `run_outcome`: one of completed_all_rounds, converged_early, stalled_no_actionable_fixes, halted_on_invariant, failed_loop, with the round it occurred in and the cause (the blocking findings for a stall, the check that failed and whether the round was reverted for a halt, which critics failed for a failed loop).
- `findings_by_severity`: severity, source critics, agreement, score, action, status.
- `findings_by_score`: sorted by score descending.
- `applied_changes_by_round`: round, finding_id, one-line fix summary, affected_component. Include unapplied findings and their reasons.
- `severity_curve`: critical, high, and medium counts per round.
- `scoring_summary`: score distribution, top findings, why each deferred or skipped finding landed there, single-critic findings that exceeded HIGH_THRESHOLD but were withheld for lack of agreement.
- `architectural_reversals_deferred`: each reversal, why it was deferred, and your recommended direction.
- `remaining_risks`: unresolved risks, deferred non-architectural findings, low-confidence items, fallback substitutions.
- `next_steps`: ordered actions required before implementation begins.
</final_report>
