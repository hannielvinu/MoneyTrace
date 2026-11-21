# Load-test runs (local server, NVIDIA dev models, 24 requests, concurrency 4)

| Run | Change being tested | Intake p95 | Time to guidance p50 / p95 | Live agents |
|---|---|---|---|---|
| `LOAD_20261121T223052Z_before_call_budget` | first run | 3.2 s | 38.4 s / 242.1 s | 17/24 (3 runaway loops, 4 rate-limited) |
| `LOAD_20261121T224200Z` | + per-case model-call budget | 3.9 s | 39.8 s / 50.5 s | 24/24 |
| `LOAD_20261121T225406Z` | + async search_advisories tool | 4.0 s | 45.5 s / 59.5 s | 18/24 (NVIDIA 429s) |
| `LOAD_20261121T225909Z` (**latest**) | + agent-stack warm-up at start-up | 0.68 s | 47.5 s / 60.0 s | 21/24 (NVIDIA 429s) |

Run-to-run variance in time-to-guidance comes mostly from the free NVIDIA endpoint (rate limits, queueing).
The intake p95 drop is the cold-start fix: the first requests no longer wait for the agent stack to import.
Exact numbers: each run's `summary.json`; per-request rows: `requests.jsonl`.
