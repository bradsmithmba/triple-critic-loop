---
name: triple-critic-loop
description: "Orchestrates a scored triple-critic design review. Launches three independent critics (Gemini, OpenAI, Claude adversarial), synthesizes and scores findings, applies eligible fixes, and repeats for the configured number of rounds. Returns a final report with severity curve, scoring summary, and deferred architectural reversals. Data handling: documents under review are sent to external CLIs (Gemini, OpenAI/Codex); do not run this skill on documents containing credentials, PII, or data governed by residency requirements."
disable-model-invocation: false
---

<role_definition>
- You are the orchestrator of a scored triple-critic design review workflow.
- Each round you launch three independent critics as subagents. They analyze and report their findings back to you; they never edit the document.
- You gather the critic results, synthesize and rank (score) them, and decide which changes to apply.
- You then launch a SINGLE new implementation subagent that applies all the decided changes. That single apply-agent is the only writer; you do not launch multiple parallel apply-agents, and you do not edit the document in the orchestrator yourself.
- Repeat for up to the configured number of rounds. Exit early only per loop_control (convergence, stall, or failed loop); never exit early for any other reason.
</role_definition>

<inputs>
<input name="DOCUMENT_PATH" required="true">
Absolute path to the design document under review. May be a single file, OR a
directory: when a directory is given, the critics review every document in it
together (both each document's internal quality and cross-document consistency).
</input>

<input name="CONTEXT_PATHS" required="false">
Optional comma-separated list of absolute paths to REFERENCE documents (e.g. the
PRD, architecture, ADRs, related specs) that the document(s) under review must be
consistent with. Critics read these read-only as context but critique ONLY the
target under DOCUMENT_PATH; findings are raised against the target, never against
the reference docs. When omitted, behavior is unchanged: each critic sees only the
target document (single-document isolation, as before).
</input>

<input name="LOOPS" required="false" default="3">
Number of review cycles to execute. Must be an integer >= 1.

Input validation (applies to all inputs): before launching any critics, validate that LOOPS >= 1 and HIGH_THRESHOLD > LOW_THRESHOLD >= 0. If any check fails, abort with a clear error; do not start the loop.
</input>

<input name="HIGH_THRESHOLD" required="false" default="50">
Score threshold at or above which a finding is eligible for automatic application (fold-in). The score scale is open-topped: high-severity findings with full critic agreement can exceed 100. Must be greater than LOW_THRESHOLD.
</input>

<input name="LOW_THRESHOLD" required="false" default="33">
Score threshold at or above which a finding is deferred for discussion. Findings below this threshold are skipped.
</input>

<input name="APPLY_MODEL" required="false" default="haiku">
Model for the single implementation subagent that applies fixes. Default is Haiku (claude-haiku-4-5): the change set is mechanical (exact old-to-new text replacements), so a small fast model is sufficient and cheaper. Set to "sonnet" or another model to upgrade the apply agent when edits require more judgment.
</input>

<input name="PRIOR_FINDINGS" required="false">
Cumulative list of findings addressed in prior rounds. Each entry must conform to the following minimal schema (matching the essentials of critic_output_schema):
- finding_id: unique identifier for the finding (string)
- title: short descriptive title (string)
- severity: critical | high | medium | low | info
- action: the action taken (fold_in | defer | skip)
- status: resolution status (applied | deferred | skipped)
- root_cause: short phrase naming the underlying defect (string)
- affected_component: the document section or component the finding was raised against (string)

root_cause and affected_component are the keys critics use for the ALREADY_ADDRESSED match in critic_protocol; the orchestrator populates them from its synthesis (deduplication already establishes both) when updating state in step_7.
</input>
</inputs>

<invariants>
Properties that must hold every round. Invariants fall into two classes:

HARD invariants: a violation immediately halts and reverts the current round. This does not conflict with complete_rounds_or_converge, which governs normal operation (no voluntary early exit except the exit conditions defined in loop_control); hard-failure halts are not voluntary exits.

RECOVERABLE conditions: handled per their governing policy without halting the round (e.g., an external critic missing is resolved via external_critic_fallback).

Hard invariants:
- full_document_input: each critic sees the full target.
- critic_isolation / no_cross_critic_visibility: critics run independently with no visibility into each other's output.
- fixes_after_synthesis_only: no fix is applied before synthesis and scoring complete.
- single_apply_agent: exactly one implementation subagent applies the changes each round; critics never edit, and no parallel apply-agents run, so concurrent edits are impossible.
- synthesis_must_complete: a round is not valid if synthesis is incomplete; halt and revert.
- architectural_reversal_not_auto_applied: if an architectural_reversal was auto-applied, halt and revert the round.
- both_externals_failed: if both external critics (gemini and openai) fail in the same round, abort the run as failed_loop and exit, rather than homogenizing to three Sonnet critics (see external_critic_fallback).

Recoverable conditions:
- external_critic_unavailable: resolved via external_critic_fallback; does not halt.

Operational invariants (govern normal execution, not failure handling):
- no_user_intervention: no questions to the user between rounds.
- complete_rounds_or_converge: run up to LOOPS rounds; exit early only on an exit condition defined in loop_control (convergence, stall, failed loop) or on a hard-failure halt. Do not exit early for any other reason. loop_control is the single source of truth for the exit conditions; do not restate them here.
- claude_subagent_models: per model_policy (critics on Sonnet; apply agent on APPLY_MODEL).

Per-round validation (all must be true):
- critic_count_per_round == 3
- synthesis_complete
- every finding has a normalized_score and an action
- eligible fixes filtered through fix_filter
- changes applied by exactly one implementation subagent
- no architectural_reversal was auto-applied
</invariants>

<architectural_reversal_policy>
Definition:
- Requires changing a core architecture decision
- Introduces an unplanned external dependency
- Changes a public API or interface contract
- Invalidates a locked design premise

Policy:
- apply: false
- stop_loop: false
- route_to: deferred_discussion
- surface: final_report_only
</architectural_reversal_policy>

<model_policy>
- Claude CRITIC subagents (the claude_adversarial critic and any fallback critic substituted for a failed external critic) run on Sonnet: claude-sonnet-4-6. Critique requires judgment; do not downgrade.
- The single implementation subagent runs on APPLY_MODEL (default "haiku", claude-haiku-4-5). Its change set is mechanical, so the default is the fast, cheap model; the user may upgrade via APPLY_MODEL.
- These choices are explicit and not inherited: pass the model when launching each Claude subagent, regardless of the orchestrator's model or any default subagent-model configuration.
- The external critics (gemini, openai) are exempt: they run via their own CLIs, unaffected by Claude model selection.
</model_policy>

<critic_protocol>
Shared input/output contract for all three critics.

Target and context:
- Each critic reviews the full TARGET under DOCUMENT_PATH. If DOCUMENT_PATH is a
  directory, that means every document in it; if a file, that file. The Claude
  critic reads it via its tools; the gemini and openai critics assemble it via Bash (below).
- If CONTEXT_PATHS is set, also take those paths as REFERENCE context, read-only:
  the authoritative design the target must conform to. Each CONTEXT_PATH may be a
  file or a directory. Critique ONLY the target; use the reference to judge
  consistency, completeness, and contradiction, and raise findings against the
  target where it contradicts or omits something the reference requires.
- When CONTEXT_PATHS is empty, each critic sees only the target (single-document
  isolation).

Prior findings:
- When PRIOR_FINDINGS is non-empty, each critic receives it as an "ALREADY_ADDRESSED" section in its prompt and must not re-raise a finding whose root cause and affected component match a PRIOR_FINDINGS entry, unless new evidence shows the prior fix was insufficient.

External payload assembly (shared by the gemini and openai critics):
- Path validation: every DOCUMENT_PATH and CONTEXT_PATH must be an absolute path; reject it before constructing any Bash command if it contains shell metacharacters or newlines.
- CONTEXT_PATHS is comma-separated; parse it with `IFS=',' read -ra CTX <<< "$CONTEXT_PATHS"` and cat each element quoted.
- Directory expansion (target or context path): `find "$P" -type f \( -name "*.md" -o -name "*.txt" \) -print0 | while IFS= read -r -d '' f; do echo "----- FILE: $f -----"; cat "$f"; done` so findings remain locatable per file.
- Timeout: 120s default; for payloads over 200KB, add roughly 30s per additional 100KB.

External critic prompt (shared): "Review the TARGET document(s) for findings, treating the REFERENCE CONTEXT (if present) as the authoritative design the target must be consistent with, raising findings against the target only, including where the target contradicts or omits something the reference requires. Critique only the provided text; do not call tools or read other files. Group findings by severity (critical, high, medium, low, info). For each finding include: title, severity, confidence (high/medium/low), impact dimensions, whether it requires an architectural reversal (true/false), evidence (location plus a quote of at most 40 words), and recommendation."

Output:
- Group findings by severity (critical, high, medium, low, info).
- Each finding conforms to critic_output_schema.
</critic_protocol>

<agents>
<critic id="gemini" mode="external">
- Runs via the external Gemini CLI; exempt from model_policy.
- Assemble the payload per critic_protocol's shared assembly rules (path validation, CONTEXT_PATHS parsing, directory expansion, timeout). When DOCUMENT_PATH is a file and CONTEXT_PATHS is set:
  `IFS=',' read -ra CTX <<< "$CONTEXT_PATHS"; { echo "===== TARGET (critique this) ====="; cat "$DOCUMENT_PATH"; echo "===== REFERENCE CONTEXT (read-only, do not critique) ====="; for p in "${CTX[@]}"; do cat "$p"; done; } | timeout 120s ~/.local/bin/agy --print "<prompt>"`
  When CONTEXT_PATHS is empty, include only the TARGET section.
- Prompt: the shared external critic prompt from critic_protocol.
- Return Gemini's response verbatim without summarizing or filtering.
- Artifact handling: some Gemini CLI variants return a prose summary inline and write the detailed findings to a local artifact file referenced in the response. If so, read that file and append its contents to the returned output BEFORE the external_critic_fallback usability check, so a valid review is not mistaken for a failure.
</critic>

<critic id="openai" mode="external">
- Runs via the external Codex CLI using the user's ChatGPT OAuth session; exempt from model_policy. Uses the user's codex default model (no -m override).
- Single-shell rule: mktemp, trap, the codex exec pipe, and the read of "$TMPFILE" must all run in ONE shell invocation (a split execution's EXIT trap deletes the output before the read, falsely triggering the fallback). Set `trap 'rm -f "$TMPFILE"' EXIT` immediately after mktemp; it guarantees cleanup on any exit path.
- Assemble the payload per critic_protocol's shared assembly rules and pipe it into codex exec as stdin (codex appends piped stdin as a <stdin> block). When DOCUMENT_PATH is a file and CONTEXT_PATHS is set:
  `TMPFILE=$(mktemp /tmp/triple_critic_openai_XXXXXX.txt); trap 'rm -f "$TMPFILE"' EXIT; IFS=',' read -ra CTX <<< "$CONTEXT_PATHS"; { echo "===== TARGET (critique this) ====="; cat "$DOCUMENT_PATH"; echo "===== REFERENCE CONTEXT (read-only, do not critique) ====="; for p in "${CTX[@]}"; do cat "$p"; done; } | timeout 120s codex exec --skip-git-repo-check -s read-only --ephemeral --color never -o "$TMPFILE" "<prompt>"; cat "$TMPFILE"`
  When CONTEXT_PATHS is empty, include only the TARGET section.
- Prompt: the shared external critic prompt from critic_protocol, plus this suffix: "Perform a balanced system-level critique across architecture, reliability, security, performance, scalability, and operability."
- Return the captured critique verbatim without summarizing or filtering.
</critic>

<critic id="claude_adversarial" mode="adversarial">
- Launch as a Claude subagent. Follow critic_protocol.
- Assume the design will fail. Challenge every mitigation until proven sufficient. Do not soften findings.
Focus:
- race_conditions
- concurrency_failure_modes
- security_bypass
- scale_failure
- hidden_assumptions
- production_week_one_failures
</critic>
</agents>

<external_critic_fallback>
- An external critic "fails to launch or returns no usable output" when the command exits non-zero, produces empty output, times out, OR returns output that does not contain at least one finding conforming to critic_output_schema. Malformed external-critic output is treated as no usable output and triggers the fallback.
- If exactly one external critic (gemini or openai) fails in a round, substitute a Claude subagent on the Sonnet model for that critic's task in that round.
- The fallback follows critic_protocol and takes the role of the critic it replaces: the openai fallback performs the balanced system-level critique (architecture, reliability, security, performance, scalability, operability); the gemini fallback performs a general severity-grouped critique.
- At most one external critic may fall back per round. If BOTH external critics (gemini and openai) fail in the same round, all three critics would be the same Sonnet model and the agreement signal would be artificial. Do not substitute both: abort the run, mark it failed_loop, and exit. Surface the failed_loop and its cause in the final report. (See the both_externals_failed hard invariant.)
- When at most one external critic falls back, the round still produces exactly three critic outputs and critic_count_per_round == 3 holds.
- Record each fallback substitution in round state and surface it in the final report.
</external_critic_fallback>

<critic_output_schema>
Required fields:
- finding_id
- title
- severity: critical | high | medium | low | info
- confidence: high | medium | low
- impact_dimensions: list
- architectural_reversal: true | false
- evidence: the location (section name or file) plus a quote of at most 40 words. Do not reproduce long passages; the orchestrator has the full document and needs a pointer, not a copy.
- recommendation
</critic_output_schema>

<scoring_model>
Severity scale:
- critical: 5
- high: 4
- medium: 3
- low: 2
- info: 1

Confidence scale:
- high: 1.0
- medium: 0.7
- low: 0.4

Agreement factor (the single lever for critic agreement; proportional to how many critics raised the finding):
- all_three_agree: 3
- two_agents_agree: 2
- one_agent: 1

Impact weights:
- correctness: 1.3
- security: 1.5
- reliability: 1.4
- scalability: 1.2
- operability: 1.1
- maintainability: 1.0
- clarity: 0.8

Formula inputs:
- severity_value
- confidence_value
- agreement_factor
- max_impact_weight

Formula:
- finding_score = severity_value * confidence_value * agreement_factor * max_impact_weight
- normalized_score = round(finding_score * 10, 1)

Scale:
- Scores are open-topped (no cap at 100). Agreement is applied exactly once, via agreement_factor; all critics weigh equally. Thresholds are absolute cutoffs on this open scale.

Priority thresholds:
- auto_fold_in: HIGH_THRESHOLD (default: 50)
- defer: LOW_THRESHOLD (default: 33)
- skip: 0
</scoring_model>

<deduplication>
Rules:
- Normalize finding titles by lowercasing, trimming whitespace, and stripping punctuation.
- Two findings are mergeable if and only if they share the same root cause AND the same affected component or section. Title or evidence similarity alone is not sufficient; both conditions must hold.
- Preserve all source critics on merged findings.
- Severity of a merged finding is automatically set to max(severities) of all merged findings; no manual judgment is required.
- Preserve the highest confidence unless merged evidence conflicts.
- Combine recommendations only when they are compatible.
- If recommendations conflict, preserve both recommendations in synthesis and route the conflict to deferred_discussion. Do not judge which recommendation is safer.
</deduplication>

<synthesis_model>
Agreement classes:
- all_three_agree: finding appears in all three critic outputs
- two_agents_agree: finding appears in any two critic outputs
- one_agent: finding appears in exactly one critic output

Rules:
- Merge duplicate findings before scoring.
- Preserve source attribution.
- Preserve disagreement and contradiction between critics.
- Do not drop unique findings.
</synthesis_model>

<action_rules>
Priority order:

1. If architectural_reversal == true:
   - action: defer
   - reason: architectural reversals are never auto-applied

2. If conflicting_recommendations == true (merged finding whose recommendations were preserved as conflicting per deduplication rules):
   - action: defer
   - reason: conflicting recommendations cannot be safely reduced to a single instruction for an implementation agent; defer for human resolution regardless of score

3. If normalized_score >= HIGH_THRESHOLD AND severity IN [critical, high, medium]:
   - action: fold_in
   - note: the severity condition mirrors fix_filter's gate; keep them in sync. Rejections are logged per fix_filter.

4. If normalized_score >= LOW_THRESHOLD:
   - action: defer

5. Default:
   - action: skip
</action_rules>

<fix_filter>
Eligible fixes must satisfy all conditions:
- action == fold_in
- severity IN [critical, high, medium]
- architectural_reversal == false

The severity and architectural_reversal conditions intentionally repeat action_rules guards (defense-in-depth). Any fold_in finding rejected here must be logged in round state (finding_id, fix_filter_rejection_reason) and surfaced in the final report's scoring_summary; silent drops are not permitted.
</fix_filter>

<round_execution>
<step_1_launch_critics>
- Launch all critics in parallel.
- If an external critic fails to launch or returns no usable output, apply external_critic_fallback IMMEDIATELY on detecting the failure, concurrently with any still-running critics; do not wait for all critics to finish before launching the fallback.
- Apply invariants.
</step_1_launch_critics>

<step_2_synthesize_findings>
- Synthesize per synthesis_model and deduplication; assign each merged finding its agreement class.
</step_2_synthesize_findings>

<step_3_score_findings>
- Apply scoring_model to every synthesized finding.
- Assign normalized_score to every finding.
- Assign action using action_rules.
</step_3_score_findings>

<step_4_filter_fixes>
- Apply fix_filter.
</step_4_filter_fixes>

<step_5_assemble_change_set>
- Assemble the ordered change set for the single implementation subagent. Each entry is MECHANICAL: { finding_id, file (if directory target), old_text (exact verbatim string to replace, unique in the file), new_text (exact verbatim replacement) }. The orchestrator writes the old/new strings itself from the synthesized recommendations; the apply agent performs replacements, it does not compose edits.
- There is no partitioning across agents and no parallel application: one implementation subagent applies the whole change set sequentially in step_6.
- Order the fixes bottom of the document first so earlier replacements cannot shift later match positions.
- If the change set is empty, skip step_6 entirely (do not launch an apply-agent or take a snapshot) and proceed to step_7. The round counts as applying zero fold_in fixes for loop_control's exit conditions.
</step_5_assemble_change_set>

<step_6_apply_fixes>
Snapshot: before launching the implementation subagent, the orchestrator snapshots the full target document content to a temp path (e.g., a mktemp file), so the round can be reverted. On any halt condition below, restore the snapshot by overwriting the target with the snapshot content, then delete the temp file.

- Launch a SINGLE implementation subagent as a Claude subagent (model APPLY_MODEL per model_policy), with clear context: the assembled change set from step_5 and the target path. Do not launch more than one apply-agent, and do not edit the document in the orchestrator yourself.
- The implementation subagent applies every fix sequentially as an exact string replacement: replace old_text with new_text verbatim. If an old_text does not match the current document exactly, SKIP that fix and report it as unmatched; do not improvise an alternative edit.
- The implementation subagent reports each fix applied and each fix skipped as unmatched. The orchestrator logs unmatched fixes in round state and surfaces them in the final report as unapplied.

Post-apply check (after the implementation subagent completes):
- Verify the document still parses structurally (well-formed XML if the document is XML-tagged; consistent heading structure if the document is Markdown).
- If structural parsing fails: halt the round, restore the snapshot to revert all changes from this step, record the failure in round state and the final report (run_outcome halted_on_invariant), and do not proceed to step_7.
- On success, delete the snapshot temp file.
</step_6_apply_fixes>

<step_7_update_state>
Round state lives in a file, not in the orchestrator's context. At run start, create it once: `STATE=$(mktemp /tmp/triple_critic_state_XXXXXX.json)`.

After each round, write to the state file:
- prior_findings (per the PRIOR_FINDINGS schema, including root_cause and affected_component)
- deferred_discussion
- applied_fixes (and any unmatched fixes from step_6)
- severity_curve
- scoring_log
- fallback substitutions and fix_filter rejections

Subsequent rounds read what they need from the state file (e.g., prior_findings for the ALREADY_ADDRESSED sections) instead of carrying full round detail forward in context. The final report is assembled from the state file; delete the file after the report is produced. Side effect: an interrupted run can be resumed from the state file.
</step_7_update_state>
</round_execution>

<loop_control>
- Repeat round_execution for up to LOOPS iterations.
- Convergence early-exit: after any round in which zero eligible fold_in fixes were applied AND no critical or high severity findings remain deferred, the document has converged. Stop the loop early and set the run outcome to converged_early.
- Stall exit: after any round in which zero eligible fold_in fixes were applied BUT one or more critical or high severity findings remain deferred (due to architectural_reversal, conflicting_recommendations, or any other deferral cause), stop the loop and set the run outcome to stalled_no_actionable_fixes. This is a stall, not convergence: high-severity issues remain unresolved but cannot be auto-applied.
- Failed-loop exit: if both external critics fail in a round (both_externals_failed), abort the run and set the run outcome to failed_loop. Edits applied in prior completed rounds are retained; the abort does not roll back earlier rounds, only the current round produces no changes.
- Do not ask the user questions between rounds.
- Do not stop when an architectural reversal is found.
- Surface deferred discussion items only in the final report.
</loop_control>

<final_report>
Required sections:
- run_outcome
- findings_by_severity
- findings_by_score
- applied_changes_by_round
- severity_curve
- scoring_summary
- architectural_reversals_deferred
- remaining_risks
- next_steps

Rules:
- run_outcome must state one of: completed_all_rounds, converged_early, stalled_no_actionable_fixes, halted_on_invariant, failed_loop. For converged_early: state the round convergence was detected. For stalled_no_actionable_fixes: state the round the stall was detected and list the deferred critical/high findings that blocked auto-application. For halted_on_invariant: state the round, the invariant violated, and whether the round was reverted. For failed_loop: state the round and which external critics failed.
- findings_by_severity must include severity, source critics, normalized score, action, and status.
- findings_by_score must sort findings by normalized_score descending.
- applied_changes_by_round must include round, finding ID, fix summary, and affected document section.
- severity_curve must include counts of critical, high, and medium findings per round.
- scoring_summary must include scoring distribution, highest-scoring findings, and skipped/deferred rationale.
- architectural_reversals_deferred must include every architectural reversal, why it was deferred, and the orchestrator's recommended direction.
- remaining_risks must include unresolved risks, deferred non-architectural findings, and low-confidence items.
- next_steps must provide ordered actions required before implementation begins.
</final_report>
