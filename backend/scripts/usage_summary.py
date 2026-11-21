"""
Daily help-desk usage summary (no personal data) -> results/usage/daily_summary.{csv,md}

    python scripts/usage_summary.py --days 30

Counts: reports received, guidance delivered (by scam type), escalations (CRITICAL cases), operator sign-offs,
median seconds from report to first guidance. Source: the usage_events table.
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BACKEND, ".env"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    from moneytrace.db.database import get_usage_summary
    s = get_usage_summary(a.days)
    out = os.path.join(BACKEND, "results", "usage")
    os.makedirs(out, exist_ok=True)
    cols = ["date", "reports_received", "guidance_delivered", "escalations", "operator_signoffs",
            "median_seconds_to_first_guidance", "by_scam_type", "by_language"]
    with open(os.path.join(out, "daily_summary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for d in s["daily"]:
            w.writerow([d["date"], d["reports_received"], d["guidance_delivered"], d["escalations"], d["operator_signoffs"],
                        d["median_seconds_to_first_guidance"], json.dumps(d["by_scam_type"]), json.dumps(d["by_language"])])
    lines = [f"# Help-desk usage (last {a.days} days)", "",
             f"Generated {datetime.now(timezone.utc).isoformat()} by `python scripts/usage_summary.py --days {a.days}`.", "",
             "| Date | Reports | Guidance | Escalations | Sign-offs | Median s to guidance |", "|---|---|---|---|---|---|"]
    lines += [f"| {d['date']} | {d['reports_received']} | {d['guidance_delivered']} | {d['escalations']} | "
              f"{d['operator_signoffs']} | {d['median_seconds_to_first_guidance']} |" for d in s["daily"]]
    t = s["totals"]
    lines += [f"| **Total** | **{t['reports_received']}** | **{t['guidance_delivered']}** | **{t['escalations']}** | "
              f"**{t['operator_signoffs']}** | **{t['median_seconds_to_first_guidance']}** |"]
    open(os.path.join(out, "daily_summary.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
