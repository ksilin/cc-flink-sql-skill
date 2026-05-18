"""
Score CC Flink SQL eval snapshots for trap avoidance correctness.

Reads evals/snapshots/results.json and checks each output against
must_contain / must_not_contain patterns from the prompt definitions.

No LLM calls — runs offline against committed snapshot.

Run:
    python evals/measure.py
    python evals/measure.py --compare snapshots/results-previous.json
    python evals/measure.py --verbose    # show per-prompt details
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SNAPSHOT = Path(__file__).parent / "snapshots" / "results.json"
PROMPTS_FILE = Path(__file__).parent / "prompts" / "cc-flink-traps.jsonl"


def load_current_prompts() -> list[dict] | None:
    """Load current prompt patterns from JSONL file (overrides snapshot patterns)."""
    if not PROMPTS_FILE.exists():
        return None
    prompts = []
    for line in PROMPTS_FILE.read_text().splitlines():
        if line.strip():
            prompts.append(json.loads(line))
    return prompts


NEGATION_MARKERS_BEFORE = [
    "❌", "wrong", "fails", "rejected", "not supported", "won't work",
    "doesn't exist", "don't", "can't", "cannot", "not available",
    "not this", "bad example", "incorrect", "invalid", "do not use",
    "not allowed", "trap", "-- no", "# no", "instead of",
    "has no", "no `", "removed", "unsupported",
]

NEGATION_MARKERS_AFTER = [
    "doesn't exist", "not supported", "not available", "not allowed",
    "won't work", "fails", "rejected", "removed", "is not",
    "flag doesn't", "doesn't work",
]


def _find_pattern(pattern: str, output: str) -> list[int]:
    """Find all match positions for a pattern in output. Returns list of start positions."""
    positions = []
    try:
        for m in re.finditer(pattern, output, re.IGNORECASE | re.DOTALL):
            positions.append(m.start())
    except re.error:
        lower = output.lower()
        pat_lower = pattern.lower()
        start = 0
        while True:
            idx = lower.find(pat_lower, start)
            if idx == -1:
                break
            positions.append(idx)
            start = idx + 1
    return positions


def _is_negation_context(output: str, match_pos: int, window: int = 200) -> bool:
    """Check if a match position is in a negation context.

    Looks backward AND forward for negation markers. Handles patterns like:
    - "CC has no `PROCTIME()`"  (negation before)
    - "`--sql-file` flag doesn't exist"  (negation after)
    - "❌ WRONG: SET 'execution.checkpointing'"  (negation before)
    """
    before_start = max(0, match_pos - window)
    before = output[before_start:match_pos].lower()
    if any(marker in before for marker in NEGATION_MARKERS_BEFORE):
        return True

    after_end = min(len(output), match_pos + window)
    after = output[match_pos:after_end].lower()
    if any(marker in after for marker in NEGATION_MARKERS_AFTER):
        return True

    return False


def check_output(output: str, must_contain: list[str], must_not_contain: list[str]) -> dict:
    """Check a single output against pattern rules. Returns detailed result.

    must_not_contain is negation-aware: if a bad pattern appears only in
    "don't do this" / "❌ WRONG" context, it's counted as 'mentioned_not_recommended'
    and does NOT fail the check. Only uncontextualized recommendations of the
    bad pattern count as violations.
    """
    output_lower = output.lower()

    found = []
    missing = []
    for pattern in must_contain:
        if _find_pattern(pattern, output):
            found.append(pattern)
        elif pattern.lower() in output_lower:
            found.append(pattern)
        else:
            missing.append(pattern)

    violations = []
    mentioned_not_recommended = []
    for pattern in must_not_contain:
        if not pattern:
            continue
        positions = _find_pattern(pattern, output)
        if not positions:
            continue

        # Check if ALL occurrences are in negation context
        all_negated = all(_is_negation_context(output, pos) for pos in positions)
        if all_negated:
            mentioned_not_recommended.append(pattern)
        else:
            violations.append(pattern)

    passed = len(missing) == 0 and len(violations) == 0
    return {
        "passed": passed,
        "found": found,
        "missing": missing,
        "violations": violations,
        "mentioned_not_recommended": mentioned_not_recommended,
    }


def score_arm(prompts: list[dict], outputs: list[str]) -> list[dict]:
    """Score all outputs for one arm."""
    results = []
    for prompt, output in zip(prompts, outputs):
        result = check_output(
            output,
            prompt.get("must_contain", []),
            prompt.get("must_not_contain", []),
        )
        result["id"] = prompt["id"]
        result["category"] = prompt.get("category", "unknown")
        result["trap_id"] = prompt.get("trap_id")
        results.append(result)
    return results


def print_summary(prompts: list[dict], arms: dict[str, list[str]], verbose: bool = False) -> dict:
    """Print scored summary and return scores dict."""
    scores = {}
    for arm_name, outputs in arms.items():
        results = score_arm(prompts, outputs)
        passed = sum(1 for r in results if r["passed"])
        total = len(results)
        score = passed / total if total else 0
        scores[arm_name] = {"score": score, "passed": passed, "total": total, "results": results}

    meta_line = ""
    print()
    print("CC Flink SQL Skill Eval")
    print("=" * 50)
    print()

    # Arm comparison table
    print("| Arm         | Score  | Pass | Fail |")
    print("|-------------|--------|------|------|")
    for arm_name, s in scores.items():
        fail = s["total"] - s["passed"]
        print(f"| {arm_name:<11} | {s['score']:5.0%}  | {s['passed']:4} | {fail:4} |")

    if "no_skill" in scores and "with_skill" in scores:
        delta = scores["with_skill"]["score"] - scores["no_skill"]["score"]
        print(f"| {'delta':<11} | {delta:+5.0%}  |      |      |")

    # Category breakdown for with_skill
    if "with_skill" in scores:
        print()
        print("Category breakdown (with_skill):")
        print("| Category           | Score | Pass/Total |")
        print("|--------------------|-------|------------|")

        categories = {}
        for r in scores["with_skill"]["results"]:
            cat = r["category"]
            if cat not in categories:
                categories[cat] = {"passed": 0, "total": 0}
            categories[cat]["total"] += 1
            if r["passed"]:
                categories[cat]["passed"] += 1

        for cat, c in sorted(categories.items()):
            cat_score = c["passed"] / c["total"] if c["total"] else 0
            print(f"| {cat:<18} | {cat_score:5.0%} | {c['passed']}/{c['total']:<9} |")

    # Mentioned-not-recommended summary (negation-aware matches)
    for arm_name in ["with_skill"]:
        if arm_name not in scores:
            continue
        mnr = [r for r in scores[arm_name]["results"] if r.get("mentioned_not_recommended")]
        if mnr:
            print()
            print(f"Correctly identified traps ({arm_name}) — mentioned bad pattern as 'don't do this':")
            for r in mnr:
                print(f"  {r['id']}: {r['mentioned_not_recommended']}")

    # Failed prompts detail
    for arm_name in ["with_skill", "no_skill"]:
        if arm_name not in scores:
            continue
        failed = [r for r in scores[arm_name]["results"] if not r["passed"]]
        if failed:
            print()
            print(f"Failed prompts ({arm_name}):")
            for r in failed:
                reasons = []
                if r["missing"]:
                    reasons.append(f"missing: {r['missing']}")
                if r["violations"]:
                    reasons.append(f"violations: {r['violations']}")
                print(f"  {r['id']}: {'; '.join(reasons)}")

    # Verbose: show all outputs
    if verbose:
        for arm_name, outputs in arms.items():
            print()
            print(f"=== {arm_name} outputs ===")
            for prompt, output in zip(prompts, outputs):
                print(f"\n--- {prompt['id']} ---")
                print(output[:500])
                if len(output) > 500:
                    print(f"  ... ({len(output)} chars total)")

    return scores


def main() -> None:
    parser = argparse.ArgumentParser(description="Score CC Flink SQL eval snapshot")
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT, help="Path to results.json")
    parser.add_argument("--compare", type=Path, default=None, help="Compare against previous snapshot")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show per-prompt output excerpts")
    parser.add_argument("--json", action="store_true", help="Output scores as JSON")
    args = parser.parse_args()

    if not args.snapshot.exists():
        print(f"No snapshot at {args.snapshot}. Run `python evals/llm_run.py` first.")
        sys.exit(1)

    data = json.loads(args.snapshot.read_text())
    meta = data.get("metadata", {})

    print(f"Generated: {meta.get('generated_at', '?')}")
    print(f"Model: {meta.get('model', '?')} | CLI: {meta.get('claude_cli_version', '?')}")
    print(f"Prompts: {meta.get('n_prompts', '?')}")

    # Use current prompt patterns from JSONL file if available (allows re-scoring
    # existing snapshots after pattern fixes without re-running LLM calls)
    current_prompts = load_current_prompts()
    if current_prompts and len(current_prompts) == len(data["prompts"]):
        # Verify prompt IDs match
        snap_ids = [p["id"] for p in data["prompts"]]
        cur_ids = [p["id"] for p in current_prompts]
        if snap_ids == cur_ids:
            print("(Using current prompt patterns from cc-flink-traps.jsonl)")
            prompts = current_prompts
        else:
            print("(Prompt IDs changed — using patterns from snapshot)")
            prompts = data["prompts"]
    else:
        prompts = data["prompts"]

    scores = print_summary(prompts, data["arms"], verbose=args.verbose)

    # Compare with previous
    if args.compare and args.compare.exists():
        prev_data = json.loads(args.compare.read_text())
        prev_meta = prev_data.get("metadata", {})
        print()
        print(f"Comparison vs {args.compare.name} (generated: {prev_meta.get('generated_at', '?')})")
        prev_scores = {}
        for arm_name, outputs in prev_data["arms"].items():
            results = score_arm(prev_data["prompts"], outputs)
            passed = sum(1 for r in results if r["passed"])
            total = len(results)
            prev_scores[arm_name] = passed / total if total else 0

        print("| Arm         | Previous | Current  | Change |")
        print("|-------------|----------|----------|--------|")
        for arm_name in scores:
            cur = scores[arm_name]["score"]
            prev = prev_scores.get(arm_name, 0)
            change = cur - prev
            print(f"| {arm_name:<11} | {prev:6.0%}   | {cur:6.0%}   | {change:+5.0%}  |")

    if args.json:
        json_out = {arm: {"score": s["score"], "passed": s["passed"], "total": s["total"]}
                    for arm, s in scores.items()}
        print()
        print(json.dumps(json_out, indent=2))

    # Exit code: non-zero if with_skill arm has failures
    if "with_skill" in scores and scores["with_skill"]["score"] < 1.0:
        sys.exit(1)


if __name__ == "__main__":
    main()
