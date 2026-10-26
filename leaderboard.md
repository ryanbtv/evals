# Leaderboard

Generated from `runs/*/summary.json`. See each run's `summary.md` for full grids.

Decode tok/s per request (tg/req) and prefill tok/s (pp) at each run's short (smallest) and long (largest) depth.
† context-load row only (measured requests failed); \* some requests failed.
Memory columns are unified-memory GiB: footprint = used after load minus baseline; min available = the run's tightest headroom; — = not recorded.

| Run | Model | Short depth | tg/req c1 | tg/req c4 | pp c1 | Long depth | tg/req c1 | tg/req c4 | pp c1 | Tools score | Model footprint GiB | Peak used GiB | Min available GiB |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| [20261026T052146Z--qwen3.8-flash-next-125b-a5b-int4](runs/20261026T052146Z--qwen3.8-flash-next-125b-a5b-int4/summary.md) | azampatti/Qwen3.8-Flash-Next-125B-A5B-INT4-AutoRound | 65536 | 69.4 | 17.6 | 685 | 259840 | 60.6 | 59.1 | 455 | 93 | 104.9 | 108.9 | 12.8 |
| [20261025T172000Z--radixark_qwen3.8-27b-nvfp4](runs/20261025T172000Z--radixark_qwen3.8-27b-nvfp4/summary.md) | RadixArk/Qwen3.8-27B-NVFP4 | 65536 | 24.1 | 5.8 | 208 | 259840 | 15.4 | 17.2 | 101 | 92 | — | — | — |
| [20261025T000300Z--radixark_qwen3.8-27b-nvfp4](runs/20261025T000300Z--radixark_qwen3.8-27b-nvfp4/summary.md) | RadixArk/Qwen3.8-27B-NVFP4 | 0 | 26.7 | 20.9 | 2291 | 258048 | 16.8 | FAIL | 130 | — | — | — | — |
