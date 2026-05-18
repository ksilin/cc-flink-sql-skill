# cc-flink-sql

Claude Code skill that enforces the Confluent Cloud Flink SQL dialect and prevents drift into Apache Flink (OSS) syntax.

## Why

Claude's training data heavily favors open-source Apache Flink. When working on Confluent Cloud Flink SQL projects, Claude silently produces syntax that is valid for OSS Flink but rejected by CC — wrong window functions, unavailable APIs, nonexistent CLI flags. This skill corrects that.

## What it does

- **32 dialect traps** — CC-vs-OSS differences, severity-classified, checked before writing SQL
- **CLI reference** — flag schemas (they differ per subcommand), carry-over recipe, timing expectations
- **CC-validated SQL patterns** — windows, joins, dedup, MATCH_RECOGNIZE, JSON processing, External Tables
- **Format reference** — the 7 supported serialization formats, `id-encoding`, consumer flags
- **Troubleshooting** — CC-specific error messages with causes and fixes
- **Reserved words** — identifiers that must be backquoted, with diagnostic hints
- **Verification loop** — EXPLAIN before CREATE, real CLI runs, no mocks for integration claims

## Eval results (Haiku)

| Arm | Score | Pass/Fail |
|-----|-------|-----------|
| Without skill | 15% | 3/20 |
| With skill | 90% | 18/20 |
| **Delta** | **+75pp** | |

20 trap prompts covering CC-specific pitfalls. Negation-aware scoring (model correctly mentioning a bad pattern as "don't do this" is not penalized).

## Structure

```
cc-flink-sql/
  SKILL.md                              # Rules, triggers, red flags, verification loop
  references/
    dialect-traps.md                    # 32 CC-vs-OSS traps (single source of truth)
    cli-reference.md                    # Flag schemas, carry-over, timing, token expiry
    sql-patterns-cc.md                  # CC-validated SQL patterns
    formats-and-serialization.md        # 7 formats, id-encoding, consume flags
    troubleshooting-cc.md               # CC error -> cause -> fix
    reserved-words.md                   # Must-backquote identifiers
  evals/
    trigger_eval.json                   # 10+10 trigger precision cases
    prompts/cc-flink-traps.jsonl        # 20 trap avoidance prompts
    llm_run.py                          # 2-arm eval runner
    measure.py                          # Pattern-match scorer
    snapshots/results.json              # Committed Haiku baseline
    README.md                           # Eval design and usage
```

## Run evals

```bash
cd ~/.claude/skills/cc-flink-sql

# Generate snapshot (~2-4 min on Haiku)
CC_FLINK_EVAL_MODEL=claude-haiku-4-5 python evals/llm_run.py

# Score (no LLM calls)
python evals/measure.py
```

## Key references

- [Confluent Cloud Flink docs](https://docs.confluent.io/cloud/current/flink/)
- [CC Flink SQL reference](https://docs.confluent.io/cloud/current/flink/reference/)
- [Confluent CLI — Flink commands](https://docs.confluent.io/confluent-cli/current/command-reference/flink/)
- [Tutorials (filter for CC only)](https://developer.confluent.io/tutorials/#flink)
