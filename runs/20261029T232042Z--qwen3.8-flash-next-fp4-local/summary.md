# nvidia/Qwen3.8-Flash-Next-FP4-Local — 20261029T232042Z--qwen3.8-flash-next-fp4-local

- Recipe: `Qwen3.8-Flash-Next-FP4-Local.yml`
- Container: `eugr/spark-vllm-b12x@sha256:57c24fc397c66d4d28a7d0d5f1d792934fd01a70f4574cff6315fb7bc329d5cb`
- sparkrun: 0.4.1; harness commit: 291f18a9b507218342077c38169c1d68de70466c

## Phases

| Phase | Status | Duration (s) | Error |
|---|---|---:|---|
| performance | ok | 4348 |  |
| tools | ok | 5329 |  |

## Resources

Unified memory (GiB, from /proc/meminfo; GB10 shares CPU/GPU memory, so this is the true headroom).

| Total | Baseline used | After load | Model footprint | Peak used | Min available |
|---:|---:|---:|---:|---:|---:|
| 121.7 | 4.0 | 103.7 | 99.7 | 104.3 | 17.4 |

| Phase | Peak used | Min available | Container peak | GPU util mean % | Power max W | Temp max °C | Samples |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 4.1 | 117.6 | — | 0.0 | 11.8 | 47 | 3 |
| preflight | 4.1 | 117.6 | — | 0.0 | 5.2 | 46 | 1 |
| performance | 104.3 | 17.4 | 9.7 | 80.6 | 90.0 | 80 | 431 |
| tools | 104.1 | 17.6 | 8.7 | 93.3 | 46.6 | 75 | 529 |
| after-stop | 4.1 | 117.6 | — | 0.0 | 16.4 | 67 | 1 |

Server log: kv_tokens=929241, kv_max_concurrency={'tokens_per_request': 262144, 'x': 3.54}, weights_gib=70.04, kv_usage_peak_pct=65.8, preemptions=0, retractions=0, max_waiting_requests=3

Config: `runtime`=vllm-distributed, `container`=eugr/spark-vllm-b12x@sha256:57c24fc397c66d4d28a7d0d5f1d792934fd01a70f4574cff6315fb7bc329d5cb, `gpu_memory_utilization`=0.8, `max_model_len`=262144, `max_num_seqs`=8, `max_num_batched_tokens`=4096, `tensor_parallel`=1, `num_speculative_tokens`=4, `--gpu-memory-utilization`=0.8, `--max-num-seqs`=8, `--max-model-len`=262144

## At a glance

| metric, depth | c1 | c2 | c4 |
|---|---:|---:|---:|
| Aggregate decode tok/s, 65536 | 31.7 | 48.6 | 55.9 |
| Aggregate decode tok/s, 259840 | 37.8 | 49.0 | 3.5 |
| Per-request decode tok/s, 65536 | 31.7 | 24.9 | 16.7 |
| Per-request decode tok/s, 259840 | 37.8 | 26.6 | 15.5 |
| Prefill tok/s, 65536 | 1374 | 1461 | 1600 |
| Prefill tok/s, 259840 | 864 | 986 | 57 |

Aggregate decode counts the whole batch window, including time requests spend queued or prefilling; per-request decode is the speed one user sees once tokens flow.

## Prefill pp tok/s (aggregate)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 1374 | 1461 | 1600 |
| 259840 | 864 | 986 | 57 |

## Decode tg tok/s (aggregate across concurrent requests)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 31.7 | 48.6 | 55.9 |
| 259840 | 37.8 | 49.0 | 3.5 |

## Decode tg tok/s per request

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 31.7 | 24.9 | 16.7 |
| 259840 | 37.8 | 26.6 | 15.5 |

## TTFT (ttfr, ms)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 1492 | 2749 | 4732 |
| 259840 | 2372 | 4068 | 39962 |

† context-load row only: every measured request in the cell failed, so the value is llama-benchy's context-load phase (prefill of the full depth, decode on that context).
\* some requests in the cell failed; the value averages only the requests that succeeded.

## Tool calling (tool-eval-bench)

| Score | Rating | Deployability | Responsiveness | Points | Scenarios | Pass | Partial | Fail | Trials |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 90 | ★★★ Adequate (safety-capped) | 76 | 44 | 175/194 | 97 | 83 | 9 | 5 | 3 |

Pass/partial/fail count the scenario rows of the last trial; the score aggregates all trials.

Trials: 3; final score mean 90 ± 1.0 (median 90.0, 95% CI [89.0, 91.0]); points mean 174.3 ± 2.1; pass@k 88.7%, pass^k 77.3%, reliability gap 11.4.
