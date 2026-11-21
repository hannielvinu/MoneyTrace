# Preliminary RAG runs (not reported)

- `RAG_20261121T213631Z`, `RAG_20261121T213705Z`: retrieval-only runs on the first 65 drafted questions
  (`/tmp` copy of the golden set) used while adding query translation (recall@5 0.7385 → 0.7538).
- `RAG_20261121T214728Z_selfjudge_only`: full 100-question run where grounding was scored by the same judge that
  filters the answer. It reported 100 % "fully grounded", which is circular (answers are grounded by construction
  under that judge). It also showed that first drafts cited placeholder ids (only 5/411 draft steps supported).
  Fixed by pre-fetching passages for the guidance agent and scoring with an independent, quote-verified auditor.
  Kept for transparency; do not quote these numbers.
