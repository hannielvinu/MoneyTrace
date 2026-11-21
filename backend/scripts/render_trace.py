"""Render one trace from results/traces/spans*.jsonl (OTEL_EXPORTER=jsonl) as an indented tree in markdown.

    python scripts/render_trace.py [trace_id] > results/traces/sample_trace.md
Without a trace_id, picks the trace with the most spans (normally a report submission + agent pipeline).
"""
import collections
import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = os.environ.get("SPANS_FILE", os.path.join(BACKEND, "results", "traces", "spans_acceptance_run.jsonl"))
spans = [json.loads(l) for l in open(src, encoding="utf-8")]
tid = sys.argv[1] if len(sys.argv) > 1 else collections.Counter(s["trace_id"] for s in spans).most_common(1)[0][0]
ts = [s for s in spans if s["trace_id"] == tid and not s["name"].endswith((" http send", " http receive"))]
children = collections.defaultdict(list)
ids = {s["span_id"] for s in ts}
for s in ts:
    children[s["parent_id"] if s["parent_id"] in ids else None].append(s)
print(f"# Sample trace `{tid}`\n")
print("Captured with `OTEL_EXPORTER=jsonl` from a local acceptance-test run (same spans go to Cloud Trace with "
      "`OTEL_EXPORTER=gcp`). Durations in ms; `http send/receive` sub-spans omitted.\n")
print("```")


def walk(s, depth):
    a = s.get("attributes", {})
    extra = ""
    for k in ("gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens", "gen_ai.request.model", "gen_ai.tool.name"):
        if k in a:
            extra += f" {k.split('.')[-1]}={a[k]}"
    print(f"{'  ' * depth}{s['name']}  [{s['duration_ms']:.0f} ms]{extra}")
    for c in sorted(children[s["span_id"]], key=lambda x: x["start"]):
        walk(c, depth + 1)


for root in sorted(children[None], key=lambda x: x["start"]):
    walk(root, 0)
print("```")
