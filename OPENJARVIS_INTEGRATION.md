# OpenJarvis staged integration

The current phone backend remains active. The isolated OpenJarvis candidate is
implemented and tested, but it has not passed the migration comparison.

## What is connected

`openjarvis_bridge.plan` runs the pinned upstream `OrchestratorAgent` and
`OllamaEngine` in `.tools/openjarvis-env`. Source revision:
`309a4f1044ccfb2032264832a31fef2f1d314586`, under `.tools/openjarvis-review`.
The candidate proposes calendar, web and archive requests through a tool interface.
The existing dialogue executor still owns validation and actual tool execution.
Ordinary conversation is returned directly. Existing six-turn context and
calendar focus/clarification state are passed into both planners identically.

This is the first compatibility stage, not unrestricted multi-step autonomy.
OpenJarvis memory extraction, scheduling, skills, shell/browser tools and cloud
providers are not activated. Android capture, AWS retention, Google credentials,
raw recordings and speech playback stay with the existing implementation.

Each candidate request allows at most two model calls, 650 output tokens per
call and an 8192-token context. The parent imposes a 145-second worker timeout.
Both backends use local qwen2.5:14b and the shared GPU lock. Multiple action
proposals are rejected. Candidate failure never triggers a second backend or
replays a potentially completed action.

## Comparison on 2026-09-25

| Measured on ten synthetic turns | Current | OpenJarvis candidate |
|---|---:|---:|
| Acceptance cases passed | 10/10 | 8/10 |
| Reported prompt + completion tokens | 10,495 | 13,328 |
| Total measured wall time | 32.44 s | 39.55 s |

The candidate used approximately 27% more tokens overall. Ordinary chat used
fewer tokens; action proposals usually needed an extra model turn. These are
local Ollama token counts, not cloud charges. Timings include model/cache and
background contention effects; this small, single-run suite is not a general
benchmark. Real web/archive inference and speech synthesis were excluded.

Cases covered personal disclosure and follow-up, calendar create/move/cancel,
missing times, negation, web routing, yesterday's recorded history and literal
repetition. Calendar writes targeted a temporary fake, and web/archive tools
returned synthetic results. No real Google events or messages were changed.

Remaining candidate failures:

- Cancel it: the engine returned neither a usable answer nor a tool call.
- Yesterday's archive: the proposal omitted its date, selecting the current
  day through the existing executor's default. It therefore failed acceptance.

An initial run also exposed omitted unused arguments. The adapter now supplies
empty strings/zero only for absent optional fields; it does not invent dates or
times. The initial evaluator treated chat/clarify as distinct despite identical
execution semantics; that overly strict check was corrected before the final
comparison. Initial and final raw reports remain in private `jarvis-data`.

## Reproduce and switch

Run `setup-openjarvis.ps1` to prepare the isolated pinned runtime. Run:

```powershell
.venv/Scripts/python.exe receiver/compare_backends.py
.tools/openjarvis-env/Scripts/python.exe receiver/openjarvis_worker_checks.py
.venv/Scripts/python.exe -m unittest discover -s receiver
```

The live receiver reads `jarvis-data/agent-backend.json` on each request:
`{"backend":"current"}` keeps the current planner;
`{"backend":"openjarvis"}` selects the candidate. Removing the file also selects
current. Existing sessions and the phone protocol are preserved. Do not switch
the default until follow-up correctness matches the baseline and the added cost
is justified by a useful new capability. The next work is date-complete tool
proposals, reliable cancellation, then memory/research tools evaluated separately.
