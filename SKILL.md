---
name: triple-critic-loop
description: "Orchestrates a scored triple-critic design review. Launches three independent critics (Gemini, OpenAI, Claude adversarial), synthesizes and scores findings, applies eligible fixes, and repeats for the configured number of rounds. Returns a final report with severity curve, scoring summary, and deferred architectural reversals. Data handling: documents under review are sent to external CLIs (Gemini, OpenAI/Codex); do not run this skill on documents containing credentials, PII, or data governed by residency requirements."
disable-model-invocation: false
---

<role_definition>
- You are the orchestrator of a scored triple-critic design review workflow.
- You launch subagents to execute the work rather than doing it yourself in order to preserve your context window.
- You launch three independent critics, synthesize and score findings, launch implementation agents to apply eligible fixes, and repeat for the configured number of rounds.
- Run all rounds to completion.
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

HARD invariants: a violation immediately halts and reverts the current round. This does not conflict with complete_all_configured_rounds, which governs normal operation (no voluntary early exit); hard-failure halts are not voluntary exits.

RECOVERABLE conditions: handled per their governing policy without halting the round (e.g., an external critic missing is resolved via external_critic_fallback).

Hard invariants:
- full_document_input: each critic sees the full target.
- critic_isolation / no_cross_critic_visibility: critics run independently with no visibility into each other's output.
- fixes_after_synthesis_only: no fix is applied before synthesis and scoring complete.
- no_overlapping_edits: no two implementation_agents edit the same document section.
- synthesis_must_complete: a round is not valid if synthesis is incomplete; halt and revert.
- architectural_reversal_not_auto_applied: if an architectural_reversal was auto-applied, halt and revert the round.

Recoverable conditions:
- external_critic_unavailable: resolved via external_critic_fallback; does not halt.

Operational invariants (govern normal execution, not failure handling):
- no_user_intervention: no questions to the user between rounds.
- complete_all_configured_rounds: run every configured round; do not early-exit.
- claude_subagents_run_on_sonnet: per model_policy.

Per-round validation (all must be true):
- critic_count_per_round == 3
- synthesis_complete
- every finding has a normalized_score and an action
- eligible fixes filtered through fix_filter
- no overlapping edit scopes
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
- Launch every Claude subagent in this skill on the Sonnet model: claude-sonnet-4-6. This covers the claude_adversarial critic, all implementation_agents, and any Sonnet fallback critic substituted for a failed external critic (see external_critic_fallback).
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
- Assemble the payload with Bash per critic_protocol: the TARGET content, then (if
  CONTEXT_PATHS is set) the REFERENCE content, with a clear separator so Gemini
  critiques only the target. When DOCUMENT_PATH is a file and CONTEXT_PATHS is set:
  `{ echo "===== TARGET (critique this) ====="; cat "$DOCUMENT_PATH"; echo "===== REFERENCE CONTEXT (read-only, do not critique) ====="; cat {each CONTEXT_PATH}; } | timeout 120s ~/.local/bin/agy --print "<prompt>"`
  When DOCUMENT_PATH is a directory, expand the target with `find "$DOCUMENT_PATH" -type f \( -name '*.md' -o -name '*.txt' \) -print -exec cat {} \;`. Expand directory CONTEXT_PATHs the same way. When CONTEXT_PATHS is empty, include only the TARGET section. DOCUMENT_PATH must be quoted when interpolated into the Bash command.
- Prompt: "Review the TARGET document(s) for findings, treating the REFERENCE CONTEXT (if present) as the authoritative design the target must be consistent with, raising findings against the target only, including where the target contradicts or omits something the reference requires. Critique only the provided text; do not call tools or read other files. Group findings by severity (critical, high, medium, low, info). For each finding include: title, severity, confidence (high/medium/low), impact dimensions, whether it requires an architectural reversal (true/false), evidence, and recommendation."
- Return Gemini's response verbatim without summarizing or filtering.
</critic>

<critic id="openai" mode="external">
- Runs via the external Codex CLI using the user's ChatGPT OAuth session; exempt from model_policy. Uses the user's codex default model (no -m override).
- The orchestrator generates a fresh TMPFILE per critic invocation: `TMPFILE=$(mktemp /tmp/triple_critic_openai_XXXXXX.txt)`
- Assemble the payload with Bash per critic_protocol: the TARGET content, then (if
  CONTEXT_PATHS is set) the REFERENCE content, with a clear separator so the critic
  critiques only the target, and pipe it into codex exec as stdin (codex appends
  piped stdin as a <stdin> block). When DOCUMENT_PATH is a file and CONTEXT_PATHS is set:
  `TMPFILE=$(mktemp /tmp/triple_critic_openai_XXXXXX.txt); { echo "===== TARGET (critique this) ====="; cat {DOCUMENT_PATH}; echo "===== REFERENCE CONTEXT (read-only, do not critique) ====="; cat {each CONTEXT_PATH}; } | timeout 120s codex exec --skip-git-repo-check -s read-only --ephemeral --color never -o "$TMPFILE" "<prompt>"`
  When DOCUMENT_PATH is a directory, expand the target with `find {DOCUMENT_PATH} -type f \( -name '*.md' -o -name '*.txt' \) -print -exec cat {} \;`. Expand directory CONTEXT_PATHs the same way. When CONTEXT_PATHS is empty, include only the TARGET section.
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
- If an external critic (gemini or openai) fails to launch or returns no usable output in a round, substitute a Claude subagent on the Sonnet model for that critic's task in that round.
- The fallback follows critic_protocol and takes the role of the critic it replaces: the openai fallback performs the balanced system-level critique (architecture, reliability, security, performance, scalability, operability); the gemini fallback performs a general severity-grouped critique.
- The round still produces exactly three critic outputs; critic_count_per_round == 3 holds.
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

Critic weights:
- gemini: 1.0
- openai: 1.0
- claude_adversarial: 1.0

Agreement multipliers:
- all_three_agree: 1.5
- two_agents_agree: 1.25
- one_agent: 1.0

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
- critic_weight_sum
- agreement_multiplier
- max_impact_weight

Formula:
- finding_score = severity_value * confidence_value * critic_weight_sum * agreement_multiplier * max_impact_weight
- normalized_score = round(finding_score * 10, 1)

Scale:
- Scores are open-topped, not capped at 100. Critic agreement is counted twice by design: additively in critic_weight_sum (the sum grows with each agreeing critic) and multiplicatively in agreement_multiplier. A high-severity finding all three critics agree on can therefore exceed 100, reflecting compounded criticality, and ranks above lesser findings instead of flattening to a shared ceiling.
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

2. If normalized_score >= HIGH_THRESHOLD AND severity IN [critical, high, medium]:
   - action: fold_in
   - note: fix_filter is the single enforcement gate. The severity condition here mirrors fix_filter's severity gate; both must stay in sync. Any finding assigned fold_in that fix_filter subsequently rejects must be logged with an explicit rejection reason in round state and surfaced in the final report.

3. If normalized_score >= LOW_THRESHOLD:
   - action: defer

4. Default:
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

<step_5_partition_fixes>
Definition of "section": for a Markdown or XML-tagged document, a section is the content between two sibling anchors (a heading or top-level tag) at the same or higher level. For a Markdown document, sibling anchors are headings at the same heading depth; the section runs from one heading to the line before the next heading at equal or lesser depth. For an XML-tagged document, a section is a top-level element including its open and close tags.

Partitioning rules:
- Assign each eligible fix (by finding_id) to a line range: { finding_id, start_line, end_line } where start_line and end_line are 1-based line numbers in the target document at the time of partitioning.
- The invariant: no two line ranges may overlap. Ranges [a, b] and [c, d] overlap if a <= d AND c <= b.
- If a clean non-overlapping partition cannot be guaranteed (e.g., two fixes target the same section), serialize those fixes to a single implementation_agent that applies them sequentially rather than attempting parallel application.
- Output the full mapping of finding_id to line range before launching any implementation_agent.
</step_5_partition_fixes>

<step_6_apply_fixes>
- Launch every implementation_agent as a Claude subagent (model per model_policy).
- Apply eligible fixes in parallel implementation_agents, each restricted to its assigned line range from step_5_partition_fixes.
- Each implementation_agent must report each fix changed and where.

Post-apply check (run after all implementation_agents complete):
- Verify that no two agents modified overlapping line ranges by comparing each agent's reported change ranges against the partition from step_5.
- Verify that the document still parses structurally (well-formed XML if the document is XML-tagged; valid heading hierarchy if the document is Markdown).
- If overlap is detected or structural parsing fails: halt the round, revert all changes applied in this step, and record the failure in round state and the final report. Do not proceed to step_7.
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
- Repeat round_execution for LOOPS iterations.
- Do not ask the user questions between rounds.
- Do not stop when an architectural reversal is found.
- Surface deferred discussion items only in the final report.
</loop_control>

<final_report>
Required sections:
- findings_by_severity
- findings_by_score
- applied_changes_by_round
- severity_curve
- scoring_summary
- architectural_reversals_deferred
- remaining_risks
- next_steps

Rules:
- findings_by_severity must include severity, source critics, normalized score, action, and status.
- findings_by_score must sort findings by normalized_score descending.
- applied_changes_by_round must include round, finding ID, fix summary, and affected document section.
- severity_curve must include counts of critical, high, and medium findings per round.
- scoring_summary must include scoring distribution, highest-scoring findings, and skipped/deferred rationale.
- architectural_reversals_deferred must include every architectural reversal, why it was deferred, and the orchestrator's recommended direction.
- remaining_risks must include unresolved risks, deferred non-architectural findings, and low-confidence items.
- next_steps must provide ordered actions required before implementation begins.
</final_report>
