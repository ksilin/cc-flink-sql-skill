"""
Run each CC Flink SQL eval prompt through Claude Code in two arms and snapshot
the real LLM outputs:

  1. no_skill   — neutral system prompt ("You are a helpful assistant.")
  2. with_skill — SKILL.md + all reference files injected as system prompt

ISOLATION (Max subscription compatible, uses OAuth):
  - --system-prompt: replaces default system prompt entirely (CLAUDE.md not included)
  - --disable-slash-commands: prevents cc-flink-sql skill from auto-triggering
  - cwd=/tmp (temp dir): no project CLAUDE.md in working directory
  - Prompt via stdin: avoids shell arg issues

The ONLY difference between arms is the system prompt content.
Without isolation, the no_skill arm would score artificially high
because project CLAUDE.md already contains the dialect trap table.

Requires:
  - `claude` CLI on PATH, logged in (OAuth — works with Max subscription)

Run:
    python evals/llm_run.py
    CC_FLINK_EVAL_MODEL=claude-haiku-4-5 python evals/llm_run.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

EVALS = Path(__file__).parent
SKILL_DIR = EVALS.parent
SKILL_MD = SKILL_DIR / "SKILL.md"
PROMPTS = EVALS / "prompts" / "cc-flink-traps.jsonl"
SNAPSHOT = EVALS / "snapshots" / "results.json"
REFERENCE_DIR = SKILL_DIR / "references"


def load_skill_context() -> str:
    """Load SKILL.md + all reference files as a single system prompt."""
    parts = [SKILL_MD.read_text()]
    if REFERENCE_DIR.is_dir():
        for ref in sorted(REFERENCE_DIR.glob("*.md")):
            parts.append(f"\n\n--- {ref.name} ---\n\n{ref.read_text()}")
    return "\n".join(parts)


def load_prompts() -> list[dict]:
    """Load JSONL prompt file."""
    prompts = []
    for line in PROMPTS.read_text().splitlines():
        line = line.strip()
        if line:
            prompts.append(json.loads(line))
    return prompts


def run_claude(prompt: str, system: str | None = None, cwd: str = "/tmp") -> str:
    """Run a single prompt through claude CLI with isolation.

    Isolation (Max subscription compatible, uses OAuth):
    - --system-prompt: replaces default system prompt (CLAUDE.md not included)
    - --disable-slash-commands: prevents skills from auto-triggering
    - cwd=/tmp: no project CLAUDE.md in working directory
    - no_skill arm gets neutral "You are a helpful assistant." system prompt
    - Prompt passed via stdin to avoid shell arg issues
    """
    cmd = [
        "claude", "-p",
        "--disable-slash-commands",
        "--output-format", "text",
    ]
    if system:
        cmd += ["--system-prompt", system]
    else:
        # no_skill arm: explicit neutral system prompt to override any defaults
        cmd += ["--system-prompt", "You are a helpful assistant. Answer the user's question."]
    model = os.environ.get("CC_FLINK_EVAL_MODEL")
    if model:
        cmd += ["--model", model]

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
            cwd=cwd,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    except subprocess.CalledProcessError as e:
        return f"[ERROR: {e.returncode}] {e.stderr[:500]}"


def claude_version() -> str:
    try:
        out = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def preflight_checks() -> bool:
    """Verify environment before spending API tokens."""
    ok = True

    # Verify claude CLI works with isolation flags
    try:
        result = subprocess.run(
            ["claude", "-p",
             "--disable-slash-commands",
             "--output-format", "text",
             "--system-prompt", "You are a helpful assistant."],
            input="Say OK",
            capture_output=True, text=True, timeout=60, cwd="/tmp",
        )
        if result.returncode != 0:
            print(f"ERROR: claude preflight failed (exit {result.returncode}):")
            print(f"  stdout: {result.stdout.strip()[:300]}")
            print(f"  stderr: {result.stderr.strip()[:300]}")
            ok = False
        else:
            print(f"  Preflight OK ({len(result.stdout.strip())} chars)")
    except subprocess.TimeoutExpired:
        print(f"ERROR: claude preflight timed out after 60s")
        ok = False
    except Exception as e:
        print(f"ERROR: claude CLI not working: {e}")
        ok = False

    return ok


def main() -> None:
    prompts = load_prompts()
    skill_context = load_skill_context()
    model = os.environ.get("CC_FLINK_EVAL_MODEL", "default")

    n_calls = len(prompts) * 2
    print(f"=== CC Flink SQL Eval ===", flush=True)
    print(f"  {len(prompts)} prompts x 2 arms = {n_calls} LLM calls", flush=True)
    print(f"  Model: {model}", flush=True)
    print(f"  Skill context: {len(skill_context)} chars", flush=True)
    print(f"  Isolation: --system-prompt override, --disable-slash-commands, cwd=/tmp", flush=True)
    print(flush=True)

    if not preflight_checks():
        sys.exit(1)

    # Run from a temp dir to guarantee no CLAUDE.md in cwd
    with tempfile.TemporaryDirectory(prefix="cc-flink-eval-") as tmpdir:
        print(f"  Working dir: {tmpdir}", flush=True)
        print(flush=True)

        snapshot = {
            "metadata": {
                "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "claude_cli_version": claude_version(),
                "model": model,
                "n_prompts": len(prompts),
                "skill_chars": len(skill_context),
                "isolation": {
                    "system_prompt_override": True,
                    "slash_commands_disabled": True,
                    "prompt_via_stdin": True,
                    "cwd": tmpdir,
                    "no_skill_system_prompt": "You are a helpful assistant. Answer the user's question.",
                    "note": "Both arms run from /tmp with --system-prompt override "
                            "(CLAUDE.md not loaded). Only system prompt content differs.",
                },
            },
            "prompts": prompts,
            "arms": {"no_skill": [], "with_skill": []},
        }

        for i, p in enumerate(prompts, 1):
            prompt_text = p["prompt"]
            pid = p["id"]

            print(f"  [{i}/{len(prompts)}] {pid}", flush=True)

            print(f"    no_skill ...", end=" ", flush=True)
            out_no = run_claude(prompt_text, cwd=tmpdir)
            print(f"{len(out_no)} chars", flush=True)
            snapshot["arms"]["no_skill"].append(out_no)

            print(f"    with_skill ...", end=" ", flush=True)
            out_with = run_claude(prompt_text, system=skill_context, cwd=tmpdir)
            print(f"{len(out_with)} chars", flush=True)
            snapshot["arms"]["with_skill"].append(out_with)

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)

    # Archive previous snapshot if it exists
    if SNAPSHOT.exists():
        prev = SNAPSHOT.with_name("results-previous.json")
        SNAPSHOT.rename(prev)
        print(f"\n  Archived previous snapshot to {prev.name}")

    SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    print(f"\n  Wrote {SNAPSHOT}")
    print(f"  Run `python evals/measure.py` to score.")


if __name__ == "__main__":
    main()
