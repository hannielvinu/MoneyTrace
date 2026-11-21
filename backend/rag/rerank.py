"""
Optional LLM reranker (RAG_RERANK=1).

The LLM gives each candidate passage a 0-3 relevance grade for the query; the
final order is by grade, ties broken by the original RRF order. Off by default:
evaluation/rag_eval.py measures recall@5 with and without it, and it is only
enabled if it helps.
"""

import json
import logging
import re
from typing import Dict, List

logger = logging.getLogger("moneytrace.rag.rerank")

PROMPT = """You grade search results for a scam-victim help desk in India.
Query: {query}

For each passage, output how useful it is for answering the query:
3 = directly answers it, 2 = clearly relevant, 1 = loosely related, 0 = irrelevant.
Return ONLY a JSON object mapping passage number to grade, e.g. {{"1": 3, "2": 0}}.

{passages}"""


def llm_rerank(query: str, items: List[Dict]) -> List[Dict]:
    from moneytrace.llm import generate_text
    passages = "\n\n".join(f"[{i}] {it['title']}\n{it['text'][:700]}" for i, it in enumerate(items, 1))
    try:
        res = generate_text(PROMPT.format(query=query, passages=passages), agent="reranker", json_mode=True)
        m = re.search(r"\{.*\}", res.text, re.S)
        grades = {int(k): float(v) for k, v in json.loads(m.group(0)).items()} if m else {}
    except Exception as e:
        logger.warning(f"rerank failed, keeping RRF order: {e}")
        return items
    for i, it in enumerate(items, 1):
        it["rerank_score"] = grades.get(i, 0.0) + it["rrf_score"]  # rrf (<0.04) only breaks ties
    return sorted(items, key=lambda it: it["rerank_score"], reverse=True)
