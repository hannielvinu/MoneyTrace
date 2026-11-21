"""Enforce the help-desk retention promise: delete reports older than DATA_RETENTION_DAYS (default 90).

    python scripts/purge_old_reports.py [--days 90] [--dry-run]
Run daily (e.g. Cloud Scheduler -> Cloud Run job, or cron). Anonymous usage counts are kept.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=int(os.environ.get("DATA_RETENTION_DAYS", "90")))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    from moneytrace.db.database import purge_reports_older_than
    print(json.dumps(purge_reports_older_than(a.days, a.dry_run)))
