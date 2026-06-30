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
- Repeat for the configured number of rounds. Run all rounds to completion.
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
Number of review cycles to execute.
</input>

<input name="HIGH_THRESHOLD" required="false" default="50">
Score threshold at or above which a finding is eligible for automatic application (fold-in). The score scale is open-topped: high-severity findings with full critic agreement can exceed 100. Must be greater than LOW_THRESHOLD.
</input>

<input name="LOW_THRESHOLD" required="false" default="33">
Score threshold at or above which a finding is deferred for discussion. Findings below this threshold are skipped.
</input>

<input name="PRIOR_FINDINGS" required="false">
Cumulative list of findings addressed in prior rounds. Each entry must conform to the following minimal schema (matching the essentials of critic_output_schema):
- finding_id: unique identifier for the finding (string)
- title: short descriptive title (string)
- severity: critical | high | medium | low | info
- action: the action taken (fold_in | defer | skip)
- status: resolution status (applied | deferred | skipped)
</input>
</inputs>

<invariants>
Properties that must hold every round. Invariants fall into two classes:

HARD invariants: a violation immediately halts and reverts the current round. This does not conflict with complete_rounds_or_converge, which governs normal operation (no voluntary early exit except convergence); hard-failure halts are not voluntary exits.

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
- complete_rounds_or_converge: run up to LOOPS rounds; exit early only on convergence (a round that applies zero eligible fold_in fixes) or on a hard-failure halt. Do not exit early for any other reason.
- claude_subagents_run_on_sonnet: per model_policy.

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
- Launch every Claude subagent in this skill on the Sonnet model: claude-sonnet-4-6. This covers the claude_adversarial critic, the single implementation subagent that applies changes, and any Sonnet fallback critic substituted for a failed external critic (see external_critic_fallback).
- This is explicit and not inherited: pass model "sonnet" (claude-sonnet-4-6) when launching each Claude subagent, regardless of the orchestrator's model or any default subagent-model configuration.
- The external critics (gemini, openai) are exempt: gemini runs via the Gemini CLI and openai via the Codex CLI, unaffected by Claude model selection.
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

Output:
- Group findings by severity (critical, high, medium, low, info).
- Each finding conforms to critic_output_schema.
</critic_protocol>

<agents>
<critic id="gemini" mode="external">
- Runs via the external Gemini CLI; exempt from model_policy.
- Path validation (shared by both external critics): every DOCUMENT_PATH and CONTEXT_PATH must be an absolute path and must be rejected before any Bash command is constructed if it contains shell metacharacters or newlines.
- Assemble the payload with Bash per critic_protocol: the TARGET content, then (if
  CONTEXT_PATHS is set) the REFERENCE content, with a clear separator so Gemini
  critiques only the target. When DOCUMENT_PATH is a file and CONTEXT_PATHS is set:
  `{ echo "===== TARGET (critique this) ====="; cat "$DOCUMENT_PATH"; echo "===== REFERENCE CONTEXT (read-only, do not critique) ====="; for p in "${CONTEXT_PATHS[@]}"; do cat "$p"; done; } | timeout 120s ~/.local/bin/agy --print "<prompt>"`
  When DOCUMENT_PATH is a directory, expand the target with `find "$DOCUMENT_PATH" -type f \( -name "*.md" -o -name "*.txt" \) -print0 | xargs -0 cat`. Expand directory CONTEXT_PATHs the same way. When CONTEXT_PATHS is empty, include only the TARGET section.
- Prompt: "Review the TARGET document(s) for findings, treating the REFERENCE CONTEXT (if present) as the authoritative design the target must be consistent with, raising findings against the target only, including where the target contradicts or omits something the reference requires. Critique only the provided text; do not call tools or read other files. Group findings by severity (critical, high, medium, low, info). For each finding include: title, severity, confidence (high/medium/low), impact dimensions, whether it requires an architectural reversal (true/false), evidence, and recommendation."
- Return Gemini's response verbatim without summarizing or filtering.
</critic>

<critic id="openai" mode="external">
- Runs via the external Codex CLI using the user's ChatGPT OAuth session; exempt from model_policy. Uses the user's codex default model (no -m override).
- Path validation: see the shared note in the gemini critic above.
- The orchestrator generates a fresh TMPFILE per critic invocation: `TMPFILE=$(mktemp /tmp/triple_critic_openai_XXXXXX.txt); trap 'rm -f "$TMPFILE"' EXIT; chmod 600 "$TMPFILE"`
- Assemble the payload with Bash per critic_protocol: the TARGET content, then (if
  CONTEXT_PATHS is set) the REFERENCE content, with a clear separator so the critic
  critiques only the target, and pipe it into codex exec as stdin (codex appends
  piped stdin as a <stdin> block). When DOCUMENT_PATH is a file and CONTEXT_PATHS is set:
  `{ echo "===== TARGET (critique this) ====="; cat "$DOCUMENT_PATH"; echo "===== REFERENCE CONTEXT (read-only, do not critique) ====="; for p in "${CONTEXT_PATHS[@]}"; do cat "$p"; done; } | timeout 120s codex exec --skip-git-repo-check -s read-only --ephemeral --color never -o "$TMPFILE" "<prompt>"`
  When DOCUMENT_PATH is a directory, expand the target with `find "$DOCUMENT_PATH" -type f \( -name "*.md" -o -name "*.txt" \) -print0 | xargs -0 cat`. Expand directory CONTEXT_PATHs the same way. When CONTEXT_PATHS is empty, include only the TARGET section.
- Prompt: "Review the TARGET document(s) for findings, treating the REFERENCE CONTEXT (if present) as the authoritative design the target must be consistent with, raising findings against the target only, including where the target contradicts or omits something the reference requires. Critique only the provided text; do not call tools or read other files. Perform a balanced system-level critique across architecture, reliability, security, performance, scalability, and operability. Group findings by severity (critical, high, medium, low, info). For each finding include: title, severity, confidence (high/medium/low), impact dimensions, whether it requires an architectural reversal (true/false), evidence, and recommendation."
- Read "$TMPFILE" and return its contents verbatim without summarizing or filtering, then delete "$TMPFILE".
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
- evidence
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
- Scores are open-topped, not capped at 100. Critic agreement is the single priority lever, applied once via agreement_factor (1, 2, or 3 for one, two, or three agreeing critics). A high-severity finding all three critics agree on can therefore exceed 100, ranking above lesser findings instead of flattening to a shared ceiling. There is no separate critic-weight term: all critics are weighted equally, so agreement_factor alone carries critic count.
- Thresholds (HIGH_THRESHOLD, LOW_THRESHOLD) are absolute cutoffs on this open scale.

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
   - note: fix_filter is the single enforcement gate. The severity condition here mirrors fix_filter's severity gate; both must stay in sync. Any finding assigned fold_in that fix_filter subsequently rejects must be logged with an explicit rejection reason in round state and surfaced in the final report.

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

Defense-in-depth note: the severity and architectural_reversal conditions above repeat guards already present in action_rules (rules 1 and 2). They are intentional defense-in-depth checks, not redundant dead code. If any finding assigned action=fold_in is rejected here, the orchestrator must log the rejection in round state with: finding_id, fix_filter_rejection_reason. That rejection must also be surfaced in the final report's scoring_summary under skipped/deferred rationale. Silent drops are not permitted.
</fix_filter>

<round_execution>
<step_1_launch_critics>
- Launch all critics in parallel.
- If an external critic fails to launch or returns no usable output, apply external_critic_fallback.
- Apply invariants.
</step_1_launch_critics>

<step_2_synthesize_findings>
Grouping:
- all_three_agree
- two_agents_agree
- one_agent

Instructions:
- Apply deduplication rules.
- Preserve source attribution.
- Preserve disagreement and contradiction between critics.
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
- Assemble the ordered change set for the single implementation subagent: the list of eligible fixes, each with finding_id, the exact change to make, where it applies, and the recommended edit.
- There is no partitioning across agents and no parallel application: one implementation subagent applies the whole change set sequentially in step_6.
- Order the fixes so they apply without coordinate drift (for example, bottom of the document first), or instruct the apply-agent to re-locate each fix by content match immediately before editing.
</step_5_assemble_change_set>

<step_6_apply_fixes>
Snapshot: before launching the implementation subagent, the orchestrator snapshots the full target document content to a temp path (e.g., a mktemp file), so the round can be reverted. On any halt condition below, restore the snapshot by overwriting the target with the snapshot content, then delete the temp file.

- Launch a SINGLE implementation subagent as a Claude subagent (model per model_policy), with clear context: the assembled change set from step_5 and the target path. Do not launch more than one apply-agent, and do not edit the document in the orchestrator yourself.
- The implementation subagent applies every fix in the change set sequentially, re-reading the affected region before each edit so each edit is made against the current document state, not a stale view.
- The implementation subagent reports each fix applied and where.

Post-apply check (after the implementation subagent completes):
- Verify the document still parses structurally (well-formed XML if the document is XML-tagged; consistent heading structure if the document is Markdown).
- If structural parsing fails: halt the round, restore the snapshot to revert all changes from this step, record the failure in round state and the final report (run_outcome halted_on_invariant), and do not proceed to step_7.
- On success, delete the snapshot temp file.
</step_6_apply_fixes>

<step_7_update_state>
State updates:
- prior_findings
- deferred_discussion
- applied_fixes
- severity_curve
- scoring_log
</step_7_update_state>
</round_execution>

<loop_control>
- Repeat round_execution for up to LOOPS iterations.
- Convergence early-exit: after any round in which zero eligible fold_in fixes were applied AND no critical or high severity findings remain deferred, the document has converged. Stop the loop early and set the run outcome to converged_early.
- Stall exit: after any round in which zero eligible fold_in fixes were applied BUT one or more critical or high severity findings remain deferred (due to architectural_reversal, conflicting_recommendations, or any other deferral cause), stop the loop and set the run outcome to stalled_no_actionable_fixes. This is a stall, not convergence: high-severity issues remain unresolved but cannot be auto-applied.
- Failed-loop exit: if both external critics fail in a round (both_externals_failed), abort the run and set the run outcome to failed_loop.
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
