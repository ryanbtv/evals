"""Rebuild a run's summary from its raw files with the current parsing logic.

Usage: resummarize.py <raw-run-dir> [<sparkrun-state-dir>]
Copies <state-dir>/runs into perf-tasks/ when given, then rewrites summary.json/md,
republishes the sanitized copy to runs/ and regenerates leaderboard.md.
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


def main(run_dir: Path, state_dir: Path | None) -> None:
    if state_dir:
        shutil.copytree(state_dir / "runs", run_dir / "perf-tasks", dirs_exist_ok=True)
    errs = {}
    for log in sorted((run_dir / "perf-tasks").glob("*.log")):
        m = re.search(r"_d(\d+)_c(\d+)\.log$", log.name)
        if m:
            errs[(int(m[1]), int(m[2]))] = lib.request_errors(log.read_text(errors="replace"))
    ba = yaml.safe_load((run_dir / "config.yaml").read_text())["performance"]["bench_args"]
    s = json.loads((run_dir / "summary.json").read_text())
    s["perf_grid"] = lib.perf_grid(json.loads((run_dir / "perf.json").read_text()), ba["depth"], ba["concurrency"], errs)
    if (run_dir / "tools.json").exists():
        s["tools"] = lib.tools_score(json.loads((run_dir / "tools.json").read_text()))
    notes = [f"d{x['depth']}c{x['concurrency']}:{x['status']}" for x in s["perf_grid"] if x["status"] != "ok"]
    notes += [f"d{x['depth']}c{x['concurrency']}:{x['request_errors']['count']} failed requests"
              for x in s["perf_grid"] if x["status"] == "ok" and x.get("request_errors")]
    ph = s.get("phases", {}).get("performance")
    if ph is not None and notes:
        if ph.get("status") in ("ok", "failed", "partial"):
            ph["status"] = "partial"
            ph["error"] = "cells: " + ", ".join(notes)
        else:
            ph["error"] = (ph.get("error") or "").split(" | cells:")[0] + " | cells: " + ", ".join(notes)
    s["resummarized_with"] = (REPO / ".harness-commit").read_text().strip() if (REPO / ".harness-commit").exists() else None
    (run_dir / "summary.json").write_text(lib.jdump(s))
    (run_dir / "summary.md").write_text(lib.render_summary(s))
    if not s.get("smoke") and not s.get("dry_run"):
        pub = REPO / "runs" / run_dir.name
        shutil.rmtree(pub, ignore_errors=True)
        lib.sanitize_tree(run_dir, pub)
        sums = [json.loads(p.read_text()) for p in sorted((REPO / "runs").glob("*/summary.json"))]
        (REPO / "leaderboard.md").write_text(lib.leaderboard(sums))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None)
