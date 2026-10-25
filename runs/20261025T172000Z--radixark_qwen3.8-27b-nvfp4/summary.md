# qwen3.8-27b — 20261025T172000Z--radixark_qwen3.8-27b-nvfp4

- Recipe: `RadixArk_Qwen3.8-27B-NVFP4.yml`
- Container: `lmsysorg/sglang@sha256:febfb971c7352570fc445c466ebd6ffc9d896024958e544a60f2137fd85856b1`
- sparkrun: 0.4.1; harness commit: 58ba17a9ec04ca573ccbee86daa79cd761308075

## Phases

| Phase | Status | Duration (s) | Error |
|---|---|---:|---|
| performance | partial | 10978 | cells: d259968c1:partial, d259968c2:4 failed requests, d259968c4:9 failed requests |
| tools | ok | 6394 |  |

## Prefill pp tok/s (aggregate)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 208 | 209 | 87 |
| 259968 | 690† | 98* | 47* |

## Decode tg tok/s (aggregate across concurrent requests)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 24.1 | 38.7 | 7.2 |
| 259968 | 15.8† | 18.9* | 7.6* |

## Decode tg tok/s per request

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 24.1 | 20.1 | 5.8 |
| 259968 | 15.8† | 18.9* | 14.9* |

## TTFT (ttfr, ms)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 9872 | 19528 | 60304 |
| 259968 | 376974† | 20849* | 392318* |

† context-load row only: every measured request in the cell failed, so the value is llama-benchy's context-load phase (prefill of the full depth, decode on that context).
\* some requests in the cell failed; the value averages only the requests that succeeded.

### Request errors

| depth | conc | failed requests | first error |
|---:|---:|---:|---|
| 259968 | 1 | 3 | HTTP 400: {"object":"error","message":"Requested token count exceeds the model's maximum context length of 262144 tokens. You requested a total of 262145 tokens: <redacted> tokens from the input messages and 128 tokens for the completion. Pleas |
| 259968 | 2 | 4 | HTTP 400: {"object":"error","message":"Requested token count exceeds the model's maximum context length of 262144 tokens. You requested a total of 262146 tokens: <redacted> tokens from the input messages and 128 tokens for the completion. Pleas |
| 259968 | 4 | 9 | HTTP 400: {"object":"error","message":"Requested token count exceeds the model's maximum context length of 262144 tokens. You requested a total of 262146 tokens: <redacted> tokens from the input messages and 128 tokens for the completion. Pleas |

## Tool calling (tool-eval-bench)

| Score | Rating | Deployability | Responsiveness | Points | Scenarios | Pass | Partial | Fail | Trials |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 92 | ★★★★★ Excellent | 75 | 35 | 179/194 | 97 | 85 | 9 | 3 | 3 |

Pass/partial/fail count the scenario rows of the last trial; the score aggregates all trials.

Trials: 3; final score mean 91.7 ± 0.6 (median 92.0, 95% CI [91.0, 92.0]); points mean 178 ± 1.7; pass@k 89.7%, pass^k 83.5%, reliability gap 6.2.
