# CC Flink SQL Skill — Evals

Measures whether the cc-flink-sql skill prevents Claude from drifting into
Apache Flink syntax when targeting Confluent Cloud. Correctness eval, not
compression eval.

## The two arms

| Arm | System prompt | What it measures |
|-----|--------------|-----------------|
| `no_skill` | none | Baseline: how often does Claude produce OSS-drifted SQL? |
| `with_skill` | SKILL.md + all references | Treatment: does the skill prevent the drift? |

The delta = traps avoided with skill minus traps avoided without.

## Isolation (critical)

Both arms run with identical isolation to prevent ambient context from
skewing results. Without this, the no_skill arm picks up the project's
CLAUDE.md (which contains the full dialect trap table) and scores
artificially high.

| Contamination source | Risk without isolation | Mitigation |
|---|---|---|
| Project CLAUDE.md | **FATAL** — contains 20+ dialect traps | `--system-prompt` replaces default (CLAUDE.md not loaded) |
| Skills auto-triggering | cc-flink-sql fires on Flink keywords | `--disable-slash-commands` |
| cwd CLAUDE.md | Picked up from working directory | `cwd=/tmp` (temp dir) |

Flags used: `claude -p --disable-slash-commands --output-format text --system-prompt "..."`

The no_skill arm gets a neutral `"You are a helpful assistant."` system prompt.
The with_skill arm gets SKILL.md + all reference files as system prompt.
Works with Max subscription (OAuth). No API key needed.

## Design

- **20 trap prompts** in `prompts/cc-flink-traps.jsonl`, each with `must_contain`
  and `must_not_contain` patterns derived from the 32-entry dialect trap table.
- **Pattern-match scoring** — no judge LLM needed. A prompt passes if all
  `must_contain` patterns are found and zero `must_not_contain` patterns appear.
- **Categories**: trap_avoidance, cli_correctness, format_correctness, pattern_quality.
- **Snapshot committed** so scoring runs offline without API calls.

## Files

- `trigger_eval.json` — Claude Code plugin format: 10 should-trigger + 10 should-not
- `prompts/cc-flink-traps.jsonl` — 20 trap prompts with expected patterns
- `llm_run.py` — runs `claude -p` per (prompt, arm), writes `snapshots/results.json`
- `measure.py` — reads snapshot, scores against patterns, prints report
- `snapshots/results.json` — committed source of truth

## Generate snapshot (requires `claude` CLI, logged in)

```bash
cd ~/.claude/skills/cc-flink-sql

# Haiku (~2-4 min):
CC_FLINK_EVAL_MODEL=claude-haiku-4-5 python evals/llm_run.py

# Opus (~7-12 min):
CC_FLINK_EVAL_MODEL=claude-opus-4-6 python evals/llm_run.py

# Default model:
python evals/llm_run.py
```

Preflight check runs one test call before spending tokens.
40 LLM calls total (20 prompts x 2 arms).
Works with Max subscription (OAuth) — no API key needed.

## Score snapshot (no LLM, no API key)

```bash
python evals/measure.py
python evals/measure.py --verbose         # show output excerpts
python evals/measure.py --compare snapshots/results-previous.json
python evals/measure.py --json            # machine-readable output
```

Exit code 0 = all with_skill prompts pass. Non-zero = regressions.

## Adding a prompt

Append a JSONL line to `prompts/cc-flink-traps.jsonl`:

```json
{"id": "trap-new-thing", "prompt": "...", "category": "trap_avoidance", "must_contain": ["correct pattern"], "must_not_contain": ["oss pattern"], "trap_id": 33}
```

Then regenerate the snapshot.

## What this does NOT measure

- **Fidelity beyond patterns** — a response could contain the right keywords in
  a wrong explanation. A future v2 could add an LLM judge rubric.
- **Trigger accuracy** — `trigger_eval.json` is declarative; no automated harness
  yet tests whether the skill actually fires.
- **Cross-model behavior** — only the model used for the snapshot is measured.
- **Statistical significance** — single run per (prompt, arm). Noise is real.
