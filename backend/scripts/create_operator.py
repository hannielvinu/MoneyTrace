"""
Create (or reset) FRAUD_OPERATOR accounts for WhiteHats club members.

    python scripts/create_operator.py --email member@vitstudent.ac.in --name "A. Member"
    python scripts/create_operator.py --csv operators.csv        # columns: email,name

A random password is generated and printed ONCE; share it with the member privately and ask them to keep it
safe. Uses DATABASE_URL (point it at the production database to create live accounts).
"""
import argparse
import csv
import os
import re
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


def create(email: str, name: str, password: str = None):
    from moneytrace.db.database import init_db, create_user, get_user_by_email
    init_db()
    email = email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValueError(f"invalid email: {email}")
    existing = get_user_by_email(email)
    uid = existing["id"] if existing else "op_" + secrets.token_hex(6)
    password = password or secrets.token_urlsafe(12)
    create_user(uid, email, password, name, "FRAUD_OPERATOR")
    return uid, password, bool(existing)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email")
    ap.add_argument("--name", default="")
    ap.add_argument("--csv")
    a = ap.parse_args()
    items = []
    if a.csv:
        items = [(r["email"], r.get("name", "")) for r in csv.DictReader(open(a.csv, encoding="utf-8"))]
    elif a.email:
        items = [(a.email, a.name or a.email.split("@")[0])]
    else:
        ap.error("--email or --csv required")
    for email, name in items:
        uid, pw, existed = create(email, name)
        print(f"{'reset' if existed else 'created'} FRAUD_OPERATOR {email} (id {uid})  password: {pw}")


if __name__ == "__main__":
    main()
