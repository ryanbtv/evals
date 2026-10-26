# qwen3.8-27b — 20261025T172000Z--radixark_qwen3.8-27b-nvfp4/rerun-20261025T221614Z

- Recipe: `RadixArk_Qwen3.8-27B-NVFP4.yml`
- Container: `lmsysorg/sglang@sha256:febfb971c7352570fc445c466ebd6ffc9d896024958e544a60f2137fd85856b1`
- sparkrun: 0.4.1; harness commit: b6d55cebb06999aafc86a1c4715538d7dc12fa95

## Phases

| Phase | Status | Duration (s) | Error |
|---|---|---:|---|
| performance | ok | 15050 |  |

## Prefill pp tok/s (aggregate)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 259840 | 101 | 8 | 6 |

## Decode tg tok/s (aggregate across concurrent requests)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 259840 | 15.4 | 0.6 | 0.4 |

## Decode tg tok/s per request

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 259840 | 15.4 | 16.2 | 17.2 |

## TTFT (ttfr, ms)

| depth \ conc | 1 | 2 | 4 |
|---:|---:|---:|---:|
| 259840 | 20248 | 337463 | 849673 |

† context-load row only: every measured request in the cell failed, so the value is llama-benchy's context-load phase (prefill of the full depth, decode on that context).
\* some requests in the cell failed; the value averages only the requests that succeeded.
