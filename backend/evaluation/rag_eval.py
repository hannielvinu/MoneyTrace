"""
RAG evaluation: recall@5 and fully-grounded % on evaluation/rag_golden.jsonl.

    python -m evaluation.rag_eval                 # full set
    python -m evaluation.rag_eval --subset 20     # CI gate subset
    python -m evaluation.rag_eval --retrieval-only

recall@5        share of questions with at least one gold doc_id among the top-5 retrieved chunks' documents.
fully grounded  share of answers (production guidance agent + grounding check) in which EVERY final step is
                supported by a cited retrieved chunk, as judged by an LLM judge with a strict rubric
                (moneytrace/agents/guidance.py JUDGE_PROMPT). Safe-fallback answers count as NOT grounded.

Outputs (results/rag_eval/<run_id>/): per_question.jsonl, summary.json, human_check.csv (20 random answers for
the human judge-agreement check; fill the `human_fully_grounded` column with 1/0 and run
`python -m evaluation.judge_agreement <run_dir>`).
"""
import argparse
import asyncio
import csv
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BACKEND, ".env"))


def load_golden(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def recall_at_k(rows, k=5, rerank=None, translate=None):
    from rag.retriever import retrieve, RetrievalTrace
    out = []
    for r in rows:
        tr = RetrievalTrace(r["question"])
        cites = retrieve(r["question"], k=k, trace=tr, rerank=rerank, translate=translate)
        docs = [c.doc_id for c in cites]
        hit = any(d in docs for d in r["gold_doc_ids"])
        rank = next((i + 1 for i, d in enumerate(docs) if d in r["gold_doc_ids"]), None)
        out.append({"id": r["id"], "hit": hit, "first_gold_rank": rank, "retrieved_doc_ids": docs,
                    "retrieved_chunk_ids": [c.chunk_id for c in cites], "latency_ms": round(tr.latency_ms, 1)})
    return out


async def grounded_eval(rows, concurrency=3):
    from moneytrace.agents.coordinator import run_guidance_only
    from moneytrace.telemetry import start_request
    sem = asyncio.Semaphore(concurrency)
    results = {}

    async def one(r):
        async with sem:
            m = start_request(None)
            t0 = time.perf_counter()
            try:
                g = await asyncio.wait_for(run_guidance_only(r["question"], r["language"], r.get("fraud_type", "")), 400)
                g["error"] = None
            except Exception as e:
                g = {"steps": [], "sources": [], "grounding": {"fully_grounded": False, "fallback_used": True},
                     "error": f"{type(e).__name__}: {str(e)[:200]}"}
            g["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            g["tokens"] = m.summary()
            results[r["id"]] = g
            print(f"  {r['id']} grounded={g['grounding'].get('fully_grounded')} steps={len(g['steps'])} "
                  f"{'ERR ' + g['error'][:60] if g['error'] else ''}", flush=True)
    await asyncio.gather(*(one(r) for r in rows))
    return results


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default=os.path.join(HERE, "rag_golden.jsonl"))
    ap.add_argument("--subset", type=int, default=0, help="evaluate a fixed, seeded subset (CI gate)")
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--rerank", action="store_true", help="also measure recall@5 with the LLM reranker")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--ablation", action="store_true", help="also measure recall@5 without query translation")
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args(argv)

    rows = load_golden(args.golden)
    if args.subset:
        rows = random.Random(args.seed).sample(rows, min(args.subset, len(rows)))
    run_id = datetime.now(timezone.utc).strftime("RAG_%Y%m%dT%H%M%SZ") + (f"_subset{args.subset}" if args.subset else "")
    out_dir = os.path.join(BACKEND, "results", "rag_eval", run_id)
    os.makedirs(out_dir, exist_ok=True)

    from moneytrace.db.database import get_engine
    from rag import store
    from moneytrace.llm import model_for, provider
    with get_engine().connect() as conn:
        meta, corpus = store.get_meta(conn), store.corpus_stats(conn)

    t0 = time.time()
    rec = recall_at_k(rows)
    recall = sum(r["hit"] for r in rec) / len(rec)
    by_lang = {}
    for g, r in zip(rows, rec):
        by_lang.setdefault(g["language"], []).append(r["hit"])
    summary = {
        "run_id": run_id, "date_utc": datetime.now(timezone.utc).isoformat(), "command": " ".join(["python -m evaluation.rag_eval"] + (argv or sys.argv[1:])),
        "eval_set": os.path.relpath(args.golden, BACKEND), "eval_set_size": len(rows),
        "review_status": sorted({g.get("review_status", "unknown") for g in rows}),
        "corpus": {"documents": corpus["documents"], "chunks": corpus["chunks"]},
        "embedding_model": meta.get("embedding_model"), "llm_provider": provider(),
        "guidance_model": model_for("strong"), "judge_model": model_for("judge"),
        "recall_at_5": round(recall, 4), "recall_at_5_hits": sum(r["hit"] for r in rec),
        "recall_at_5_by_language": {k: round(sum(v) / len(v), 4) for k, v in by_lang.items()},
        "mean_retrieval_latency_ms": round(sum(r["latency_ms"] for r in rec) / len(rec), 1),
    }
    if args.ablation:
        nt = recall_at_k(rows, translate=False)
        summary["recall_at_5_without_query_translation"] = round(sum(r["hit"] for r in nt) / len(nt), 4)
    if args.rerank:
        rr = recall_at_k(rows, rerank=True)
        summary["recall_at_5_with_rerank"] = round(sum(r["hit"] for r in rr) / len(rr), 4)
    print(f"recall@5 = {summary['recall_at_5']} ({summary['recall_at_5_hits']}/{len(rows)})")

    gres = {}
    if not args.retrieval_only:
        gres = asyncio.run(grounded_eval(rows, args.concurrency))
        ok = [g for g in gres.values() if not g.get("error")]
        grounded = sum(1 for g in gres.values() if g["grounding"].get("fully_grounded"))
        summary.update({
            "fully_grounded_pct": round(100 * grounded / len(rows), 2), "fully_grounded_count": grounded,
            "answers_with_errors": len(rows) - len(ok),
            "safe_fallback_count": sum(1 for g in gres.values() if g["grounding"].get("fallback_used")),
            "mean_final_steps": round(sum(len(g["steps"]) for g in gres.values()) / len(rows), 2),
            "mean_guidance_latency_ms": round(sum(g["latency_ms"] for g in gres.values()) / len(rows), 1),
        })
        print(f"fully grounded = {summary['fully_grounded_pct']}% ({grounded}/{len(rows)})")
    summary["duration_s"] = round(time.time() - t0, 1)

    with open(os.path.join(out_dir, "per_question.jsonl"), "w", encoding="utf-8") as f:
        for g, r in zip(rows, rec):
            row = {**g, "retrieval": r}
            if g["id"] in gres:
                x = gres[g["id"]]
                row["answer"] = {"steps": x["steps"], "sources": x["sources"], "grounding": x["grounding"],
                                 "error": x.get("error"), "latency_ms": x["latency_ms"], "tokens": x.get("tokens")}
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    if gres:
        sample = random.Random(20).sample(rows, min(20, len(rows)))
        with open(os.path.join(out_dir, "human_check.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "question", "final_steps_with_citations", "cited_passages", "judge_fully_grounded",
                        "human_fully_grounded (1/0)", "human_notes"])
            for g in sample:
                x = gres[g["id"]]
                steps = "\n".join(f"{i}. {s['text']} {s.get('citations')}" for i, s in enumerate(x["steps"], 1))
                from moneytrace.agents.guidance import load_chunks
                ch = load_chunks([c for s in x["steps"] for c in s.get("citations", [])])
                passages = "\n\n".join(f"[{k}] {v['title']}: {v['text'][:800]}" for k, v in ch.items())
                w.writerow([g["id"], g["question"], steps, passages, int(bool(x["grounding"].get("fully_grounded"))), "", ""])
    latest = os.path.join(BACKEND, "results", "rag_eval", "latest_subset.json" if args.subset else "latest.json")
    with open(latest, "w", encoding="utf-8") as f:
        json.dump({**summary, "run_dir": os.path.relpath(out_dir, BACKEND)}, f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    main()
