# qwen3.8-27b — 20261025T172000Z--radixark_qwen3.8-27b-nvfp4

> **Note:** Depth 259840 was re-run on 2026-10-26T02:27:07+00:00 with `--rerun-perf-depth` (rerun-20261025T221614Z/) and merged here. It replaces depth(s) [259968]; their raw data is kept under superseded/.

- Recipe: `RadixArk_Qwen3.8-27B-NVFP4.yml`
- Container: `lmsysorg/sglang@sha256:febfb971c7352570fc445c466ebd6ffc9d896024958e544a60f2137fd85856b1`
- sparkrun: 0.4.1; harness commit: 58ba17a9ec04ca573ccbee86daa79cd761308075

## Phases

| Phase | Status | Duration (s) | Error |
|---|---|---:|---|
| performance | ok | 10978 |  |
| tools | ok | 6394 |  |
| performance (rerun-20261025T221614Z, depth 259840) | ok | 15050 |  |

## Prefill pp tok/s (aggregate)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 208 | 209 | 87 |
| 259840 | 101 | 8 | 6 |

## Decode tg tok/s (aggregate across concurrent requests)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 24.1 | 38.7 | 7.2 |
| 259840 | 15.4 | 0.6 | 0.4 |

## Decode tg tok/s per request

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 24.1 | 20.1 | 5.8 |
| 259840 | 15.4 | 16.2 | 17.2 |

## TTFT (ttfr, ms)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 9872 | 19528 | 60304 |
| 259840 | 20248 | 337463 | 849673 |

† context-load row only: every measured request in the cell failed, so the value is llama-benchy's context-load phase (prefill of the full depth, decode on that context).
\* some requests in the cell failed; the value averages only the requests that succeeded.

## Tool calling (tool-eval-bench)

| Score | Rating | Deployability | Responsiveness | Points | Scenarios | Pass | Partial | Fail | Trials |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 92 | ★★★★★ Excellent | 75 | 35 | 179/194 | 97 | 85 | 9 | 3 | 3 |

Pass/partial/fail count the scenario rows of the last trial; the score aggregates all trials.

Trials: 3; final score mean 91.7 ± 0.6 (median 92.0, 95% CI [91.0, 92.0]); points mean 178 ± 1.7; pass@k 89.7%, pass^k 83.5%, reliability gap 6.2.
