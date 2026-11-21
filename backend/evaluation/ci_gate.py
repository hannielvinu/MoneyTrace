"""CI gate: fail when recall@5 or fully-grounded % drop below the committed baseline (minus a small tolerance).

    python -m evaluation.ci_gate <current_summary.json> <baseline_summary.json> [--tolerance 0.05]
The baseline is created by copying a reviewed subset run: cp results/rag_eval/latest_subset.json results/rag_eval/baseline_subset.json
"""
import json
import sys


def main(argv):
    cur, base = json.load(open(argv[0])), json.load(open(argv[1]))
    tol = float(argv[argv.index("--tolerance") + 1]) if "--tolerance" in argv else 0.05
    failures = []
    if cur["recall_at_5"] < base["recall_at_5"] - tol:
        failures.append(f"recall@5 {cur['recall_at_5']} < baseline {base['recall_at_5']} - {tol}")
    if "fully_grounded_pct" in base and cur.get("fully_grounded_pct", 0) < base["fully_grounded_pct"] - 100 * tol:
        failures.append(f"fully grounded {cur.get('fully_grounded_pct')}% < baseline {base['fully_grounded_pct']}% - {100 * tol}")
    print(json.dumps({"current": {k: cur.get(k) for k in ("recall_at_5", "fully_grounded_pct")},
                      "baseline": {k: base.get(k) for k in ("recall_at_5", "fully_grounded_pct")},
                      "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
