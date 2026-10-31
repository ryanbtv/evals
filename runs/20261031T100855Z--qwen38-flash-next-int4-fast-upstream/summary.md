# azampatti/Qwen3.8-Flash-Next-125B-A5B-INT4-AutoRound — 20261031T100855Z--qwen38-flash-next-int4-fast-upstream

- Recipe: `qwen38-flash-next-int4-fast-upstream.yml`
- Container: `eugr/spark-vllm-b12x@sha256:03a956544e9f9b4b7ba91690469fbe7848bdbef29a7d2e0f5788368467bb3595`
- sparkrun: 0.4.1; harness commit: 291f18a9b507218342077c38169c1d68de70466c-dirty

## Phases

| Phase | Status | Duration (s) | Error |
|---|---|---:|---|
| performance | ok | 5224 |  |
| tools | ok | 3618 |  |

## Resources

Unified memory (GiB, from /proc/meminfo; GB10 shares CPU/GPU memory, so this is the true headroom).

| Total | Baseline used | After load | Model footprint | Peak used | Min available |
|---:|---:|---:|---:|---:|---:|
| 121.7 | 4.6 | 110.2 | 105.7 | 110.6 | 11.1 |

| Phase | Peak used | Min available | Container peak | GPU util mean % | Power max W | Temp max °C | Samples |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 4.8 | 116.9 | — | 0.0 | 4.7 | 44 | 3 |
| preflight | 4.6 | 117.1 | — | 0.0 | 4.6 | 44 | 1 |
| performance | 110.6 | 11.1 | 18.7 | 80.8 | 85.8 | 83 | 517 |
| tools | 110.6 | 11.1 | 9.5 | 93.5 | 65.2 | 79 | 359 |
| after-stop | 4.1 | 117.6 | — | 0.0 | 16.4 | 67 | 1 |

Server log: kv_tokens=646666, kv_max_concurrency={'tokens_per_request': 262144, 'x': 2.47}, weights_gib=73.28, kv_cache_gib=18.63, kv_usage_peak_pct=80.9, preemptions=0, retractions=0, max_waiting_requests=3

Config: `runtime`=vllm-distributed, `container`=eugr/spark-vllm-b12x@sha256:03a956544e9f9b4b7ba91690469fbe7848bdbef29a7d2e0f5788368467bb3595, `gpu_memory_utilization`=0.01, `kv_cache_bytes`=20g, `kv_cache_dtype`=auto, `max_model_len`=262144, `max_num_seqs`=8, `max_num_batched_tokens`=8192, `tensor_parallel`=1, `num_speculative_tokens`=5, `--gpu-memory-utilization`=0.01, `--kv-cache-memory-bytes`=20g, `--max-num-seqs`=8, `--max-model-len`=262144

## At a glance

| metric, depth | c1 | c2 | c4 |
|---|---:|---:|---:|
| Aggregate decode tok/s, 65536 | 53.4 | 82.0 | 107.1 |
| Aggregate decode tok/s, 259840 | 60.0 | 79.2 | 1.5 |
| Per-request decode tok/s, 65536 | 53.4 | 44.4 | 31.5 |
| Per-request decode tok/s, 259840 | 60.0 | 43.2 | 17.3 |
| Prefill tok/s, 65536 | 915 | 1010 | 1085 |
| Prefill tok/s, 259840 | 635 | 752 | 21 |

Aggregate decode counts the whole batch window, including time requests spend queued or prefilling; per-request decode is the speed one user sees once tokens flow.

## Prefill pp tok/s (aggregate)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 915 | 1010 | 1085 |
| 259840 | 635 | 752 | 21 |

## Decode tg tok/s (aggregate across concurrent requests)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 53.4 | 82.0 | 107.1 |
| 259840 | 60.0 | 79.2 | 1.5 |

## Decode tg tok/s per request

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 53.4 | 44.4 | 31.5 |
| 259840 | 60.0 | 43.2 | 17.3 |

## TTFT (ttfr, ms)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 2242 | 3980 | 7449 |
| 259840 | 3231 | 5344 | 207018 |

† context-load row only: every measured request in the cell failed, so the value is llama-benchy's context-load phase (prefill of the full depth, decode on that context).
\* some requests in the cell failed; the value averages only the requests that succeeded.

## Tool calling (tool-eval-bench)

| Score | Rating | Deployability | Responsiveness | Points | Scenarios | Pass | Partial | Fail | Trials |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 90 | ★★★★★ Excellent | 78 | 50 | 174/194 | 97 | 82 | 10 | 5 | 3 |

Pass/partial/fail count the scenario rows of the last trial; the score aggregates all trials.

Trials: 3; final score mean 90.3 ± 0.6 (median 90.0, 95% CI [90.0, 91.0]); points mean 175 ± 1.0; pass@k 89.7%, pass^k 79.4%, reliability gap 10.3.
