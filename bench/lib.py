"""Pure logic: config merge, result parsing, task-cache consolidation, summaries, sanitization.

No sparkrun imports here, so the unit tests run offline.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------- config

def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def effective_config(raw: dict, smoke: bool) -> dict:
    cfg = {k: v for k, v in raw.items() if k != "smoke"}
    if smoke:
        cfg = deep_merge(cfg, raw.get("smoke") or {})
    cfg["smoke"] = bool(smoke)
    return cfg


def slugify(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-").lower() or "model"


def display_model(recipe_doc: dict | None, fallback: str = "") -> str:
    """Reported model name: the recipe's `model` (HF repo id), else served_model_name, else fallback."""
    doc = recipe_doc or {}
    return str(doc.get("model") or (doc.get("defaults") or {}).get("served_model_name") or fallback)


# ---------------------------------------------------------------- llama-benchy

def metric_mean(value: Any) -> float | None:
    """llama-benchy metrics are a number or {mean, std, values}."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        m = value.get("mean")
        if isinstance(m, (int, float)) and not isinstance(m, bool):
            return float(m)
        vals = [v for v in value.get("values") or [] if isinstance(v, (int, float))]
        if vals:
            return sum(vals) / len(vals)
    return None


def _benchy_row(b: dict) -> dict:
    conc = int(b.get("concurrency") or 1)
    tg_total = metric_mean(b.get("tg_throughput"))
    tg_req = metric_mean(b.get("tg_req_throughput"))
    if tg_req is None and conc == 1:
        tg_req = tg_total
    return {
        "depth": int(b.get("context_size") or 0),
        "concurrency": conc,
        "pp_tok_s": metric_mean(b.get("pp_throughput")),
        "pp_req_tok_s": metric_mean(b.get("pp_req_throughput")),
        "tg_tok_s": tg_total,
        "tg_req_tok_s": tg_req,
        "ttfr_ms": metric_mean(b.get("ttfr")),
        "e2e_ttft_ms": metric_mean(b.get("e2e_ttft")),
    }


def benchy_rows(results: dict | None, context_phase: bool = False) -> list[dict]:
    """Rows from consolidated llama-benchy results.

    context_phase=False: the measured pp/tg rows (the 2048-token prompt on top of
    the cached depth). context_phase=True: the context-load rows, where llama-benchy
    prefills `depth` tokens and decodes on that context before the measured request.
    """
    return [_benchy_row(b) for b in (results or {}).get("benchmarks") or []
            if isinstance(b, dict) and bool(b.get("is_context_prefill_phase")) == context_phase]


_HTTP_ERR = re.compile(r"^HTTP (\d{3}): (.*)$", re.M)


def request_errors(log_text: str) -> dict:
    """Count failed llama-benchy requests in a task log, with the first message per status."""
    out: dict = {"count": 0, "by_status": {}, "examples": {}}
    for status, msg in _HTTP_ERR.findall(log_text or ""):
        out["count"] += 1
        out["by_status"][status] = out["by_status"].get(status, 0) + 1
        out["examples"].setdefault(status, msg[:300])
    return out


def perf_grid(results: dict | None, depths: list[int], concs: list[int], errors: dict | None = None) -> list[dict]:
    """One cell per (depth, concurrency) in the configured schedule.

    status: "ok" = measured pp/tg row present; "partial" = only the context-load
    row has numbers (every measured request failed), its values are shown with
    ctx_only=True; "fail" = nothing. errors maps (depth, conc) -> request_errors().
    """
    meas = {(r["depth"], r["concurrency"]): r for r in benchy_rows(results)}
    ctx = {(r["depth"], r["concurrency"]): r for r in benchy_rows(results, context_phase=True)}
    cells = []
    for d in depths:
        for c in concs:
            r, x = meas.get((d, c)), ctx.get((d, c))
            cell = {"depth": d, "concurrency": c}
            if r is not None and r["tg_tok_s"] is not None:
                cell.update(status="ok", ok=True, ctx_only=False, **{k: v for k, v in r.items() if k not in ("depth", "concurrency")})
            elif x is not None and x["tg_tok_s"] is not None:
                cell.update(status="partial", ok=False, ctx_only=True, **{k: v for k, v in x.items() if k not in ("depth", "concurrency")})
            else:
                cell.update(status="fail", ok=False, ctx_only=False)
            e = (errors or {}).get((d, c))
            if e and e.get("count"):
                cell["request_errors"] = e
            cells.append(cell)
    return cells


def cell_text(cell: dict | None, field: str, nd: int) -> str:
    """FAIL; value; value† (context-load row only); value* (some requests failed)."""
    if not cell or cell.get("status", "ok" if cell.get("ok") else "fail") == "fail":
        return "FAIL"
    v = cell.get(field)
    text = "—" if v is None else f"{v:.{nd}f}"
    if cell.get("ctx_only"):
        text += "†"
    elif (cell.get("request_errors") or {}).get("count"):
        text += "*"
    return text


OVERVIEW_METRICS = (("Aggregate decode tok/s", "tg_tok_s", 1), ("Per-request decode tok/s", "tg_req_tok_s", 1), ("Prefill tok/s", "pp_tok_s", 0))


def perf_overview(grid: list[dict]) -> dict:
    """At-a-glance table: one row per metric x depth, one column per concurrency run."""
    concs = sorted({c["concurrency"] for c in grid or []})
    depths = sorted({c["depth"] for c in grid or []})
    key = {(c["depth"], c["concurrency"]): c for c in grid or []}
    rows = [{"metric": title, "depth": d, "values": {f"c{c}": ("—" if (d, c) not in key else cell_text(key[(d, c)], field, nd)) for c in concs}}
            for title, field, nd in OVERVIEW_METRICS for d in depths]
    return {"columns": [f"c{c}" for c in concs], "rows": rows}


def render_overview(ov: dict) -> list[str]:
    if not ov or not ov.get("rows"):
        return []
    cols = ov["columns"]
    L = ["## At a glance", "", "| metric, depth | " + " | ".join(cols) + " |", "|---|" + "---:|" * len(cols)]
    L += [f"| {r['metric']}, {r['depth']} | " + " | ".join(r["values"].get(c, "—") for c in cols) + " |" for r in ov["rows"]]
    return L + ["", "Aggregate decode counts the whole batch window, including time requests spend queued or prefilling; "
                "per-request decode is the speed one user sees once tokens flow.", ""]


def consolidate_tasks(tasks: list) -> dict:
    """Merge per-task framework JSON from sparkrun's task cache.

    llama-benchy tasks each hold {"benchmarks": [...]} and are concatenated, as
    sparkrun's own consolidation does. Anything else (tool-eval-bench runs one
    suite task) is returned as the single task envelope.
    """
    tasks = [t for t in tasks if isinstance(t, dict) and t]
    if not tasks:
        return {}
    if all("benchmarks" in t for t in tasks):
        benches = [b for t in tasks for b in t.get("benchmarks") or [] if isinstance(b, dict)]
        return {"model": next((t.get("model") for t in tasks if t.get("model")), ""),
                "max_concurrency": max([int(b.get("concurrency") or 0) for b in benches] or [0]),
                "benchmarks": benches}
    return dict(tasks[-1])


# ---------------------------------------------------------------- tools

def tools_score(results: dict | None) -> dict:
    r = results or {}
    scores = r.get("scores") if isinstance(r.get("scores"), dict) else {}
    final = r.get("final_score", scores.get("final_score"))
    rows = [x for x in scores.get("scenario_results") or [] if isinstance(x, dict)]
    counts = {k: sum(1 for x in rows if x.get("status") == k) for k in ("pass", "partial", "fail")}
    stats = r.get("trial_statistics") if isinstance(r.get("trial_statistics"), dict) else {}
    return {
        "final_score": final,
        "rating": r.get("rating", scores.get("rating")),
        "deployability": r.get("deployability", scores.get("deployability")),
        "responsiveness": r.get("responsiveness", scores.get("responsiveness")),
        "points": scores.get("total_points", scores.get("points")),
        "max_points": scores.get("max_points"),
        "scenarios": r.get("total_scenarios") or len(rows),
        "version": r.get("tool_eval_bench_version"),
        **counts,
        "trials": stats.get("trials"),
        "trial_statistics": {k: v for k, v in stats.items() if k != "per_scenario"} or None,
    }


# ---------------------------------------------------------------- summary

def _f(v: Any, nd: int = 1) -> str:
    return "—" if v is None else f"{v:.{nd}f}"


def render_summary(s: dict) -> str:
    L = [f"# {s.get('model', '?')} — {s.get('run_id', '')}", ""]
    if s.get("smoke"):
        L += ["> **SMOKE run** — harness validation only, not a benchmark result.", ""]
    for n in s.get("notes") or []:
        L += [f"> **Note:** {n}", ""]
    L += [f"- Recipe: `{s.get('recipe_name')}`", f"- Container: `{s.get('container_image') or '?'}`",
          f"- sparkrun: {s.get('sparkrun_version')}; harness commit: {s.get('harness_commit')}", ""]
    L += ["## Phases", "", "| Phase | Status | Duration (s) | Error |", "|---|---|---:|---|"]
    for name, ph in (s.get("phases") or {}).items():
        err = (ph.get("error") or "").replace("|", "\\|").replace("\n", " ")[:200]
        L.append(f"| {name} | {ph.get('status')} | {_f(ph.get('duration_s'), 0)} | {err} |")
    L.append("")
    L += render_resources(s.get("resources"))
    grid = s.get("perf_grid") or []
    if grid:
        concs = sorted({c["concurrency"] for c in grid})
        depths = sorted({c["depth"] for c in grid})
        key = {(c["depth"], c["concurrency"]): c for c in grid}
        L += render_overview(perf_overview(grid))
        for title, field, nd in (("Prefill pp tok/s (aggregate)", "pp_tok_s", 0),
                                 ("Decode tg tok/s (aggregate across concurrent requests)", "tg_tok_s", 1),
                                 ("Decode tg tok/s per request", "tg_req_tok_s", 1),
                                 ("TTFT (ttfr, ms)", "ttfr_ms", 0)):
            L += [f"## {title}", "", "| depth \\ conc | " + " | ".join(str(c) for c in concs) + " |",
                  "|---:|" + "---:|" * len(concs)]
            for d in depths:
                vals = []
                for c in concs:
                    vals.append(cell_text(key.get((d, c)), field, nd))
                L.append(f"| {d} | " + " | ".join(vals) + " |")
            L.append("")
        L += ["† context-load row only: every measured request in the cell failed, so the value is "
              "llama-benchy's context-load phase (prefill of the full depth, decode on that context).",
              "\\* some requests in the cell failed; the value averages only the requests that succeeded.", ""]
        bad = [c for c in grid if (c.get("request_errors") or {}).get("count")]
        if bad:
            L += ["### Request errors", "", "| depth | conc | failed requests | first error |", "|---:|---:|---:|---|"]
            for c in bad:
                e = c["request_errors"]
                ex = "; ".join(f"HTTP {k}: {v}" for k, v in e["examples"].items()).replace("|", "\\|")[:240]
                L.append(f"| {c['depth']} | {c['concurrency']} | {e['count']} | {ex} |")
            L.append("")
    t = s.get("tools")
    if t:
        L += ["## Tool calling (tool-eval-bench)", "", "| Score | Rating | Deployability | Responsiveness | Points | Scenarios | Pass | Partial | Fail | Trials |",
              "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
              f"| {t.get('final_score')} | {t.get('rating')} | {t.get('deployability')} | {t.get('responsiveness')} | {t.get('points')}/{t.get('max_points')} | {t.get('scenarios')} | {t.get('pass')} | {t.get('partial')} | {t.get('fail')} | {t.get('trials') or 1} |", "",
              "Pass/partial/fail count the scenario rows of the last trial; the score aggregates all trials.", ""]
        ts = t.get("trial_statistics") or {}
        if ts:
            L += [f"Trials: {ts.get('trials')}; final score mean {ts.get('final_score_mean')} ± {ts.get('final_score_stddev')} "
                  f"(median {ts.get('final_score_median')}, 95% CI {ts.get('final_score_ci95')}); points mean {ts.get('total_points_mean')} "
                  f"± {ts.get('total_points_stddev')}; pass@k {ts.get('pass_at_k')}%, pass^k {ts.get('pass_hat_k')}%, "
                  f"reliability gap {ts.get('reliability_gap')}.", ""]
    return "\n".join(L)


def leaderboard(summaries: list[dict]) -> str:
    L = ["# Leaderboard", "", "Generated from `runs/*/summary.json`. See each run's `summary.md` for full grids.", "",
         "Decode tok/s per request (tg/req) and prefill tok/s (pp) at each run's short (smallest) and long (largest) depth.",
         "† context-load row only (measured requests failed); \\* some requests failed.",
         "Memory columns are unified-memory GiB: footprint = used after load minus baseline; min available = the run's tightest headroom; — = not recorded.", "",
         "| Run | Model | Short depth | tg/req c1 | tg/req c4 | pp c1 | Long depth | tg/req c1 | tg/req c4 | pp c1 | Tools score | Model footprint GiB | Peak used GiB | Min available GiB |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]

    def cell(s, d, c, f):
        for x in s.get("perf_grid") or []:
            if x["depth"] == d and x["concurrency"] == c:
                return cell_text(x, f, 0 if f == "pp_tok_s" else 1)
        return "—"

    for s in sorted(summaries, key=lambda x: x.get("run_id", ""), reverse=True):
        rid = s.get("run_id", "")
        mem = (s.get("resources") or {}).get("memory") or {}
        depths = sorted({x["depth"] for x in s.get("perf_grid") or []}) or [None]
        lo, hi = depths[0], depths[-1]
        L.append(f"| [{rid}](runs/{rid}/summary.md) | {s.get('model')} | {lo} | {cell(s,lo,1,'tg_req_tok_s')} | {cell(s,lo,4,'tg_req_tok_s')} | "
                 f"{cell(s,lo,1,'pp_tok_s')} | {hi} | {cell(s,hi,1,'tg_req_tok_s')} | {cell(s,hi,4,'tg_req_tok_s')} | "
                 f"{cell(s,hi,1,'pp_tok_s')} | {(s.get('tools') or {}).get('final_score', '—')} | "
                 f"{_f(mem.get('model_footprint_gib'))} | {_f(mem.get('peak_used_gib'))} | {_f(mem.get('min_available_gib'))} |")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- sanitization

_PRIVATE_IP = re.compile(
    r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
    r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2}|169\.254(?:\.\d{1,3}){2})\b")
_HOSTS = re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.(?:ff\.lan|ryanb\.tv)\b|\bryanb\.tv\b", re.I)
_SSH_PATH = re.compile(r"(?:~|/home/[\w.-]+|/Users/[\w.-]+|/root)?/\.ssh/[^\s\"',;)]*")
_TOKENS = [
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
]
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}")
_KV_SECRET = re.compile(
    r"(?i)([\"']?\b[\w-]*(?:api[_-]?key|token|secret|password|passwd|authorization)[\w-]*[\"']?\s*[:=]\s*[\"']?)"
    r"(?!<redacted>)(?![\d.,]+(?:[\s\"',}\]]|$))([^\s\"',}]{6,})")


def sanitize_text(text: str) -> str:
    text = _SSH_PATH.sub("<redacted-ssh-path>", text)
    text = text.replace("/home/ryanb", "~")
    text = _HOSTS.sub("<redacted-host>", text)
    text = _PRIVATE_IP.sub("<private-ip>", text)
    for rx in _TOKENS:
        text = rx.sub("<redacted>", text)
    text = _BEARER.sub(r"\1 <redacted>", text)
    text = _KV_SECRET.sub(lambda m: m.group(1) + "<redacted>", text)
    return text


def sanitize_tree(src: Path, dst: Path) -> list[str]:
    """Copy src to dst, sanitizing every UTF-8 text file. Returns skipped binaries."""
    skipped = []
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        out = dst / rel
        if p.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        data = p.read_bytes()
        try:
            out.write_text(sanitize_text(data.decode("utf-8")), encoding="utf-8")
        except UnicodeDecodeError:
            skipped.append(str(rel))
    return skipped


def jdump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=False, default=str)


# ---------------------------------------------------------------- resources

GIB = 1024 ** 3
# Recipe `defaults` keys that size the server's memory; recorded as-is when present.
RESOURCE_KEYS = ("gpu_memory_utilization", "mem_fraction_static", "kv_cache_bytes", "kv_cache_dtype",
                 "max_model_len", "context_length", "max_num_seqs", "max_running_requests",
                 "max_num_batched_tokens", "tensor_parallel", "num_speculative_tokens", "speculative_algorithm")


def parse_meminfo(text: str) -> dict:
    """/proc/meminfo -> {"total": bytes, "available": bytes} (keys omitted when missing)."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"(MemTotal|MemAvailable):\s+(\d+)\s*kB", line)
        if m:
            out["total" if m[1] == "MemTotal" else "available"] = int(m[2]) * 1024
    return out


def parse_smi(text: str) -> dict:
    """One `nvidia-smi --query-gpu=utilization.gpu,power.draw,temperature.gpu --format=csv,noheader,nounits` line."""
    keys = ("gpu_util_pct", "power_w", "temp_c")
    vals = [v.strip() for v in (text.strip().splitlines() or [""])[0].split(",")]
    out = {}
    for k, v in zip(keys, vals):
        try:
            out[k] = float(v)
        except ValueError:
            pass
    return out


def resource_config(recipe_doc: dict | None) -> dict:
    doc = recipe_doc or {}
    d = doc.get("defaults") or {}
    cfg = {"runtime": doc.get("runtime"), "container": doc.get("container")}
    cfg.update({k: d[k] for k in RESOURCE_KEYS if k in d})
    cmd = str(doc.get("command") or "")
    for flag in ("mem-fraction-static", "gpu-memory-utilization", "kv-cache-memory-bytes", "max-running-requests",
                 "max-num-seqs", "chunked-prefill-size", "max-model-len", "context-length", "cuda-graph-max-bs-decode"):
        m = re.search(rf"--{flag}[ =](\S+)", cmd)
        if m:
            v = m[1]
            m2 = re.fullmatch(r"\{(\w+)\}", v)
            cfg[f"--{flag}"] = d.get(m2[1], v) if m2 else v
    return {k: v for k, v in cfg.items() if v is not None}


def parse_server_log(text: str) -> dict:
    """KV capacity and pressure signals from a vLLM or SGLang server log."""
    out: dict = {}
    m = re.search(r"GPU KV cache size: ([\d,]+) tokens", text)                     # vLLM
    if m:
        out["kv_tokens"] = int(m[1].replace(",", ""))
    m = re.search(r"Maximum concurrency for ([\d,]+) tokens per request: ([\d.]+)x", text)
    if m:
        out["kv_max_concurrency"] = {"tokens_per_request": int(m[1].replace(",", "")), "x": float(m[2])}
    m = re.search(r"max_total_num_tokens=(\d+)", text)                              # SGLang
    if m:
        out["kv_tokens"] = int(m[1])
    m = re.search(r"max_running_requests=(\d+)", text)
    if m:
        out["max_running_requests"] = int(m[1])
    m = re.search(r"Model loading took ([\d.]+) GiB", text) or re.search(r"Load weight end\..*?mem usage=([\d.]+) GB", text)
    if m:
        out["weights_gib"] = float(m[1])
    m = re.search(r"reserved ([\d.]+) GiB memory for KV Cache", text) or re.search(r"KV Cache is allocated\..*?K size: ([\d.]+) GB, V size: ([\d.]+) GB", text)
    if m:
        out["kv_cache_gib"] = round(sum(float(x) for x in m.groups()), 2)
    usage = [float(x) for x in re.findall(r"GPU KV cache usage: ([\d.]+)%", text)]
    usage += [float(x) * 100 for x in re.findall(r"token usage: ([\d.]+)", text)]
    if usage:
        out["kv_usage_peak_pct"] = round(max(usage), 1)
    out["preemptions"] = len(re.findall(r"(?i)\bpreempted\b", text))
    out["retractions"] = len(re.findall(r"(?i)\bretract(?:ed|ion|ing)?\b", text))
    waiting = [int(x) for x in re.findall(r"(?:Waiting: |#queue-req: )(\d+)", text)]
    if waiting:
        out["max_waiting_requests"] = max(waiting)
    return out


def summarize_resources(samples: list[dict]) -> dict:
    """Headroom from resources.jsonl samples (phase, healthy, mem_total, mem_available, gpu fields)."""
    good = [x for x in samples if x.get("mem_available") is not None]
    if not good:
        return {}
    gb = lambda b: None if b is None else round(b / GIB, 1)  # noqa: E731
    total = next((x["mem_total"] for x in good if x.get("mem_total")), None)
    used = lambda x: x["mem_total"] - x["mem_available"] if x.get("mem_total") else None  # noqa: E731
    base = [x for x in good if x.get("phase") == "baseline"] or good[:1]
    loaded = next((x for x in good if x.get("healthy") and x.get("phase") != "baseline"), None)
    base_used = min(used(x) for x in base)
    out = {
        "mem_total_gib": gb(total), "samples": len(samples),
        "baseline_used_gib": gb(base_used),
        "loaded_used_gib": gb(used(loaded)) if loaded else None,
        "model_footprint_gib": gb(used(loaded) - base_used) if loaded else None,
        "peak_used_gib": gb(max(used(x) for x in good)),
        "min_available_gib": gb(min(x["mem_available"] for x in good)),
        "phases": {},
    }
    for ph in dict.fromkeys(x.get("phase") for x in good):
        xs = [x for x in good if x.get("phase") == ph]
        pick = lambda k, f: (lambda v: f(v) if v else None)([x[k] for x in xs if x.get(k) is not None])  # noqa: E731
        out["phases"][ph] = {
            "peak_used_gib": gb(max(used(x) for x in xs)), "min_available_gib": gb(min(x["mem_available"] for x in xs)),
            "container_peak_gib": gb(pick("container_mem", max)),
            "gpu_util_mean_pct": (lambda v: round(v, 1) if v is not None else None)(pick("gpu_util_pct", lambda v: sum(v) / len(v))),
            "power_max_w": pick("power_w", max), "temp_max_c": pick("temp_c", max), "samples": len(xs)}
    return out


def render_resources(r: dict | None) -> list[str]:
    r = r or {}
    if not (r.get("memory") or r.get("config") or r.get("server")):
        return []
    m, L = r.get("memory") or {}, ["## Resources", ""]
    if m:
        L += ["Unified memory (GiB, from /proc/meminfo; GB10 shares CPU/GPU memory, so this is the true headroom).", "",
              "| Total | Baseline used | After load | Model footprint | Peak used | Min available |",
              "|---:|---:|---:|---:|---:|---:|",
              f"| {_f(m.get('mem_total_gib'))} | {_f(m.get('baseline_used_gib'))} | {_f(m.get('loaded_used_gib'))} | "
              f"{_f(m.get('model_footprint_gib'))} | {_f(m.get('peak_used_gib'))} | {_f(m.get('min_available_gib'))} |", ""]
        if m.get("phases"):
            L += ["| Phase | Peak used | Min available | Container peak | GPU util mean % | Power max W | Temp max °C | Samples |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"]
            for ph, p in m["phases"].items():
                L.append(f"| {ph} | {_f(p.get('peak_used_gib'))} | {_f(p.get('min_available_gib'))} | {_f(p.get('container_peak_gib'))} | "
                         f"{_f(p.get('gpu_util_mean_pct'))} | {_f(p.get('power_max_w'))} | {_f(p.get('temp_max_c'), 0)} | {p.get('samples')} |")
            L.append("")
    if r.get("server"):
        L += ["Server log: " + ", ".join(f"{k}={v}" for k, v in r["server"].items()), ""]
    if r.get("config"):
        L += ["Config: " + ", ".join(f"`{k}`={v}" for k, v in r["config"].items()), ""]
    return L


# ---------------------------------------------------------------- preflight

class ProxyGuard:
    """Stop a systemd unit for the run and start it again on exit, only if we stopped it.

    `run(argv) -> str` runs a command and returns its output; `clock() -> str` gives a timestamp.
    """

    def __init__(self, unit: str, run, clock, log=print):
        self.unit, self.run, self.clock, self.log = unit, run, clock, log
        self.stopped = False
        self.restored = False
        self.record: dict = {"unit": unit, "was_active": None, "stopped_at": None, "started_at": None,
                             "stop_result": None, "start_result": None, "active_after_restart": None}

    def active(self) -> bool:
        return (self.run(["systemctl", "is-active", self.unit]) or "").strip() == "active"

    def stop(self) -> None:
        self.record["was_active"] = self.active()
        if not self.record["was_active"]:
            self.log(f"{self.unit} not active; leaving it alone")
            return
        self.record["stop_result"] = self.run(["sudo", "-n", "systemctl", "stop", self.unit]) or "ok"
        self.record["stopped_at"] = self.clock()
        self.stopped = not self.active()
        self.log(f"stopped {self.unit} at {self.record['stopped_at']}: {self.record['stop_result']} (inactive={self.stopped})")

    def restore(self) -> None:
        if not self.record["was_active"] or self.restored:
            return
        self.restored = True
        self.record["start_result"] = self.run(["sudo", "-n", "systemctl", "start", self.unit]) or "ok"
        self.record["started_at"] = self.clock()
        self.record["active_after_restart"] = self.active()
        self.log(f"started {self.unit} at {self.record['started_at']}: {self.record['start_result']} (active={self.record['active_after_restart']})")


def merge_perf(orig: dict | None, new: dict | None, replaced_depths) -> dict:
    """Original llama-benchy rows minus the replaced depths, plus the re-run rows."""
    replaced = {int(d) for d in replaced_depths}
    keep = [b for b in (orig or {}).get("benchmarks") or [] if int(b.get("context_size") or 0) not in replaced]
    add = list((new or {}).get("benchmarks") or [])
    rows = keep + add
    return {"model": (orig or {}).get("model") or (new or {}).get("model", ""),
            "max_concurrency": max([int(b.get("concurrency") or 0) for b in rows] or [0]),
            "benchmarks": rows, "merged": {"replaced_depths": sorted(replaced), "kept_rows": len(keep), "rerun_rows": len(add)}}


def gpu_containers_to_stop(inspected: list[dict], keep: list[str]) -> list[dict]:
    """Pick running containers that hold the GPU, from `docker inspect` objects.

    A container qualifies when it requests GPU devices (DeviceRequests / nvidia
    runtime / NVIDIA_VISIBLE_DEVICES) and its name is not in `keep`.
    """
    out = []
    for c in inspected:
        name = (c.get("Name") or "").lstrip("/")
        if not name or name in keep or not (c.get("State") or {}).get("Running"):
            continue
        hc = c.get("HostConfig") or {}
        env = (c.get("Config") or {}).get("Env") or []
        gpu = bool(hc.get("DeviceRequests")) or hc.get("Runtime") == "nvidia" or any(
            e.startswith("NVIDIA_VISIBLE_DEVICES=") and e.split("=", 1)[1] not in ("", "void", "none") for e in env)
        if gpu:
            out.append({"name": name, "id": (c.get("Id") or "")[:12], "image": (c.get("Config") or {}).get("Image")})
    return out
