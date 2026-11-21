# Sample trace `a6915c545b0e18a8c1ee061c51cefce6`

Captured with `OTEL_EXPORTER=jsonl` from a local acceptance-test run (same spans go to Cloud Trace with `OTEL_EXPORTER=gcp`). Durations in ms; `http send/receive` sub-spans omitted.

```
POST /api/portal/reports  [16 ms]
  BackgroundTask run_investigation_pipeline  [271629 ms]
    moneytrace.pipeline  [271568 ms]
      coordinator  [39019 ms]
        invoke_workflow coordinator  [36046 ms]
          invoke_agent coordinator  [36038 ms]
            generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [1822 ms] input_tokens=570 output_tokens=480 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
            execute_tool intake_agent  [4107 ms] name=intake_agent
              invoke_workflow intake_agent  [4106 ms]
                invoke_agent intake_agent  [4101 ms]
                  generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [875 ms] input_tokens=1159 output_tokens=167 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
                  execute_tool get_report  [4 ms] name=get_report
                  generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [2674 ms] input_tokens=1367 output_tokens=716 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
                  execute_tool save_case_record  [11 ms] name=save_case_record
                  generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [515 ms] input_tokens=1988 output_tokens=53 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
            generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [996 ms] input_tokens=877 output_tokens=258 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
            execute_tool investigation_agent  [9942 ms] name=investigation_agent
              invoke_workflow investigation_agent  [9941 ms]
                invoke_agent investigation_agent  [9938 ms]
                  generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [1543 ms] input_tokens=1117 output_tokens=197 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
                  execute_tool lookup_transaction  [7 ms] name=lookup_transaction
                  generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [1540 ms] input_tokens=1373 output_tokens=173 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
                  execute_tool score_signals  [5 ms] name=score_signals
                  generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [419 ms] input_tokens=1624 output_tokens=41 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
                  execute_tool search_related_incidents  [10 ms] name=search_related_incidents
                  generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [5458 ms] input_tokens=2286 output_tokens=1298 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
                  execute_tool submit_assessment  [0 ms] name=submit_assessment
                  generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [922 ms] input_tokens=3218 output_tokens=104 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
            generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [902 ms] input_tokens=1142 output_tokens=172 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
            execute_tool guidance_agent  [17689 ms] name=guidance_agent
              invoke_workflow guidance_agent  [17687 ms]
                invoke_agent guidance_agent  [17684 ms]
                  generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [1367 ms] input_tokens=765 output_tokens=432 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
                  execute_tool search_advisories  [319 ms] name=search_advisories
                  generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [824 ms] input_tokens=2637 output_tokens=129 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
                  execute_tool search_advisories  [317 ms] name=search_advisories
                  generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [545 ms] input_tokens=4403 output_tokens=81 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
                  execute_tool search_advisories  [328 ms] name=search_advisories
                  generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [13953 ms] input_tokens=5963 output_tokens=4372 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
            generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [488 ms] input_tokens=1823 output_tokens=70 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
      guard  [0 ms]
      grounding_check  [232515 ms]
        invoke_workflow guidance_agent  [24148 ms]
          invoke_agent guidance_agent  [24134 ms]
            generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [11779 ms] input_tokens=1402 output_tokens=1258 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
            execute_tool search_advisories  [253 ms] name=search_advisories
            generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [742 ms] input_tokens=3689 output_tokens=153 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
            execute_tool search_advisories  [250 ms] name=search_advisories
            generate_content openai/nvidia/nemotron-3.5-lightning-30b-a3b  [11090 ms] input_tokens=5289 output_tokens=3341 model=openai/nvidia/nemotron-3.5-lightning-30b-a3b
```
