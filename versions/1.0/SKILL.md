---
name: triple-critic-loop
description: Orchestrates a scored triple-critic design review. Launches three independent critics (Gemini, Claude balanced, Claude adversarial), synthesizes and scores findings, applies eligible fixes, and repeats for the configured number of rounds. Returns a final report with severity curve, scoring summary, and deferred architectural reversals.
disable-model-invocation: false
---

<role_definition>
- You are the orchestrator of a scored triple-critic design review workflow.
- You launch subagents to execute the work rather than doing it yourself in order to preserve your context window.
- You launch three independent critics, synthesize and score findings, launch implementation agents to apply eligible fixes, and repeat for the configured number of rounds.
- Run all rounds to completion.
- Do not stop mid-loop for architectural reversals.
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
Normalized score threshold (0-100) at or above which a finding is eligible for automatic application (fold-in). Must be greater than LOW_THRESHOLD.
</input>

<input name="LOW_THRESHOLD" required="false" default="33">
Normalized score threshold (0-100) at or above which a finding is deferred for discussion. Findings below this threshold are skipped.
</input>

<input name="PRIOR_FINDINGS" required="false">
Cumulative list of findings addressed in prior rounds.
</input>
</inputs>

<invariants>
- full_document_input: true
- critic_isolation: true
- no_cross_critic_visibility: true
- fixes_after_synthesis_only: true
- no_overlapping_edits: true
- no_user_intervention: true
- complete_all_configured_rounds: true
- claude_subagents_run_on_sonnet: true
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
- Launch every Claude subagent in this skill (both Claude critics and all implementation_agents) on the Sonnet model: claude-sonnet-4-6.
- This is explicit and not inherited: pass model "sonnet" (claude-sonnet-4-6) when launching each Claude subagent, regardless of the orchestrator's model or any default subagent-model configuration.
- The gemini critic is exempt: it runs via the external Gemini CLI and is unaffected by Claude model selection.
</model_policy>

<agents>
<critic id="gemini" mode="external">
Instructions:
- Read the full document under review. If DOCUMENT_PATH is a directory, read every
  document in it; if it is a file, read that file.
- Assemble the payload: the TARGET content (the document(s) under DOCUMENT_PATH),
  then, if CONTEXT_PATHS is set, the REFERENCE content from those paths, with a
  clear separator between the two sections so Gemini critiques only the target.
  Build it with Bash, e.g. when DOCUMENT_PATH is a file and CONTEXT_PATHS is set:
  `{ echo "===== TARGET (critique this) ====="; cat {DOCUMENT_PATH}; echo "===== REFERENCE CONTEXT (read-only, do not critique) ====="; cat {each CONTEXT_PATH}; } | ~/.local/bin/agy --print "<prompt>"`
  When DOCUMENT_PATH is a directory, expand the target with e.g. `find {DOCUMENT_PATH} -type f \( -name '*.md' -o -name '*.txt' \) -print -exec cat {} \;` so each target file's path and content are included. Each CONTEXT_PATH may itself be a file (cat it) or a directory (expand it with the same find pattern). When CONTEXT_PATHS is empty, include only the TARGET section (unchanged behavior).
- Prompt: "Review the TARGET document(s) for findings, treating the REFERENCE CONTEXT (if present) as the authoritative design the target must be consistent with — raise findings against the target only, including where the target contradicts or omits something the reference requires. Group findings by severity (critical, high, medium, low, info). For each finding include: title, severity, confidence (high/medium/low), impact dimensions, whether it requires an architectural reversal (true/false), evidence, and recommendation."
- Return Gemini's response verbatim without summarizing or filtering.
</critic>

<critic id="claude_balanced" mode="balanced">
Instructions:
- Launch as a Claude subagent on the Sonnet model (model "sonnet", claude-sonnet-4-6).
- Read the full document under review (every file if DOCUMENT_PATH is a directory).
- If CONTEXT_PATHS is set, also read those reference documents read-only as the
  authoritative design context the target must conform to; critique ONLY the
  target, but use the context to judge consistency, completeness, and contradiction.
- Perform a balanced system-level critique.
- Return findings grouped by topic and severity.

Focus:
- architecture
- reliability
- security
- performance
- scalability
- operability
</critic>

<critic id="claude_adversarial" mode="adversarial">
Instructions:
- Launch as a Claude subagent on the Sonnet model (model "sonnet", claude-sonnet-4-6).
- Read the full document under review (every file if DOCUMENT_PATH is a directory).
- If CONTEXT_PATHS is set, also read those reference documents read-only as the
  authoritative design context; critique ONLY the target, but use the context to
  attack inconsistencies, unmet contracts, and assumptions the target makes about
  the rest of the system.
- Assume the design will fail.
- Challenge every mitigation until proven sufficient.
- Do not soften findings.

Focus:
- race_conditions
- concurrency_failure_modes
- security_bypass
- scale_failure
- hidden_assumptions
- production_week_one_failures
</critic>
</agents>

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
- gemini: 1.1
- claude_balanced: 1.0
- claude_adversarial: 1.2

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
- normalized_score = min(100, round(finding_score * 10, 1))

Priority thresholds:
- auto_fold_in: HIGH_THRESHOLD (default: 50)
- defer: LOW_THRESHOLD (default: 33)
- skip: 0
</scoring_model>

<deduplication>
Rules:
- Normalize finding titles by lowercasing, trimming whitespace, and stripping punctuation.
- Merge findings when titles or evidence are semantically equivalent.
- Preserve all source critics on merged findings.
- Preserve the strongest severity unless evidence supports a downgrade.
- Preserve the highest confidence unless merged evidence conflicts.
- Combine recommendations only when they are compatible.
- If recommendations conflict, preserve the conflict in synthesis and route unresolved conflict to deferred_discussion unless one resolution is clearly safer.
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

<decision_pipeline>
1. Synthesize and deduplicate critic findings.
2. Assign agreement class.
3. Score every finding.
4. Assign action using action_rules.
5. Filter eligible fixes using fix_filter.
6. Partition eligible fixes into non-overlapping edit scopes.
7. Apply eligible fixes through implementation_agents.
8. Update state.
9. Continue to the next round until LOOPS is complete.
</decision_pipeline>

<action_rules>
Priority order:

1. If architectural_reversal == true:
   - action: defer
   - reason: architectural reversals are never auto-applied

2. If normalized_score >= HIGH_THRESHOLD AND severity IN [critical, high, medium]:
   - action: fold_in

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
</fix_filter>

<round_execution>
<step_1_launch_critics>
- Launch all critics in parallel.
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
- Architectural reversals must always be assigned action=defer.
</step_3_score_findings>

<step_4_filter_fixes>
- Apply fix_filter.
</step_4_filter_fixes>

<step_5_partition_fixes>
- Partition fixes into balanced non-overlapping edit scopes.
- No two implementation_agents may edit the same document section.
</step_5_partition_fixes>

<step_6_apply_fixes>
- Launch every implementation_agent as a Claude subagent on the Sonnet model (model "sonnet", claude-sonnet-4-6).
- Apply eligible fixes in parallel implementation_agents.
- Each implementation_agent must report each fix changed and where.
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

<validation>
Required per round:
- critic_outputs == 3
- synthesis_complete == true
- findings_count >= 0
- every_finding_has_score == true
- every_finding_has_action == true
- eligible_fixes_filtered == true
- overlapping_edit_scopes == false
- architectural_reversal_applied == false

Reject if:
- architectural_reversal_applied == true
- loop_stopped_for_architectural_reversal == true
- critic_count_per_round != 3
- any_finding_missing_score == true
- any_finding_missing_action == true
- overlapping_edit_scopes == true
</validation>

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
