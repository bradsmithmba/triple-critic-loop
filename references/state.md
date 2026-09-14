# v2 state and recovery

State is retained as an audit trail. It contains document copies and model output; keep it private. `/tmp` is not durable storage: a deleted state directory cannot be resumed. Users needing durable recovery may retain a copy outside target/reference trees.

## Artifacts

`run.json`: schema_version "2.0", run ID, canonical target/reference manifests and hashes, effective inputs/models, current round, and terminal outcome if any. Validate immutable input/configuration equality on resume. Do not accept v1 state or silently change models/configuration within a resumed run.

`ledger.json`: canonical IDs, aliases, status/disposition, evidence, remedy/acceptance criteria, occurrence/source history, first/last seen round, and verification history. Keep a ledger-before and ledger-after copy per round; commit ledger-after only with that round's successful commit.

Each `round_N/` contains:
- `phase.json`: last fully completed phase and relevant artifact hashes.
- `snapshot/target/` and `snapshot/context/`: immutable pre-review copies with a mapping to original paths, byte hashes, and manifest.
- `work/`: private target working copy. The apply agent only authors edits here; original-path findings map through the manifest. The orchestrator may initialize/reset the copy, but no other agent authors changes.
- critic input payloads, Gemini/OpenAI/Claude JSON, external protocol events and stderr, plus `notes.json` for retries/fallbacks/halts.
- `judge-input.json` and private `attribution.json`: anonymized item IDs and their source mapping, plus saved shuffled order.
- `judgment.json`, `apply.json`, `applied.diff`, `verification.json`, and ledger-before/after files.
- `commit.json`: per-file original, pre-hash, verified post-hash, publication status, and the intended ledger-after hash.

All JSON writes use a temporary sibling file followed by atomic rename. A phase marker follows validation of its complete artifacts, never precedes it. A no-edit round still writes empty apply/verification results and a zero diff, then commits its ledger update.

## Phases

`prepared → critics_complete → judged → applied → verified → committed`

The marker names the last completed phase. `prepared` means frozen input and work copy exist; `judged` means validated judgment exists; `applied` means apply results and scope-checked diff exist; `verified` means the entire applied patch passed independent verification; `committed` means published target hashes and ledger-after match the journal. Terminal outcome is stored separately.

Before publication, compare every original target and reference hash/file set with its pre-round manifest. On unexpected changes, halt without overwriting them. Journal intended verified post-hashes before modifying originals. For each changed target file, use a temporary sibling and atomic replacement, retaining metadata such as permissions; record publication. Recheck references and resulting targets before marking committed. Multi-file publication is not atomic; the journal makes it recoverable.

## Resume

- A terminal run returns its saved report; it does not silently restart. Resume validates the run manifest, phase, and artifact hashes first.
- `prepared`: rerun incomplete critics; retain valid completed output from the same frozen snapshot.
- `critics_complete`: run the judge.
- `judged`: if an interrupted apply may have altered work, rebuild work from snapshot and rerun apply. Originals must still match pre-hashes.
- `applied`: validate scope/hashes, then run a fresh verifier. Do not reapply.
- `verified`: inspect commit journal before publishing. An original matching pre-hash still needs publication; one matching verified post-hash is already published, even if the status write was interrupted. Anything else is an external edit: halt without overwriting it.
- `committed`: restore/check the matching ledger-after, evaluate termination, and only then start the next round. Do not skip termination evaluation after a crash.

On verification/scope failure before publication, discard/reset work and retain originals. On a failed partial publication, restore a published file only if its current hash still equals this round's post-hash; preserve and report unexpected content. Record any files whose restoration could not safely complete, and never claim a full rollback in that case. Cancel active workers before recovery; never start two writers for one run.
