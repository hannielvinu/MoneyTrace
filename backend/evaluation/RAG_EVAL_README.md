# RAG evaluation — how the numbers are produced and how to review them

## Files
| File | What it is |
|---|---|
| `evaluation/rag_golden.jsonl` | 100 victim questions (50 en / 25 hi / 25 ta, 8 fraud types). One JSON per line: `question`, `language`, `fraud_type`, `gold_doc_ids`, `source_chunk_id`, `reference_answer`, `review_status`. |
| `evaluation/build_rag_golden.py` | Drafts the questions from corpus passages with an LLM (`--append` tops the set up). |
| `evaluation/rag_eval.py` | Computes recall@5 and fully-grounded %; writes `results/rag_eval/<run_id>/`. |
| `evaluation/judge_agreement.py` | Agreement (and Cohen's κ) between the LLM judge and your 20 hand labels. |
| `evaluation/ci_gate.py` | CI regression gate on a 20-question subset. |

## Metric definitions
- **recall@5**: share of questions where at least one `gold_doc_ids` document appears among the documents of the
  top-5 retrieved chunks (hybrid pgvector + full-text, RRF, query translation for hi/ta/kn).
- **Fully grounded %** (reported): the production guidance agent answers the question (pre-fetched passages, grounding
  self-check, one regeneration, safe fallback). The FINAL answer is then audited by an **independent judge** - a different
  model with a claim-level rubric: every claim in every step needs a supporting sentence quoted from the step's cited
  passages, and each quote is **verified in code** to occur in the passage. An answer counts only if every step passes.
  Safe-fallback answers and errors count as not grounded.
- Also reported, for transparency: `pipeline_self_check_grounded_pct` (the pipeline's own checker; optimistic because the
  pipeline filters by it) and `draft_fully_grounded_pct` (the agent's first draft before any self-check).
- Why two judges: an answer filtered by judge A and scored by judge A is grounded by construction (an earlier run scored
  100 % this way; that number was discarded, see `results/rag_eval/preliminary/`).

## Your review (needed before the numbers go anywhere)
1. Open `rag_golden.jsonl` (any editor; one question per line).
2. For each question:
   - Is it something a victim would really ask? Fix the wording if not.
   - Look up `gold_doc_ids` in `rag/sources.yaml`: does that document answer it? Add every other `doc_id` that also
     answers it (e.g. both the commercial-bank and co-operative-bank liability circulars), remove wrong ones.
   - Set `"review_status": "reviewed"`.
3. Re-run `python -m evaluation.rag_eval`, then fill `human_fully_grounded (1/0)` in the run's `human_check.csv`
   (20 random answers: read each step and its cited passage; 1 only if every step is supported; the judge column is the
   independent auditor's verdict) and run
   `python -m evaluation.judge_agreement results/rag_eval/<run_id>`.
4. `python scripts/make_results.py` regenerates RESULTS.md.

## Known limitations (report them with the numbers)
- Questions were drafted from passages, which makes retrieval easier than for organically written questions.
- Gold labels start with a single document per question, so recall@5 is pessimistic until you add the other
  documents that also answer each question.
- Development runs used NVIDIA-hosted models (embeddings `nvidia/nemotron-3-embed-1b`, guidance/judge
  `nvidia/nemotron-3.5-lightning-30b-a3b`); production uses Gemini (`gemini-embedding-001`, Gemini Flash). Re-run with
  Gemini before quoting numbers.
