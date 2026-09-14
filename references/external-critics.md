# External critics and failure handling

These adapters preserve the existing repository's Claude Code, agy, and Codex setup. CLI flags/model availability are installation-dependent: preflight the installed commands' help, schema support, authentication, and agent definitions. Report unsupported capabilities clearly; do not invent replacement flags or silently change models. Only use external services authorized by the requested review.

## Common preparation

Use Bash for the snippets. Define `SKILL_DIR` as this skill's actual absolute directory, `SCHEMA="$SKILL_DIR/findings.schema.json"`, and `ROUND_DIR="$STATE_DIR/round_$N"`. `PAYLOAD_FILE` is the persisted UTF-8 critic input: shared critic prompt, original-path-labeled frozen target/reference contents, manifest, and optional verified history. Build it with file APIs or quoted variables; never interpolate document content as shell code. Each role receives the same documents but its own prompt suffix.

Choose the available GNU `timeout` or `gtimeout` command as `TIMEOUT_BIN`; require it before launching. Set T to 180 seconds plus 30 seconds per started 100KB beyond 200KB of input. Enforce this wall-clock bound. Large input may exceed Gemini's command argument limit or model context: fail with an input-size limitation rather than silently truncate.

Subagent JSON is returned to the orchestrator and captured there. All outputs must pass findings.schema.json, exact reviewed-file coverage, and evidence checks. `review_status: incomplete`, nonempty limitations, missing coverage, nonzero exits, timeouts, or invalid output are failures. `complete` with empty findings and complete coverage is success.

## Gemini

Keep the existing agy model mapping: low → `gemini-3.1-pro-low`; medium/high → `gemini-3.1-pro-high`. The configured adapter supplies the payload through the final `--print` argument. Verify that this installation supports these variants and flags; this reference does not assert that every Gemini CLI has this interface.

```bash
GEMINI_MODEL=$([ "$EFFORT" = low ] && echo gemini-3.1-pro-low || echo gemini-3.1-pro-high)
"$TIMEOUT_BIN" "${T}s" env NO_BROWSER=1 TERM=xterm-256color \
  ~/.local/bin/agy --sandbox --output-format json --json-schema "$SCHEMA" \
  --model "$GEMINI_MODEL" --print "$(cat "$PAYLOAD_FILE")" \
  > "$ROUND_DIR/gemini.raw.json" 2> "$ROUND_DIR/gemini.stderr"
GEMINI_EXIT=$?
jq '.structured_output' "$ROUND_DIR/gemini.raw.json" > "$ROUND_DIR/gemini.json"
```

Run where a nonzero exit can be captured (do not let shell errexit bypass classification). Preserve GEMINI_EXIT before extraction. Consume `.structured_output`, not `.response`, which may contain concatenated fragments. No output progress is required before completion.

## OpenAI balanced

Use the user's authenticated Codex session and configured default model, recording the effective model from events when available. Add a balanced critique suffix covering architecture, reliability, security, performance, scalability, and operability where relevant to the document. Run in one Bash invocation, capture the process status before copying output, and use a fresh temporary output file for every attempt:

```bash
TMPFILE=$(mktemp /tmp/triple_critic_openai_XXXXXX.json)
trap 'rm -f "$TMPFILE"' EXIT
"$TIMEOUT_BIN" "${T}s" codex exec --skip-git-repo-check -s read-only \
  --ephemeral --color never -c model_reasoning_effort="$EFFORT" --json \
  --output-schema "$SCHEMA" -o "$TMPFILE" - \
  < "$PAYLOAD_FILE" > "$ROUND_DIR/openai.events.jsonl" 2> "$ROUND_DIR/openai.stderr"
OPENAI_EXIT=$?
cp "$TMPFILE" "$ROUND_DIR/openai.json"
```

The final `-` explicitly selects stdin for the complete instructions and payload. Quiet stderr is not failure. Inspect structured errors before retrying: for a non-auth/quota nonzero exit with empty output, retry once with a fresh invocation; preserve the first attempt's events/stderr under attempt-specific filenames. No unbounded retries.

## Claude adversarial

Launch `critic-$EFFORT`, whose definitions specify `claude-sonnet-4-6` and effort. Missing definitions fail preflight rather than falling back to general-purpose. For systems documents, focus on race conditions, security bypasses, scale assumptions, and production failure paths. For product/process documents, focus on unstated assumptions, missing failure paths, unowned decisions, unmeasurable success criteria, and reference contradictions. Challenge mitigations without manufacturing findings. Read only frozen input files or supplied payload, and return JSON without writing files.

## Failures

Classify auth/quota from structured error output only; never search echoed documents or model answers. For the existing adapters, use these signatures:

```bash
jq -r 'select(.type=="error" or .type=="turn.failed") | .. | strings' \
  "$ROUND_DIR/openai.events.jsonl" | \
  grep -Eiq 'not authenticated|login required|invalid credentials|refresh token|invalid_grant|\b401\b|quota exceeded|rate limit|\b429\b|resource exhausted|usage limit'
```

For agy, inspect stderr lines beginning `error:` and envelope metadata with `.response` and `.structured_output` removed, using the same signature expression. Preserve diagnostics and the matched error, excluding document contents from the user-facing error summary. Auth/quota failure stops `failed_loop`; substitution cannot repair account state.

For one other external critic failure after bounded correction/retry, substitute one fresh Opus Claude subagent (`model: opus` explicitly) using the same frozen input and failed critic's role. Record actual provider/model provenance. Await both external outcomes before substitution; if both fail, abort without substituting. A failed Claude critic or failed substitute stops failed_loop after at most one output-repair request. Cancel pending workers on terminal failure. Valid empty findings never cause substitution.
