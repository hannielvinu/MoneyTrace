"""
Draft the RAG golden set (evaluation/rag_golden.jsonl) from the ingested corpus.

For each target (fraud type x language) the script retrieves candidate passages
for that fraud type, picks one not used before, and asks an LLM to write the
question a real victim would ask that this passage answers, plus a short
reference answer. The passage's document is the initial gold doc_id.

Every row is written with "review_status": "draft". Hanniel must review the
gold doc_ids (add other documents that also answer the question, remove wrong
ones) before the numbers are reported; see evaluation/RAG_EVAL_README.md.

Known bias, reported with the metric: questions are drafted from a passage, so
retrieval of that passage is easier than for organically written questions.
The prompt asks for plain victim language (no copied phrases) to reduce this.

    python -m evaluation.build_rag_golden --n 100
"""

import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BACKEND, ".env"))

FRAUD_TYPES = {
    "fake_kyc": "fake KYC update call / SMS / link that leads to money loss",
    "upi_collect": "wrong UPI collect request or 'enter PIN to receive money' / QR code scam",
    "otp_screen_share": "OTP sharing, screen-sharing or remote-access app scam",
    "fake_customer_care": "fake customer care / helpline number found online, refund scam",
    "investment_task": "investment, trading app or part-time task scam on WhatsApp / Telegram",
    "reporting_liability": "unauthorised debit: how and when to report, zero / limited customer liability, bank complaint",
    "impersonation_rbi": "fraud emails, calls or offers in the name of RBI / government, lottery or fictitious offers",
    "digital_arrest_loan": "digital arrest by fake police/CBI, or loan app harassment",
}
# 100 questions: 50 English, 25 Hindi, 25 Tamil, spread over the fraud types
LANG_PLAN = ["en"] * 50 + ["hi"] * 25 + ["ta"] * 25
LANG_NAMES = {"en": "English", "hi": "Hindi (Devanagari script, natural spoken style; Hinglish words are fine)",
              "ta": "Tamil (Tamil script, natural spoken style)"}

PROMPT = """You help build an evaluation set for a scam-victim help desk in India.

PASSAGE (from "{title}", {issuer}):
\"\"\"{text}\"\"\"

Write ONE question that a real {fraud_desc} victim (or someone about to be scammed) would type into a help desk,
which this passage answers. Rules:
- Write the question in {language}.
- Use plain everyday words and the victim's own situation; do NOT copy distinctive phrases from the passage.
- The question must be answerable from the passage alone.
Also write a 1-2 sentence reference answer in English, using only the passage.
If the passage cannot answer any realistic victim question, return {{"usable": false}}.

Return ONLY JSON: {{"usable": true, "question": "...", "reference_answer": "..."}}"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default=os.path.join(HERE, "rag_golden.jsonl"))
    args = ap.parse_args(argv)

    from rag.retriever import retrieve
    from moneytrace.llm import generate_json, model_for

    rng = random.Random(args.seed)
    langs = LANG_PLAN[: args.n]
    rng.shuffle(langs)
    types = list(FRAUD_TYPES)
    pools = {}
    for t, desc in FRAUD_TYPES.items():
        pools[t] = [c for c in retrieve(desc, k=20)]
        rng.shuffle(pools[t])
    # Plan (fraud type, passage) pairs round-robin, then draft questions in parallel.
    plan, used = [], set()
    depth = 0
    while len(plan) < args.n * 2 and depth < 20:
        for t in types:
            pool = [c for c in pools[t] if c.chunk_id not in used]
            if pool:
                used.add(pool[0].chunk_id)
                plan.append((t, pool[0]))
        depth += 1

    def draft(item):
        t, c, lang = item
        try:
            out = generate_json(PROMPT.format(title=c.title, issuer=c.issuer, text=c.text[:2400],
                                              fraud_desc=FRAUD_TYPES[t], language=LANG_NAMES[lang]),
                                tier="strong", agent="golden_builder", temperature=0.4, max_tokens=4000)
        except Exception as e:
            return None
        if not out.get("usable") or not out.get("question"):
            return None
        return {"question": out["question"].strip(), "language": lang, "fraud_type": t, "gold_doc_ids": [c.doc_id],
                "source_chunk_id": c.chunk_id, "reference_answer": out.get("reference_answer", "").strip(),
                "drafted_by": model_for("strong"), "review_status": "draft"}

    from concurrent.futures import ThreadPoolExecutor
    rows = []
    cursor = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        while len(rows) < args.n and cursor < len(plan):
            need = args.n - len(rows)
            batch = plan[cursor: cursor + need]
            cursor += len(batch)
            items = [(t, c, langs[(len(rows) + j) % len(langs)]) for j, (t, c) in enumerate(batch)]
            for r in ex.map(draft, items):
                if r and len(rows) < args.n:
                    rows.append(r)
            print(f"{len(rows)}/{args.n} drafted", flush=True)
    # re-balance languages to the plan exactly (50/25/25) is not guaranteed after skips; report actual mix
    for k, r in enumerate(rows, 1):
        r["id"] = f"q{k:03d}"
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    from collections import Counter
    print(f"wrote {len(rows)} questions to {args.out}; languages={dict(Counter(r['language'] for r in rows))}; "
          f"types={dict(Counter(r['fraud_type'] for r in rows))}")


if __name__ == "__main__":
    main()
