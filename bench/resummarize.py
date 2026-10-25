"""Rebuild a run's summary from its raw files with the current parsing logic.

Usage: resummarize.py <raw-run-dir> [<sparkrun-state-dir>]
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
    ba = yaml.safe_load((run_dir / "config.yaml").read_text())["performance"]["bench_args"]
    depths = s.get("perf_depths") or ba["depth"]
    concs = s.get("perf_concurrency") or ba["concurrency"]
    s["perf_grid"] = lib.perf_grid(json.loads((run_dir / "perf.json").read_text()), depths, concs, task_errors(run_dir))
    if (run_dir / "tools.json").exists():
        s["tools"] = lib.tools_score(json.loads((run_dir / "tools.json").read_text()))
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
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None)
