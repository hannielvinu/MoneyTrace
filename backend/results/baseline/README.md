# Phase 0 baseline (2026-11-21, UTC)

| File | Command | Outcome |
|---|---|---|
| `classifier_eval.log`, `classifier_metrics.json` | `python -X utf8 evaluation/generate_dataset.py && python -X utf8 evaluation/evaluator.py` | Reproduced: accuracy 86.50 %, macro-F1 87.37 %, binary F1 94.83 % on 400 held-out rows (run `RUN_20261121_184701_f1229c`) |
| `acceptance_test.log` | `python -X utf8 test_acceptance.py` against a local server | Steps 1–6 pass. Step 7 fails at `assert status == "GEMINI LIVE"` because no Gemini key is configured in this environment |
| — | `python -m pytest -q` | 29 passed (new `tests_v2/` + existing parser and voice suites) |

The two voice tests that failed at first relied on a real `SARVAM_API_KEY` from a developer `.env`, even though they mock the HTTP call. They now patch a dummy key.
