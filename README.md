# evals

A reproducible benchmark harness for local LLM inference on an NVIDIA DGX Spark,
built on [sparkrun](https://github.com/spark-arena/sparkrun)'s Python benchmark API.
Every model runs the same fixed schedule, so results compare directly.

## Layout

```
bench/run           entry point: ./bench/run <recipe-path>
bench/driver.py     orchestration (sparkrun API calls, phases, server reuse, teardown)
bench/lib.py        pure logic: parsing, task-cache recovery, summaries, leaderboard, sanitization
bench/config.yaml   all benchmark parameters (committed; identical for every model)
tests/              offline unit tests (stdlib unittest)
scripts/sync.sh     deploy the harness to the Spark / pull sanitized results back
runs/<UTC>--<slug>/ sanitized published results, one directory per run
leaderboard.md      index regenerated from runs/*/summary.json after each real run
raw-runs/           unsanitized local results (gitignored, stays on the Spark)
smoke-runs/         sanitized smoke results (gitignored)
```

## Running

On the Spark, with sparkrun installed (`~/.local/bin/sparkrun`):

```sh
./bench/run /path/to/recipe.yml                 # full run (many hours)
./bench/run /path/to/recipe.yml --dry-run       # sparkrun dry_run for every phase
BENCH_SMOKE=1 ./bench/run /path/to/recipe.yml   # harness validation only
~/.local/share/uv/tools/sparkrun/bin/python -m unittest discover -s tests
```

Run long jobs detached, for example
`setsid nohup ./bench/run recipe.yml </dev/null >run.log 2>&1 &`.
The recipe path is the only input. Change parameters only in `bench/config.yaml`,
and only between benchmark generations.

The driver runs with sparkrun's own interpreter (`SPARKRUN_PYTHON` overrides it).
A full run of Qwen3.8-27B-NVFP4 is estimated at about 6.5 h: about 7 min launch, about
4.6 h performance (the long-depth c=4 cell alone is about 2.3 h) and about 1.5–2 h tools.
A **preflight** first frees the GPU: it stops the `preflight.systemd_units` from the config
(`sudo -n`), every sparkrun workload reported by `sparkrun.api.status` (via
`sparkrun.api.stop`), and any other running container that requests the GPU, except
`preflight.keep_containers`. Everything stopped is listed in `platform.json → preflight`
and in `harness.log`. Nothing is restarted afterwards. The driver then refuses to start
if something still answers on the recipe's port.
From a workstation: `DGX_HOST=user@host scripts/sync.sh deploy`, then
`scripts/sync.sh pull` to fetch `runs/` and `leaderboard.md` for committing.

## Phases

Each phase runs inside its own `sparkrun.api.capture_diagnostics` bundle
(`diagnostics/<phase>.ndjson`). A failing phase is recorded with its error and the
next phase still runs.

1. **performance** — llama-benchy 0.4.0 (pinned by sparkrun): pp 2048, tg 128,
   two depths — **short** 65536 and **long** 259968 — at concurrency 1 / 2 / 4, 3 runs per
   cell, prefix caching on. 259968 is the deepest context that fits the model's 262144
   window with the request on top: 259968 + 2048 (pp) + 128 (tg) = 262144.
   One sparkrun task per (depth, concurrency), each with a 14,400 s timeout;
   `exit_on_first_fail=False`, so a cell that times out or exhausts the KV cache is
   reported as `FAIL` and the sweep continues.
2. **tools** — tool-eval-bench v2.8.0, 3 trials, hard mode, temperature 0.

If a phase is interrupted (timeout, SIGTERM, crash) before sparkrun exports its results,
the driver rebuilds `perf.json` / `tools.json` from sparkrun's per-task cache
(`~/.cache/sparkrun/benchmarks/<benchmark_id>/runs/`), copies the raw task files to
`perf-tasks/` / `tools-tasks/`, and marks the JSON `recovered_from_task_cache: true`.

The inference server launches once (`no_stop=True`) and later calls reuse it with
`skip_run=True`. Before each call the driver checks `GET /v1/models`; if the server
died (for example after an out-of-memory cell) the next call relaunches it.
`summary.json → server_reuse` records launches and reused calls. The server is
stopped through `sparkrun.api.stop` in a `finally` block, with a
`sparkrun stop <recipe>` fallback, also on error or SIGTERM.

## Metrics

- **pp tok/s** — prompt-processing throughput, aggregate across concurrent requests.
- **tg tok/s (aggregate)** — llama-benchy `tg_throughput`. At concurrency > 1 this is the
  *total* decode rate of the whole batch (decoded tokens / batch decode time), not a
  per-user speed. At concurrency 1 it equals the per-request value.
- **tg tok/s per request** — llama-benchy `tg_req_throughput`: mean decode speed one
  request observes. This is the user-experienced speed.
  (Verified in llama-benchy 0.4.0 `results.py`: `tg_throughput` is documented
  "Generation tokens per second (total)" and computed from batch throughputs when
  concurrency > 1; `tg_req_throughput` is "per request".)
- **TTFT** — llama-benchy `ttfr` (time to first response token, ms), mean over runs.
  At depth > 0 the context is pre-filled with prefix caching on, so TTFT reflects the
  2048-token prompt on top of a cached context.
- Values are means of the configured runs. `FAIL` means the cell produced no measurement
  (timeout, request error, KV exhaustion or server crash).
- **Tool score** — tool-eval-bench `final_score` (0–100) plus its rating, deployability,
  responsiveness and points.

## Outputs per run

`recipe.yml` (verbatim), `config.yaml` (effective config), `platform.json` (hardware,
OS, kernel, driver, CUDA, sparkrun / llama-benchy / tool-eval-bench versions, container
image and digest, harness commit, config), `perf.{yaml,json,csv}`,
`tools.{yaml,json,csv}`, `perf-tasks/` and `tools-tasks/` (only after a recovery),
`diagnostics/*.ndjson`, `harness.log` (full stdout/stderr), `progress.ndjson`
(every sparkrun progress event), `summary.md`, `summary.json`.

## Platform notes

Reference host: NVIDIA DGX Spark (GB10, aarch64, 128 GB unified memory), Ubuntu 26.04,
NVIDIA driver 580, CUDA 13.0, sparkrun 0.4.1, solo mode. Unified memory means the
recipe's memory fraction bounds the KV cache, so deep-context cells at high
concurrency are expected to fail on large models.

## Sanitization

Published copies under `runs/` pass through `lib.sanitize_text`: the home directory
becomes `~`, private IPv4 addresses and private LAN hostnames are replaced, and API
keys, bearer tokens, credential-like `key=value` pairs and SSH key paths are redacted.
Hardware, software versions, recipes and logs are otherwise kept verbatim. The raw
copy stays on the benchmark host under `raw-runs/`.

## Smoke mode

`BENCH_SMOKE=1` overlays `smoke:` from the config (depth 0, concurrency 1, 1 run;
1 tool trial without hard mode). It exists only
to validate the harness; its results go to `smoke-runs/` and never to the leaderboard.
