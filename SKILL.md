---
name: cc-flink-sql
description: "Ground rules and CLI validation patterns for Confluent Cloud Flink SQL projects. Use when working in a CC-Flink workspace or when Flink SQL is the subject and the runtime is Confluent Cloud. Prevents drift into Apache Flink assumptions."
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Grep
  - Glob
  - WebFetch
---

<objective>
Enforce the CC-Flink-vs-OSS-Flink boundary and the CLI-driven verification loop in any Confluent Cloud Flink SQL project. Provides dialect traps, CLI reference, CC-validated SQL patterns, format reference, troubleshooting, and anti-patterns.

Includes reference files for dialect traps, CLI patterns, SQL examples, format reference, troubleshooting, and reserved words.
</objective>

<trigger>
Auto-invoke when any of the following hold:

- Working directory path contains `cc_flink`, `cc-flink`, or `flink-udf`.
- A `PROMPT.md` in cwd references "Confluent Cloud Flink".
- User mentions: CC Flink, Confluent Cloud Flink SQL, `confluent flink` CLI, CFU compute pool, `CREATE CONNECTION`, CC Flink UDF, or asks to validate a Flink SQL statement.
- A Flink SQL question is posed and no evidence establishes the runtime is Apache Flink.
</trigger>

<non_negotiables>

1. **CC Flink ≠ Apache Flink.** Apache Flink training data is a trap. Verify every API, SQL construct, and runtime behavior against:
   - Confluent Cloud Flink docs: https://docs.confluent.io/cloud/current/flink/
   - CC Flink SQL reference: https://docs.confluent.io/cloud/current/flink/reference/
   - Confluent Terraform provider: https://registry.terraform.io/providers/confluentinc/confluent/latest/docs
   - Live `confluent flink shell` against the user's compute pool.

2. **No mocks in verification.** Integration claims require real `confluent` CLI runs. Unit tests may mock; anything calling itself "end-to-end verification" may not.

3. **Docs first.** Decisions land in `docs/*.md` before code. Dialect traps go in `docs/flink-dialect-traps.md`.

4. **Secrets never in repo.** `CREATE CONNECTION` parameters TF-injected; never hardcoded. `.tfvars`, `.tfstate*`, `*.secret*` gitignored from day one.

5. **EXPLAIN before CREATE.** Always `EXPLAIN` a query before `statement create`. Catches parse/type errors without consuming CFUs.

</non_negotiables>

<reference_files>

Load these on demand when the topic matches:

| File | When to load |
|------|-------------|
| [references/dialect-traps.md](references/dialect-traps.md) | Before writing ANY Flink SQL — 32 CC-vs-OSS traps, single source of truth |
| [references/cli-reference.md](references/cli-reference.md) | Before running `confluent` CLI — flag schemas, carry-over recipe, timing, token expiry |
| [references/sql-patterns-cc.md](references/sql-patterns-cc.md) | When writing SQL — CC-validated patterns: windows, joins, dedup, MATCH_RECOGNIZE, JSON, External Tables |
| [references/formats-and-serialization.md](references/formats-and-serialization.md) | When configuring table formats — 7 supported formats, id-encoding, consume flags |
| [references/troubleshooting-cc.md](references/troubleshooting-cc.md) | When debugging errors — CC-specific error→cause→fix |
| [references/reserved-words.md](references/reserved-words.md) | When hitting parse errors — must-backquote identifiers |

</reference_files>

<red_flags>

Stop and consult dialect traps if you see yourself writing any of these:

- DataStream API (Java/Scala) — not supported on CC. Table API (Java/Python) IS supported
- `CREATE CATALOG ...` — catalog = CC environment, not creatable
- `SET 'execution.checkpointing.*'` — CC-managed, not settable
- `CREATE TABLE ... WITH ('connector' = 'kafka', ...)` — tables auto-map from topics
- `'value.format' = 'json'` — must be `'json-registry'` (or other SR-backed format)
- `WITH cte AS (...) INSERT INTO ...` — CC requires CTE AFTER INSERT INTO
- `$rowtime AS alias` in CTE — silently strips time-attribute
- `GROUP BY TUMBLE(ts, INTERVAL ...)` — must use TVF: `TUMBLE(TABLE t, DESCRIPTOR(ts), ...)`
- `LATERAL TABLE(UNNEST(...))` — parse error; use `CROSS JOIN UNNEST(...)`
- `PROCTIME()` — not supported; use External Tables/KEY_SEARCH_AGG or upsert-kafka join
- `CREATE FUNCTION f AS '...'` without `USING JAR` — CC UDFs require artifact upload
- Savepoints / `STOP WITH SAVEPOINT` — not exposed on CC
- `--sql-file` flag — doesn't exist; use `--sql "$(cat file.sql)"`
- `--cloud`/`--region` on `statement create` — rejected; use `--environment`

</red_flags>

<verification_loop>

Canonical validation loop for any CC Flink SQL claim:

0. **EXPLAIN** the query in `flink shell` — catches syntax and type errors free.
1. Write minimal reproducer in `repro/<phase>-<slug>.sql`.
2. Run: `confluent flink statement create <name> --sql "$(cat repro.sql)" --compute-pool <id> --database <cluster> --environment <env> --wait`
3. Observe. Consume downstream: `confluent kafka topic consume <topic> --from-beginning --value-format jsonschema 2>/dev/null | grep -v '^%'`
4. Paste command + output into `docs/VERIFICATION-<phase>.md`.

Escalation-required states (no silent workarounds):

- Statement `PENDING` > 60s → `statement exception list`
- UDF deploy "jar not found" → `artifact list`
- Schema mismatch → `DESCRIBE <table>`, diff vs producer schema
- Egress denied → check `CREATE CONNECTION` + `USING CONNECTIONS` clause

See [cli-reference.md](references/cli-reference.md) for full flag schemas and timing expectations.

</verification_loop>

<anti_patterns>

- Apache Flink docs or SO answers tagged `apache-flink` cited as CC authority
- LLM memory of "Flink SQL syntax" used without CC verification
- Mocking `confluent` CLI in anything claiming end-to-end verification
- `terraform apply -auto-approve` on first run of a root module
- Committing `.tfvars`, `.tfstate*`, `.terraform/`, `*.secret*`
- Swallowing Flink statement exceptions — fail loud; read `statement exception list`
- Hardcoded secrets in `CREATE CONNECTION` or UDF source

</anti_patterns>

<tutorials>

https://developer.confluent.io/tutorials/#flink — mix of OSS and CC tutorials.

**Filter rule:** Only use tutorials that include "Confluent Cloud" in prerequisites or use `confluent flink shell`. Apply dialect trap table to any SQL copied from tutorials. Many tutorials target OSS Flink or Kafka Streams — do not assume CC compatibility.

</tutorials>

<source_of_truth_hierarchy>

1. `references/dialect-traps.md` (this skill) — canonical, consolidated
2. Per-project `CLAUDE.md` — references skill, adds project-specific context
3. Per-project `docs/flink-dialect-traps.md` — append-only session log, periodically upstream to skill

When a new trap is discovered: add to `references/dialect-traps.md` first, then propagate.

</source_of_truth_hierarchy>

<references>

- Confluent Cloud Flink docs: https://docs.confluent.io/cloud/current/flink/
- Confluent Cloud Flink SQL reference: https://docs.confluent.io/cloud/current/flink/reference/
- Confluent Terraform provider: https://registry.terraform.io/providers/confluentinc/confluent/latest/docs
- Confluent CLI reference: https://docs.confluent.io/confluent-cli/current/command-reference/flink/
- Tutorials (CC-only filter): https://developer.confluent.io/tutorials/#flink
- Related skill (OSS+CC): https://github.com/gAmUssA/flink-sql-skill

</references>
