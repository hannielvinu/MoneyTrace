"""
Load test for the MoneyTrace API (local or the deployed Cloud Run URL).

    python scripts/load_test.py --base-url https://<service>.run.app --n 100 --concurrency 5

For each request it logs in as the demo victim, submits a realistic report
(mixed languages: en / hi / ta / kn; mixed fraud types), then polls until the
case reaches COMPLETE and reads the measured telemetry the server recorded for
that investigation (/api/incidents/{id}/metrics).

Reported (all computed from measured values, raw rows saved next to the summary):
  - intake API latency  : POST /api/portal/reports round trip (victim gets the case id + acknowledgement)
  - time to guidance    : submit -> investigation COMPLETE with guidance delivered (end-to-end agent pipeline)
  - p50 / p95 / mean of both, tokens/sec (output tokens / model wall time), INR per request
Results: results/load/<run_id>/{requests.jsonl, summary.json}
"""
import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
from datetime import datetime, timezone

import httpx

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REPORTS = [
    ("en", "Fake KYC", "Got a call saying my SBI KYC expires today. He sent a link, I entered the OTP and Rs {amt} was debited to {upi}."),
    ("en", "UPI collect", "Someone on OLX said he would pay for my sofa and sent a request. I entered my UPI PIN and {amt} rupees went to {upi} instead."),
    ("en", "Screen share", "A caller from 'customer care' asked me to install AnyDesk to fix my refund. Next morning ₹{amt} was gone."),
    ("en", "Fake customer care", "I searched Google for the courier helpline, called the number and they asked me to pay ₹5 via a link. Later ₹{amt} was debited."),
    ("en", "Investment / task", "A WhatsApp group promised 30% daily profit on a trading app. I invested ₹{amt} through UPI to {upi} and cannot withdraw."),
    ("en", "Digital arrest", "Men claiming to be CBI on a video call said my Aadhaar was used for drug parcels and made me transfer ₹{amt} to a 'safe account'."),
    ("hi", "Fake KYC", "किसी ने फोन करके कहा कि मेरा KYC बंद हो जाएगा, लिंक भेजा और OTP लिया। मेरे खाते से ₹{amt} कट गए।"),
    ("hi", "Task scam", "टेलीग्राम पर पार्ट टाइम जॉब के नाम पर टास्क दिए, पहले थोड़ा पैसा मिला फिर ₹{amt} जमा करवाकर ब्लॉक कर दिया।"),
    ("ta", "UPI collect", "பணம் பெற PIN போடச் சொன்னார்கள், நான் போட்டேன், ₹{amt} என் கணக்கிலிருந்து போய்விட்டது. {upi}"),
    ("ta", "Fake KYC", "வங்கி KYC அப்டேட் என்று ஒரு லிங்க் அனுப்பினார்கள், OTP சொன்னேன், ₹{amt} எடுக்கப்பட்டது."),
    ("kn", "Fake customer care", "ಕಸ್ಟಮರ್ ಕೇರ್ ಎಂದು ಕರೆ ಮಾಡಿ ರಿಫಂಡ್ ಕೊಡುತ್ತೇವೆ ಎಂದರು, ಆಪ್ ಇನ್‌ಸ್ಟಾಲ್ ಮಾಡಿಸಿ ₹{amt} ತೆಗೆದರು."),
    ("en", "Loan app", "An instant loan app is threatening to send morphed photos to my contacts unless I pay ₹{amt} more to {upi}."),
]
UPIS = ["kyc-update.pay@ybl", "refund.desk@okaxis", "profit.club@paytm", "safe.account@okicici", "help.care@ibl"]


def pct(values, p):
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p / 100
    f, c = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[f] + (v[c] - v[f]) * (k - f), 1)


async def one(client, i, token, op_token, poll_timeout):
    lang, kind, tmpl = REPORTS[i % len(REPORTS)]
    amt = random.Random(i).choice([2500, 7250, 18500, 49999, 120000])
    upi = UPIS[i % len(UPIS)]
    body = {"narrative": tmpl.format(amt=f"{amt:,}", upi=upi), "language": lang, "amount": float(amt), "consent": True}
    row = {"i": i, "language": lang, "kind": kind, "amount": amt}
    t0 = time.perf_counter()
    try:
        r = await client.post("/api/portal/reports", json=body, headers={"Authorization": f"Bearer {token}"})
        row["intake_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        row["status_code"] = r.status_code
        if r.status_code != 200:
            row["error"] = r.text[:200]
            return row
        inc = r.json()["incident_id"]
        row["incident_id"] = inc
        deadline = time.perf_counter() + poll_timeout
        while time.perf_counter() < deadline:
            await asyncio.sleep(1.0)
            m = await client.get(f"/api/incidents/{inc}/metrics", headers={"Authorization": f"Bearer {op_token}"})
            if m.status_code == 200 and m.json().get("investigation_stage") == "COMPLETE" and m.json().get("request_metrics"):
                d = m.json()
                row["time_to_guidance_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                row["server_metrics"] = d["request_metrics"]
                row["ai_status"] = (d.get("ai_investigator") or {}).get("status")
                row["fully_grounded"] = (d.get("grounding") or {}).get("fully_grounded")
                return row
        row["error"] = "timeout waiting for COMPLETE"
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {e}"[:200]
    return row


async def run(args):
    async with httpx.AsyncClient(base_url=args.base_url, timeout=60) as client:
        v = await client.post("/api/auth/login", json={"email": args.victim_email, "password": args.victim_password})
        o = await client.post("/api/auth/login", json={"email": args.operator_email, "password": args.operator_password})
        v.raise_for_status(), o.raise_for_status()
        token, op_token = v.json()["access_token"], o.json()["access_token"]
        sem = asyncio.Semaphore(args.concurrency)

        async def guarded(i):
            async with sem:
                row = await one(client, i, token, op_token, args.poll_timeout)
                print(f"[{i + 1}/{args.n}] {row.get('language')} {row.get('kind')}: intake={row.get('intake_ms')} ms "
                      f"guidance={row.get('time_to_guidance_ms')} ms {row.get('error', '')}", flush=True)
                return row
        t0 = time.time()
        rows = await asyncio.gather(*(guarded(i) for i in range(args.n)))
        return rows, time.time() - t0


def summarise(rows, args, wall_s):
    ok = [r for r in rows if "time_to_guidance_ms" in r]
    intake = [r["intake_ms"] for r in rows if "intake_ms" in r and r.get("status_code") == 200]
    e2e = [r["time_to_guidance_ms"] for r in ok]
    sm = [r["server_metrics"] for r in ok]
    tps = [m["output_tokens_per_sec"] for m in sm if m.get("output_tokens_per_sec")]
    inr = [m["cost_inr"] for m in sm if m.get("cost_inr") is not None]
    sys.path.insert(0, BACKEND)
    from moneytrace.config import get_settings, PRICES_CHECKED_ON
    s = get_settings()
    models = sorted({mm for m in sm for mm in m.get("models", [])})
    return {
        "run_id": args.run_id, "date_utc": datetime.now(timezone.utc).isoformat(), "base_url": args.base_url,
        "command": "python scripts/load_test.py " + " ".join(sys.argv[1:]),
        "requests": len(rows), "completed": len(ok), "errors": len(rows) - len(ok), "concurrency": args.concurrency,
        "wall_time_s": round(wall_s, 1),
        "intake_latency_ms": {"p50": pct(intake, 50), "p95": pct(intake, 95), "mean": round(statistics.mean(intake), 1) if intake else None},
        "time_to_guidance_ms": {"p50": pct(e2e, 50), "p95": pct(e2e, 95), "mean": round(statistics.mean(e2e), 1) if e2e else None},
        "avg_output_tokens_per_sec": round(statistics.mean(tps), 2) if tps else None,
        "avg_input_tokens": round(statistics.mean([m["input_tokens"] for m in sm]), 1) if sm else None,
        "avg_output_tokens": round(statistics.mean([m["output_tokens"] for m in sm]), 1) if sm else None,
        "avg_model_calls": round(statistics.mean([m["model_calls"] for m in sm]), 2) if sm else None,
        "avg_cost_inr_per_request": round(statistics.mean(inr), 4) if inr else None,
        "fully_grounded_share": round(sum(1 for r in ok if r.get("fully_grounded")) / len(ok), 4) if ok else None,
        "ai_status_counts": {k: sum(1 for r in ok if r.get("ai_status") == k) for k in {r.get("ai_status") for r in ok}},
        "models": models,
        "pricing": {"note": "cost = measured tokens x price table in moneytrace/config.py", "checked_on": PRICES_CHECKED_ON,
                    "usd_to_inr": s.usd_to_inr, "usd_to_inr_source": s.usd_to_inr_source,
                    "prices_usd_per_1m": {m: (s.price_for(m).__dict__ if s.price_for(m) else "not configured") for m in models}},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("MONEYTRACE_BASE_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--poll-timeout", type=float, default=600)
    ap.add_argument("--victim-email", default="victim@moneytrace.in")
    ap.add_argument("--victim-password", default=os.environ.get("DEMO_VICTIM_PASSWORD", "victim123"))
    ap.add_argument("--operator-email", default="operator@moneytrace.in")
    ap.add_argument("--operator-password", default=os.environ.get("DEMO_OPERATOR_PASSWORD", "operator123"))
    args = ap.parse_args()
    args.run_id = datetime.now(timezone.utc).strftime("LOAD_%Y%m%dT%H%M%SZ")
    rows, wall = asyncio.run(run(args))
    out = os.path.join(BACKEND, "results", "load", args.run_id)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "requests.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = summarise(rows, args, wall)
    json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=2, ensure_ascii=False)
    json.dump({**summary, "run_dir": os.path.relpath(out, BACKEND)}, open(os.path.join(BACKEND, "results", "load", "latest.json"), "w"), indent=2)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
