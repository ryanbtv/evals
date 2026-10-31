# turboderp/Qwen3.8-Flash-Next-exl3 — 20261031T023355Z--qwen38-flash-next-tensorfold-flash3

- Recipe: `qwen38-flash-next-tensorfold-flash3.yml`
- Container: `?`
- sparkrun: 0.4.1; harness commit: 291f18a9b507218342077c38169c1d68de70466c-dirty

## Phases

| Phase | Status | Duration (s) | Error |
|---|---|---:|---|
| performance | partial | 22615 | BenchmarkFailed: Benchmark incomplete; schedule did not complete; cells: d259840c4:fail |
| tools | incomplete | 4142 | BenchmarkFailed: Benchmark incomplete; schedule did not complete |

## Resources

Unified memory (GiB, from /proc/meminfo; GB10 shares CPU/GPU memory, so this is the true headroom).

| Total | Baseline used | After load | Model footprint | Peak used | Min available |
|---:|---:|---:|---:|---:|---:|
| 121.7 | 3.8 | 76.7 | 72.9 | 115.6 | 6.1 |

| Phase | Peak used | Min available | Container peak | GPU util mean % | Power max W | Temp max °C | Samples |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 3.8 | 117.9 | — | 0.0 | 12.6 | 48 | 3 |
| preflight | 3.8 | 117.9 | — | 0.0 | 5.1 | 47 | 1 |
| performance | 115.6 | 6.1 | 43.4 | 73.5 | 67.5 | 83 | 2190 |
| tools | 115.5 | 6.2 | 11.0 | 69.1 | 65.8 | 73 | 194 |
| after-stop | 3.8 | 117.9 | — | 0.0 | 4.7 | 44 | 1 |

Server log: preemptions=0, retractions=0

Config: `runtime`=vllm-distributed, `container`=tensorfold:v0.6.6-cb2ebf0540f4-pb7c96ae7e07e, `tensor_parallel`=1

## At a glance

| metric, depth | c1 | c2 | c4 |
|---|---:|---:|---:|
| Aggregate decode tok/s, 65536 | 51.9 | 62.5 | 52.2 |
| Aggregate decode tok/s, 259840 | 46.8 | 41.5 | n/a |
| Per-request decode tok/s, 65536 | 51.9 | 35.0 | 21.6 |
| Per-request decode tok/s, 259840 | 46.8 | 22.4 | n/a |
| Prefill tok/s, 65536 | 39925 | 544 | 802 |
| Prefill tok/s, 259840 | 5861 | 296 | n/a |

Aggregate decode counts the whole batch window, including time requests spend queued or prefilling; per-request decode is the speed one user sees once tokens flow.

## Prefill pp tok/s (aggregate)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 39925 | 544 | 802 |
| 259840 | 5861 | 296 | n/a |

## Decode tg tok/s (aggregate across concurrent requests)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 51.9 | 62.5 | 52.2 |
| 259840 | 46.8 | 41.5 | n/a |

## Decode tg tok/s per request

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 51.9 | 35.0 | 21.6 |
| 259840 | 46.8 | 22.4 | n/a |

## TTFT (ttfr, ms)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 65536 | 96 | 142 | 348 |
| 259840 | 394 | 805 | n/a |

† context-load row only: every measured request in the cell failed, so the value is llama-benchy's context-load phase (prefill of the full depth, decode on that context).
\* some requests in the cell failed; the value averages only the requests that succeeded.

## Tool calling (tool-eval-bench)

Score: n/a (no completed trial; see Limitations).

## Limitations

The run is valid for the results it reports; these limits apply.

- Performance: 5 of 6 cells completed. The 259840-depth, concurrency-4 cell did not complete: llama-benchy logged three empty `Error during run:` lines (perf-tasks/005_d259840_c4.log) and sparkrun reported `schedule did not complete`. It is shown as n/a. The server stayed up after this cell and served the tool eval.
- Tool calling: no score (n/a). Trial 1 ran from 08:50:56 to 09:57:26 UTC and scored 44 of 97 scenarios (98/100 on those, 86/88 points) before the server went away near TC-45; that partial trial is kept in runs/2026/10/ but is not a valid score. At 09:56:46 UTC the dgx01 kernel's global OOM killer killed the `tensorfold` server process (kernel journal; the serve log ends with `Killed`). Trials 2 and 3 then failed every scenario with connection errors, and the harness's resume attempt failed its pre-flight check with `connection_failed` on :8888 (tools-tasks/000.log).
- Memory: peak use was 115.6 of 121.7 GiB, with a minimum of 6.1 GiB available, under `--parallel 9 --context 262144`. The OOM kill during the tool eval suggests this configuration leaves too little headroom on this host for a full run.
- Recipe: `model_revision: 4.05bpw_h6_ng6` is recorded, but the command never passes `--revision`. The served weights are whatever snapshot is cached (55a732e0c4c3d4614bc42b68493bb930d9b02c0a in the serve log), not a revision the recipe enforces.
- Recipe: it bind-mounts `tool_calls.py` and `tool_trace.py` from a host checkout of github.com/anubhavgupta/Tensorfold-recipies-single-dgx-spark (flash-3/tools/, commit 481854d920a4050a504b4ca8d4bc4fceb2960235). They are not vendored here because that repository has no license; see recipes/qwen38-flash-next-tensorfold-flash3/README.md.
- Duration: about 7.4 h in total (performance 22615 s, tools 4142 s).
