# Superseded load-test run (kept for transparency)

24 requests, concurrency 4, local server, NVIDIA dev models. It exposed two problems:
- 3 requests (i = 7, 17, 22) ran into a ReAct loop: 150-166 model calls each, ~20 million input tokens resent as the
  context grew, until the 240 s agent timeout; the guard then completed those cases with rules.
- 4 requests at start-up failed in the agents with HTTP 429 (NVIDIA rate limit) and fell back to rules.

Fix: a per-case model-call budget (MAX_LLM_CALLS_PER_CASE=40) enforced in the ADK plugin, which also covers the
AgentTool sub-agents. Results after the fix are in the next LOAD_* directory. Do not quote this run's averages.
