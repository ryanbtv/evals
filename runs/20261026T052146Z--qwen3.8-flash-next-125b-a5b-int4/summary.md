# azampatti/Qwen3.8-Flash-Next-125B-A5B-INT4-AutoRound — 20261026T052146Z--qwen3.8-flash-next-125b-a5b-int4

- Recipe: `Qwen3.8-Flash-Next-125B-A5B-INT4.yml`
- Container: `eugr/spark-vllm-b12x@sha256:8e7e062186f841453ef0ec6f713043c5b65447decc3835206685128c18e42262`
- sparkrun: 0.4.1; harness commit: 80420a5d872d806d2839d15451759df6c4bdef17

## Phases

| Phase | Status | Duration (s) | Error |
|---|---|---:|---|
| performance | ok | 6971 |  |
| tools | ok | 3696 |  |

## Resources

Unified memory (GiB, from /proc/meminfo; GB10 shares CPU/GPU memory, so this is the true headroom).

| Total | Baseline used | After load | Model footprint | Peak used | Min available |
|---:|---:|---:|---:|---:|---:|
| 121.7 | 4.0 | 108.9 | 104.9 | 108.9 | 12.8 |

| Phase | Peak used | Min available | Container peak | GPU util mean % | Power max W | Temp max °C | Samples |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 4.0 | 117.7 | — | 0.0 | 5.4 | 52 | 3 |
| preflight | 4.0 | 117.7 | — | 0.0 | 5.3 | 52 | 1 |
| performance | 108.9 | 12.8 | 9.1 | 91.1 | 94.4 | 83 | 691 |
| tools | 108.6 | 13.0 | 9.2 | 92.9 | 65.0 | 78 | 367 |
| after-stop | 4.0 | 117.6 | — | 0.0 | 16.3 | 66 | 1 |

Server log: kv_tokens=328932, kv_max_concurrency={'tokens_per_request': 262144, 'x': 1.25}, weights_gib=73.92, kv_cache_gib=9.31, kv_usage_peak_pct=96.3, preemptions=0, retractions=0, max_waiting_requests=3

Config: `runtime`=vllm-distributed, `container`=eugr/spark-vllm-b12x@sha256:8e7e062186f841453ef0ec6f713043c5b65447decc3835206685128c18e42262, `gpu_memory_utilization`=0.01, `kv_cache_bytes`=10g, `kv_cache_dtype`=auto, `max_model_len`=262144, `max_num_seqs`=8, `max_num_batched_tokens`=8192, `tensor_parallel`=1, `num_speculative_tokens`=4, `--gpu-memory-utilization`=0.01, `--kv-cache-memory-bytes`=10g, `--max-num-seqs`=8, `--max-model-len`=262144

## At a glance

| metric, depth | c1 | c2 | c4 |
|---|---:|---:|---:|
| Aggregate decode tok/s, 65536 | 69.4 | 90.6 | 6.6 |
| Aggregate decode tok/s, 259840 | 60.6 | 1.5 | 1.0 |
| Per-request decode tok/s, 65536 | 69.4 | 47.4 | 17.6 |
| Per-request decode tok/s, 259840 | 60.6 | 60.9 | 59.1 |
| Prefill tok/s, 65536 | 685 | 748 | 75 |
| Prefill tok/s, 259840 | 455 | 17 | 15 |

Aggregate decode counts the whole batch window, including time requests spend queued or prefilling; per-request decode is the speed one user sees once tokens flow.

## Prefill pp tok/s (aggregate)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 685 | 748 | 75 |
| 259840 | 455 | 17 | 15 |

## Decode tg tok/s (aggregate across concurrent requests)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 69.4 | 90.6 | 6.6 |
| 259840 | 60.6 | 1.5 | 1.0 |

## Decode tg tok/s per request

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 69.4 | 47.4 | 17.6 |
| 259840 | 60.6 | 60.9 | 59.1 |

## TTFT (ttfr, ms)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 2993 | 5444 | 69223 |
| 259840 | 4503 | 181642 | 336842 |

† context-load row only: every measured request in the cell failed, so the value is llama-benchy's context-load phase (prefill of the full depth, decode on that context).
\* some requests in the cell failed; the value averages only the requests that succeeded.

## Tool calling (tool-eval-bench)

| Score | Rating | Deployability | Responsiveness | Points | Scenarios | Pass | Partial | Fail | Trials |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 93 | ★★★★★ Excellent | 80 | 50 | 178/192 | 97 | 85 | 8 | 4 | 3 |

Pass/partial/fail count the scenario rows of the last trial; the score aggregates all trials.

Trials: 3; final score mean 91 ± 2.0 (median 91.0, 95% CI [89.0, 93.0]); points mean 174 ± 4.0; pass@k 93.8%, pass^k 78.1%, reliability gap 15.7.
