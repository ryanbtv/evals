"""Rebuild a run's summary from its raw files with the current parsing logic.

Usage: resummarize.py <raw-run-dir> [<sparkrun-state-dir>]
       resummarize.py --relabel-published [<runs-dir>]   # refresh model names + leaderboard only
Copies <state-dir>/runs into perf-tasks/ when given, then rewrites summary.json/md,
republishes the sanitized copy to runs/ and regenerates leaderboard.md.
Request errors come from perf-tasks/*.log and, after a depth re-run, rerun-*/perf-tasks/*.log.
"""

import json
import re
import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def relabel(run_dir: Path, s: dict) -> None:
    """Set the reported model name from the run's saved recipe.yml (older runs used served_model_name)."""
    recipe = run_dir / "recipe.yml"
    if recipe.exists():
        doc = yaml.safe_load(recipe.read_text()) or {}
        if s.get("model") and s.get("model") != lib.display_model(doc, s["model"]):
            s.setdefault("served_model_name", s["model"])
        s["model"] = lib.display_model(doc, s.get("model", ""))


def relabel_published(runs_root: Path) -> None:
    """Relabel already-published runs in place (no raw files needed) and regenerate leaderboard.md."""
    for sj in sorted(runs_root.glob("*/summary.json")):
        s = json.loads(sj.read_text())
        relabel(sj.parent, s)
        if s.get("perf_grid"):
            s["perf_overview"] = lib.perf_overview(s["perf_grid"])
        sj.write_text(lib.jdump(s))
        (sj.parent / "summary.md").write_text(lib.render_summary(s))
    sums = [json.loads(p.read_text()) for p in sorted(runs_root.glob("*/summary.json"))]
    (runs_root.parent / "leaderboard.md").write_text(lib.leaderboard(sums))


def rebuild_resources(run_dir: Path, s: dict) -> None:
    """Recompute the Resources section from resources.jsonl and saved server logs, when present."""
    r = dict(s.get("resources") or {})
    if (run_dir / "recipe.yml").exists():
        r.setdefault("config", lib.resource_config(yaml.safe_load((run_dir / "recipe.yml").read_text()) or {}))
    path = run_dir / "resources.jsonl"
    if path.exists():
        samples = []
        for line in path.read_text().splitlines():
            try:
                samples.append(json.loads(line))
            except ValueError:
                pass
        r["memory"] = lib.summarize_resources(samples)
    logs = sorted((run_dir / "diagnostics").glob("server-*.log"))
    if logs:
        r["server"] = lib.parse_server_log("".join(p.read_text(errors="replace") for p in logs))
    if r:
        s["resources"] = r


def task_errors(run_dir: Path) -> dict:
    errs = {}
    logs = list((run_dir / "perf-tasks").glob("*.log")) + list(run_dir.glob("rerun-*/perf-tasks/*.log"))
    for log in sorted(logs, key=lambda p: (p.parent.parent.name, p.name)):
        m = re.search(r"_d(\d+)_c(\d+)\.log$", log.name)
        if m:  # later reruns (sorted last) win for the same cell
            errs[(int(m[1]), int(m[2]))] = lib.request_errors(log.read_text(errors="replace"))
    return errs


def rebuild(run_dir: Path) -> dict:
    s = json.loads((run_dir / "summary.json").read_text())
    relabel(run_dir, s)
    ba = yaml.safe_load((run_dir / "config.yaml").read_text())["performance"]["bench_args"]
    depths = s.get("perf_depths") or ba["depth"]
    concs = s.get("perf_concurrency") or ba["concurrency"]
    s["perf_grid"] = lib.perf_grid(json.loads((run_dir / "perf.json").read_text()), depths, concs, task_errors(run_dir))
    s["perf_overview"] = lib.perf_overview(s["perf_grid"])
    if (run_dir / "tools.json").exists():
        s["tools"] = lib.tools_score(json.loads((run_dir / "tools.json").read_text()))
    rebuild_resources(run_dir, s)
    notes = [f"d{x['depth']}c{x['concurrency']}:{x['status']}" for x in s["perf_grid"] if x["status"] != "ok"]
    notes += [f"d{x['depth']}c{x['concurrency']}:{x['request_errors']['count']} failed requests"
              for x in s["perf_grid"] if x["status"] == "ok" and x.get("request_errors")]
    ph = s.get("phases", {}).get("performance")
    if ph is not None:
        if ph.get("status") in ("ok", "failed", "partial"):
            ph["status"] = "partial" if notes else "ok"
            ph["error"] = ("cells: " + ", ".join(notes)) if notes else None
        elif notes:
            ph["error"] = (ph.get("error") or "").split(" | cells:")[0] + " | cells: " + ", ".join(notes)
    (run_dir / "summary.json").write_text(lib.jdump(s))
    (run_dir / "summary.md").write_text(lib.render_summary(s))
    return s


def publish(run_dir: Path, s: dict) -> None:
    if s.get("smoke") or s.get("dry_run"):
        return
    pub = REPO / "runs" / run_dir.name
    shutil.rmtree(pub, ignore_errors=True)
    lib.sanitize_tree(run_dir, pub)
    sums = [json.loads(p.read_text()) for p in sorted((REPO / "runs").glob("*/summary.json"))]
    (REPO / "leaderboard.md").write_text(lib.leaderboard(sums))


def main(run_dir: Path, state_dir: Path | None) -> None:
    if state_dir:
        shutil.copytree(state_dir / "runs", run_dir / "perf-tasks", dirs_exist_ok=True)
    s = rebuild(run_dir)
    s["resummarized_with"] = (REPO / ".harness-commit").read_text().strip() if (REPO / ".harness-commit").exists() else None
    (run_dir / "summary.json").write_text(lib.jdump(s))
    publish(run_dir, s)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--relabel-published"]:
        relabel_published(Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else REPO / "runs")
    else:
        main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None)
