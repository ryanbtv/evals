# RadixArk/Qwen3.8-27B-NVFP4 — 20261025T000300Z--radixark_qwen3.8-27b-nvfp4

- Recipe: `RadixArk_Qwen3.8-27B-NVFP4.yml`
- Container: `lmsysorg/sglang@sha256:febfb971c7352570fc445c466ebd6ffc9d896024958e544a60f2137fd85856b1 (from recipe; run interrupted before sparkrun reported provenance)`
- sparkrun: 0.4.1; harness commit: 446509c3c6ae4115877d8dc4f070a9d1500b6337

## Phases

| Phase | Status | Duration (s) | Error |
|---|---|---:|---|
| performance | interrupted | 39086 | stopped at 11h poll cap during task 30 (d258048 c4); d131072c8, d196608c4, d196608c8 timed out at 5400s; d258048 c4/c8 not run \| cells: d131072c8:fail, d196608c4:fail, d196608c8:fail, d258048c4:fail, |
| tools | not run | — | run stopped at poll cap before this phase |
| ctf | not run | — | run stopped at poll cap before this phase |

## At a glance

| metric, depth | c1 | c2 | c4 | c8 |
|---|---:|---:|---:|---:|
| Aggregate decode tok/s, 0 | 26.7 | 50.3 | 77.5 | 68.1 |
| Aggregate decode tok/s, 4096 | 27.7 | 44.7 | 54.3 | 42.7 |
| Aggregate decode tok/s, 16384 | 26.6 | 42.9 | 37.9 | 17.0 |
| Aggregate decode tok/s, 32768 | 25.1 | 38.4 | 33.1 | 7.9 |
| Aggregate decode tok/s, 65536 | 22.4 | 39.6 | 8.4 | 3.4 |
| Aggregate decode tok/s, 131072 | 19.9 | 26.0 | 1.8 | FAIL |
| Aggregate decode tok/s, 196608 | 19.3 | 16.3 | FAIL | FAIL |
| Aggregate decode tok/s, 258048 | 16.8 | 0.6 | FAIL | FAIL |
| Per-request decode tok/s, 0 | 26.7 | 26.5 | 20.9 | 17.8 |
| Per-request decode tok/s, 4096 | 27.7 | 23.9 | 19.0 | 13.9 |
| Per-request decode tok/s, 16384 | 26.6 | 22.5 | 15.7 | 8.9 |
| Per-request decode tok/s, 32768 | 25.1 | 19.8 | 14.7 | 5.7 |
| Per-request decode tok/s, 65536 | 22.4 | 20.5 | 6.3 | 3.4 |
| Per-request decode tok/s, 131072 | 19.9 | 14.8 | 9.0 | FAIL |
| Per-request decode tok/s, 196608 | 19.3 | 10.8 | FAIL | FAIL |
| Per-request decode tok/s, 258048 | 16.8 | 16.5 | FAIL | FAIL |
| Prefill tok/s, 0 | 2291 | 2184 | 1935 | 1187 |
| Prefill tok/s, 4096 | 688 | 944 | 956 | 645 |
| Prefill tok/s, 16384 | 355 | 354 | 402 | 278 |
| Prefill tok/s, 32768 | 288 | 287 | 328 | 126 |
| Prefill tok/s, 65536 | 206 | 208 | 111 | 47 |
| Prefill tok/s, 131072 | 135 | 137 | 20 | FAIL |
| Prefill tok/s, 196608 | 100 | 16 | FAIL | FAIL |
| Prefill tok/s, 258048 | 130 | 9 | FAIL | FAIL |

Aggregate decode counts the whole batch window, including time requests spend queued or prefilling; per-request decode is the speed one user sees once tokens flow.

## Prefill pp tok/s (aggregate)

| depth \ conc | 1 | 2 | 4 | 8 |
|---:|---:|---:|---:|---:|
| 0 | 2291 | 2184 | 1935 | 1187 |
| 4096 | 688 | 944 | 956 | 645 |
| 16384 | 355 | 354 | 402 | 278 |
| 32768 | 288 | 287 | 328 | 126 |
| 65536 | 206 | 208 | 111 | 47 |
| 131072 | 135 | 137 | 20 | FAIL |
| 196608 | 100 | 16 | FAIL | FAIL |
| 258048 | 130 | 9 | FAIL | FAIL |

## Decode tg tok/s (aggregate across concurrent requests)

| depth \ conc | 1 | 2 | 4 | 8 |
|---:|---:|---:|---:|---:|
| 0 | 26.7 | 50.3 | 77.5 | 68.1 |
| 4096 | 27.7 | 44.7 | 54.3 | 42.7 |
| 16384 | 26.6 | 42.9 | 37.9 | 17.0 |
| 32768 | 25.1 | 38.4 | 33.1 | 7.9 |
| 65536 | 22.4 | 39.6 | 8.4 | 3.4 |
| 131072 | 19.9 | 26.0 | 1.8 | FAIL |
| 196608 | 19.3 | 16.3 | FAIL | FAIL |
| 258048 | 16.8 | 0.6 | FAIL | FAIL |

## Decode tg tok/s per request

| depth \ conc | 1 | 2 | 4 | 8 |
|---:|---:|---:|---:|---:|
| 0 | 26.7 | 26.5 | 20.9 | 17.8 |
| 4096 | 27.7 | 23.9 | 19.0 | 13.9 |
| 16384 | 26.6 | 22.5 | 15.7 | 8.9 |
| 32768 | 25.1 | 19.8 | 14.7 | 5.7 |
| 65536 | 22.4 | 20.5 | 6.3 | 3.4 |
| 131072 | 19.9 | 14.8 | 9.0 | FAIL |
| 196608 | 19.3 | 10.8 | FAIL | FAIL |
| 258048 | 16.8 | 16.5 | FAIL | FAIL |

## TTFT (ttfr, ms)

| depth \ conc | 1 | 2 | 4 | 8 |
|---:|---:|---:|---:|---:|
| 0 | 899 | 1878 | 4180 | 7902 |
| 4096 | 2979 | 4327 | 8011 | 14959 |
| 16384 | 5775 | 11558 | 18455 | 29405 |
| 32768 | 7123 | 14223 | 22676 | 65970 |
| 65536 | 9922 | 19634 | 41910 | 188492 |
| 131072 | 15205 | 29958 | 252017 | FAIL |
| 196608 | 20436 | 223907 | FAIL | FAIL |
| 258048 | 15771 | 328966 | FAIL | FAIL |

† context-load row only: every measured request in the cell failed, so the value is llama-benchy's context-load phase (prefill of the full depth, decode on that context).
\* some requests in the cell failed; the value averages only the requests that succeeded.
