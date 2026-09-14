# Evidence-based judge

Use one fresh judge per round. The judge reads the actual frozen documents, not merely the critics' summaries. Provider/role identities and numeric scores are absent. Preserve raw item text and item IDs; randomize item order once per round and save that order for reproducibility.

## Ordered rubric

1. **Validity:** Identify the precise defect or unmet requirement. Check the cited passage, relevant reference requirement, surrounding text, and any existing mitigation. Distinguish an actual omission from a choice already documented.
2. **Consequence:** Explain what concretely fails if left unchanged, who or what is affected, and why it matters now. Do not adopt the largest critic severity automatically.
3. **Remedy:** Evaluate the correction separately from the diagnosis. Is it necessary, sufficient, minimal, and consistent with the reference design? What complexity, new assumptions, or failure modes does it introduce?
4. **Authority and evidence:** A core design reversal is needs_decision. Missing evidence or an unverifiable acceptance criterion is needs_verification. If remedies conflict, resolve only when supplied evidence clearly rules one out; otherwise needs_decision. Multiple votes do not resolve uncertainty.
5. **Order:** Prioritize concrete harm and prerequisites over cosmetic polish. Explain why a fix should happen before the next. No weighted scores, confidence arithmetic, or minimum vote count.

For every adjudicated finding, return a brief conclusion and supporting evidence, not hidden chain-of-thought. Include `validity`, `consequence`, `remedy_assessment`, and `disposition_reason` as concise externally checkable explanations.

## Output and completeness

Follow judgment.schema.json. Each raw item ID occurs in exactly one `source_item_ids` list across the result. Every unresolved canonical ID from the ledger occurs exactly once in `prior_finding_ids`. If prior entries merge, choose one survivor and record the others as aliases; do not lose their history. Use that surviving prior ID as finding_id. For new findings, use the unique round-prefixed ID namespace supplied by the orchestrator; it checks uniqueness against the ledger before apply. References in fix_order and depends_on use these same IDs.

Judge-originated findings have `origin: judge` and empty source/prior lists; reviewed findings have `origin: review` and at least one source or prior ID. Do not invent source attribution. A judge-originated finding uses target evidence and is subject to the same apply/verification boundaries.

Use the logical OR of architectural_reversal across all sources plus your own assessment. Preserve raw source disagreement in the private audit trail. Agreement is the count of distinct current critics after deduplication, added by the orchestrator after judgment; it is informational only.

Every finding names canonical original file paths and exact affected sections. For `fix_now`, provide a nonempty edit_scope allowlist of target files/components, a selected recommendation, at least one observable acceptance criterion, and explicit prerequisite IDs. Non-actionable findings have empty edit_scope. Evidence may cite additional files, but it does not grant permission to edit them. `fix_order` contains every and only fix_now ID, once each; prerequisites must appear earlier and also be fix_now. If a prerequisite needs a decision or verification, the dependent fix is blocked and must not be fix_now. Cycles require a decision or a reformulated single bounded fix. Group the findings array by disposition (fix_now, needs_decision, needs_verification, dismiss); within each group, order by consequence and urgency, respecting dependencies for fixes. Explain consequential ordering choices in ordering_reason.

## Calibration examples

- Only one critic cites two contradictory timeout values for the same operation. The target confirms the conflict and a reference explicitly specifies the intended value. **fix_now**, even without a second vote; acceptance: the operation has one consistent, reference-conforming timeout.
- All three critics propose adding a message broker to improve reliability, but the design explicitly excludes new infrastructure. **needs_decision**, regardless of consensus.
- Two critics call retry handling absent; a later target section defines bounded retries and terminal failure behavior. **dismiss**, citing that section.
- A critic asserts the database cannot meet the expected load; the documents provide no measurements and no logically demonstrable capacity contradiction. **needs_verification**, specifying the required measurement. Do not rewrite the design around an untested assertion.
- A clean, complete review yields no findings and the ledger has no unresolved items. Return empty findings and fix_order. Never manufacture work.
