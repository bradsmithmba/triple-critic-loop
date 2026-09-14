# triple-critic-loop v2.0

Three independent critics find problems. An evidence-based LLM judge decides which findings hold up and orders bounded fixes. One apply agent makes those changes in a private copy, and a fresh verifier checks the result before it reaches your document.

I built the original loop to stop manually copying documents between models and reconciling their reviews. V2 keeps those independent perspectives and replaces weighted scoring and minimum vote counts with explicit judgment against the actual document.

## What changed in v2

- **No scores or thresholds.** The judge assigns `fix_now`, `needs_decision`, `needs_verification`, or `dismiss`, with evidence-linked reasons and an ordered fix list.
- **Single-critic discoveries can lead to fixes.** The judge must establish the defect and assess the remedy independently. Agreement is recorded for audit, not used as a gate.
- **Anonymized judgment.** Provider and role identities are withheld; the judge gets the complete frozen target and reference documents.
- **Verification after every apply, including the last round.** Fixes need observable acceptance criteria. Failed or uncertain verification discards the round's patch; earlier verified rounds stand.
- **Clean reviews are valid.** Complete coverage and empty findings mean success, not a fallback trigger.
- **Unresolved findings persist.** Deferred issues and unapplied fixes cannot disappear into an “already addressed” list or count as convergence.
- **Recoverable phases.** Review, judgment, apply, verification, and publication have separate phase markers and hashes. V1 state is not compatible.

The current root package is v2.0. `versions/1.0/SKILL.md` preserves the originally published skill. `versions/pre-2.0/` preserves the exact scored package immediately before this update. Historical copies are reference material; install the current root package for v2.

## How a round works

1. Freeze a consistent target/reference snapshot. Gemini, OpenAI balanced, and Claude adversarial review it independently.
2. A fresh judge evaluates every anonymized finding and unresolved ledger item against the documents. It separates “is the defect real?” from “is this the right correction?”, merges duplicates, and orders approved fixes by consequence and prerequisites.
3. One apply agent edits only approved components in a private working copy.
4. A fresh verifier checks the original diagnosis, acceptance criteria, resulting document, and regressions. The orchestrator publishes only a verified patch after checking that the original files have not changed.
5. Update the ledger and either repeat, converge, stall with unresolved work, or halt on failure. Reaching the round limit does not imply all issues are resolved.

Architectural reversals always remain decisions for the user. Unresolved conflicting remedies and claims requiring outside evidence do not become automatic edits. There are no questions between rounds; decisions appear in the report.

## Install

This package targets Claude Code and the external adapters documented in [references/external-critics.md](references/external-critics.md).

```bash
git clone https://github.com/bradsmithmba/triple-critic-loop.git ~/.claude/skills/triple-critic-loop
mkdir -p ~/.claude/agents
ln -s ~/.claude/skills/triple-critic-loop/agents/*.md ~/.claude/agents/
```

If upgrading an existing clone, update its files and link the new `triple-critic-judge.md` and `triple-critic-verifier.md` definitions. Existing critic symlinks will read the updated definitions; do not overwrite unrelated agents. No global installation or account changes are made by editing this repository.

## Invoke and inputs

```text
/triple-critic-loop DOCUMENT_PATH=/absolute/path/to/spec.md LOOPS=3
```

| Input | Default | Meaning |
|---|---|---|
| `DOCUMENT_PATH` | Required | Text file, or directory of Markdown/text documents. |
| `CONTEXT_PATHS` | None | Comma-separated absolute reference paths, read-only. |
| `LOOPS` | `3` | Maximum review/apply rounds; final verification always runs. |
| `EFFORT` | `medium` | Critic effort: low, medium, or high. |
| `JUDGE_MODEL` | `opus` | Fresh judge, high effort. |
| `APPLY_MODEL` | `sonnet` | Single apply agent. |
| `VERIFY_MODEL` | `sonnet` | Fresh verifier, high effort. |
| `STATE_DIR` | New temporary directory | Resume a compatible v2 run. |

`HIGH_THRESHOLD` and `LOW_THRESHOLD` are removed and rejected with a migration message. Start a new v2 run rather than reusing a v1 state directory. Directory review covers `.md` and `.txt` files; this is not a repository-wide code modification skill.

## Dependencies and data handling

- Claude Code with the supplied agent definitions. Critic definitions retain `claude-sonnet-4-6`; judge and external-failure substitute default to `opus`; verifier/apply default to `sonnet`. Model availability and requested overrides are checked at run start.
- The existing `~/.local/bin/agy` Gemini adapter with schema output. Low effort selects `gemini-3.1-pro-low`; medium/high select `gemini-3.1-pro-high`. Preflight installed support; the adapter is not interchangeable with arbitrary Gemini CLIs.
- Codex CLI with authentication, stdin input, read-only execution, and schema output. It uses the configured default model and selected critic effort.
- Bash, `jq`, and GNU `timeout` or `gtimeout` for the external adapters.
- Python 3 and `jsonschema` for the artifact validation helper. Install `requirements-dev.txt` into your chosen virtual environment for development validation.

Targets and reference documents are sent to external providers. As in v1, do not use the skill on credentials, PII, or data governed by residency requirements. State retains snapshots, findings, and diagnostics. Keep it private and copy it to durable storage if needed; temporary directories can be removed by the operating system.

An auth/quota failure stops the run. One other external failure may use an Opus substitute; two external failures stop it. Judge/verifier failures are not silently bypassed. Actual substitutions and models appear in the report.

## Report and state

The report includes the state path, outcome, ranked unresolved findings by disposition, judge explanations, verified changes, unapplied/reverted changes, architectural decisions, and next steps. Per-round counts distinguish new, reopened, resolved, and outstanding findings.

The state protocol is in [references/state.md](references/state.md). It is an orchestration contract followed by the skill, not a standalone workflow engine. The validation helper enforces JSON shape and local policy invariants; the orchestrator still checks source truth, coverage, cross-artifact consistency, file hashes, and publication.

## Development checks

```bash
python3 -m venv /tmp/triple-critic-dev
/tmp/triple-critic-dev/bin/pip install -r requirements-dev.txt
/tmp/triple-critic-dev/bin/python -m unittest discover -s tests -v
```

Validate an individual artifact:

```bash
python3 scripts/validate_artifact.py judgment.schema.json /absolute/path/to/judgment.json
```

Offline tests exercise clean reviews, singleton approval, reversal boundaries, provenance uniqueness, dependencies, acceptance criteria, and verification evidence. They do not establish live model quality or adapter availability. Before tuning judge prompts or model choices, compare recorded reviews on seeded defects and clean controls, inspecting unnecessary edits and missed defects.

## Layout

```text
SKILL.md                       Current v2.0 workflow
findings.schema.json           Critic output contract
judgment.schema.json           Judge dispositions and ordered fixes
verification.schema.json       Independent verification contract
agents/                        Critics, judge, verifier
references/                    Judge rubric, adapters, state/recovery
scripts/validate_artifact.py    JSON and local policy validation
tests/test_contracts.py         Offline contract tests
requirements-dev.txt           Validation dependencies
versions/                      Historical scored skills
```

## License

MIT. See [LICENSE](LICENSE).
