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


def benchy_rows(results: dict | None) -> list[dict]:
    """Measured (non context-prefill) rows from consolidated llama-benchy results."""
    rows = []
    for b in (results or {}).get("benchmarks") or []:
        if not isinstance(b, dict) or b.get("is_context_prefill_phase"):
            continue
        conc = int(b.get("concurrency") or 1)
        tg_total = metric_mean(b.get("tg_throughput"))
        tg_req = metric_mean(b.get("tg_req_throughput"))
        if tg_req is None and conc == 1:
            tg_req = tg_total
        rows.append({
            "depth": int(b.get("context_size") or 0),
            "concurrency": conc,
            "pp_tok_s": metric_mean(b.get("pp_throughput")),
            "pp_req_tok_s": metric_mean(b.get("pp_req_throughput")),
            "tg_tok_s": tg_total,
            "tg_req_tok_s": tg_req,
            "ttfr_ms": metric_mean(b.get("ttfr")),
            "e2e_ttft_ms": metric_mean(b.get("e2e_ttft")),
        })
    return rows


def perf_grid(results: dict | None, depths: list[int], concs: list[int]) -> list[dict]:
    """One cell per (depth, concurrency) in the configured schedule; missing = failed."""
    by_key = {(r["depth"], r["concurrency"]): r for r in benchy_rows(results)}
    cells = []
    for d in depths:
        for c in concs:
            r = by_key.get((d, c))
            ok = r is not None and r["tg_tok_s"] is not None
            cells.append({"depth": d, "concurrency": c, "ok": ok, **({k: v for k, v in r.items() if k not in ("depth", "concurrency")} if r else {})})
    return cells


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
        "trial_statistics": stats or None,
    }


# ---------------------------------------------------------------- summary

def _f(v: Any, nd: int = 1) -> str:
    return "—" if v is None else f"{v:.{nd}f}"


def render_summary(s: dict) -> str:
    L = [f"# {s.get('model', '?')} — {s.get('run_id', '')}", ""]
    if s.get("smoke"):
        L += ["> **SMOKE run** — harness validation only, not a benchmark result.", ""]
    L += [f"- Recipe: `{s.get('recipe_name')}`", f"- Container: `{s.get('container_image') or '?'}`",
          f"- sparkrun: {s.get('sparkrun_version')}; harness commit: {s.get('harness_commit')}", ""]
    L += ["## Phases", "", "| Phase | Status | Duration (s) | Error |", "|---|---|---:|---|"]
    for name, ph in (s.get("phases") or {}).items():
        err = (ph.get("error") or "").replace("|", "\\|").replace("\n", " ")[:200]
        L.append(f"| {name} | {ph.get('status')} | {_f(ph.get('duration_s'), 0)} | {err} |")
    L.append("")
    grid = s.get("perf_grid") or []
    if grid:
        concs = sorted({c["concurrency"] for c in grid})
        depths = sorted({c["depth"] for c in grid})
        key = {(c["depth"], c["concurrency"]): c for c in grid}
        for title, field, nd in (("Prefill pp tok/s (aggregate)", "pp_tok_s", 0),
                                 ("Decode tg tok/s (aggregate across concurrent requests)", "tg_tok_s", 1),
                                 ("Decode tg tok/s per request", "tg_req_tok_s", 1),
                                 ("TTFT (ttfr, ms)", "ttfr_ms", 0)):
            L += [f"## {title}", "", "| depth \\ conc | " + " | ".join(str(c) for c in concs) + " |",
                  "|---:|" + "---:|" * len(concs)]
            for d in depths:
                vals = []
                for c in concs:
                    cell = key.get((d, c))
                    vals.append("FAIL" if not cell or not cell["ok"] else _f(cell.get(field), nd))
                L.append(f"| {d} | " + " | ".join(vals) + " |")
            L.append("")
    t = s.get("tools")
    if t:
        L += ["## Tool calling (tool-eval-bench)", "", "| Score | Rating | Deployability | Responsiveness | Points | Scenarios | Pass | Partial | Fail | Trials |",
              "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
              f"| {t.get('final_score')} | {t.get('rating')} | {t.get('deployability')} | {t.get('responsiveness')} | {t.get('points')}/{t.get('max_points')} | {t.get('scenarios')} | {t.get('pass')} | {t.get('partial')} | {t.get('fail')} | {t.get('trials') or 1} |", "",
              "Pass/partial/fail count the scenario rows of the last trial; the score aggregates all trials.", ""]
    return "\n".join(L)


def leaderboard(summaries: list[dict]) -> str:
    L = ["# Leaderboard", "", "Generated from `runs/*/summary.json`. See each run's `summary.md` for full grids.", "",
         "Decode tok/s per request (tg/req) and prefill tok/s (pp) at the short (65536) and long (259968) depths.", "",
         "| Run | Model | tg/req d65536 c1 | tg/req d65536 c4 | pp d65536 c1 | tg/req d259968 c1 | tg/req d259968 c4 | pp d259968 c1 | Tools score |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|"]

    def cell(s, d, c, f):
        for x in s.get("perf_grid") or []:
            if x["depth"] == d and x["concurrency"] == c:
                return _f(x.get(f), 0 if f == "pp_tok_s" else 1) if x["ok"] else "FAIL"
        return "—"

    for s in sorted(summaries, key=lambda x: x.get("run_id", ""), reverse=True):
        rid = s.get("run_id", "")
        L.append(f"| [{rid}](runs/{rid}/summary.md) | {s.get('model')} | {cell(s,65536,1,'tg_req_tok_s')} | {cell(s,65536,4,'tg_req_tok_s')} | "
                 f"{cell(s,65536,1,'pp_tok_s')} | {cell(s,259968,1,'tg_req_tok_s')} | {cell(s,259968,4,'tg_req_tok_s')} | "
                 f"{cell(s,259968,1,'pp_tok_s')} | {(s.get('tools') or {}).get('final_score', '—')} |")
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
    r"(?!<redacted>)([^\s\"',}]{6,})")


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


# ---------------------------------------------------------------- preflight

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
