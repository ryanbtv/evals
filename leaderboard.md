# Leaderboard

Generated from `runs/*/summary.json`. See each run's `summary.md` for full grids.

Decode tok/s per request (tg/req) and prefill tok/s (pp) at each run's short (smallest) and long (largest) depth.
† context-load row only (measured requests failed); \* some requests failed.

| Run | Model | Short depth | tg/req c1 | tg/req c4 | pp c1 | Long depth | tg/req c1 | tg/req c4 | pp c1 | Tools score |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| [20261025T172000Z--radixark_qwen3.8-27b-nvfp4](runs/20261025T172000Z--radixark_qwen3.8-27b-nvfp4/summary.md) | qwen3.8-27b | 65536 | 24.1 | 5.8 | 208 | 259968 | 15.8† | 14.9* | 690† | 92 |
| [20261025T000300Z--radixark_qwen3.8-27b-nvfp4](runs/20261025T000300Z--radixark_qwen3.8-27b-nvfp4/summary.md) | qwen3.8-27b | 0 | 26.7 | 20.9 | 2291 | 258048 | 16.8 | FAIL | 130 | — |
