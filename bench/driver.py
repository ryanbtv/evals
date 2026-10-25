"""sparkrun benchmark harness driver. Run via ./bench/run <recipe-path>."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform as pyplatform
import shutil
import signal
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sh(cmd: list[str], timeout: int = 30) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return (p.stdout or p.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return f"<error: {e}>"


def tee_output(log_path: Path) -> None:
    """Duplicate this process's stdout/stderr (and children's) into harness.log."""
    tee = subprocess.Popen(["tee", "-a", str(log_path)], stdin=subprocess.PIPE, stdout=sys.__stdout__)
    os.dup2(tee.stdin.fileno(), 1)
    os.dup2(tee.stdin.fileno(), 2)
    sys.stdout = os.fdopen(1, "w", buffering=1, closefd=False)
    sys.stderr = os.fdopen(2, "w", buffering=1, closefd=False)


def harness_commit() -> str:
    out = sh(["git", "-C", str(REPO), "rev-parse", "HEAD"], 10)
    if len(out) == 40:
        dirty = sh(["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=no"], 10)
        return out + ("-dirty" if dirty else "")
    f = REPO / ".harness-commit"
    return f.read_text().strip() if f.exists() else "unknown"


def platform_info() -> dict:
    os_release = {}
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                os_release[k] = v.strip('"')
    except OSError:
        pass
    smi = sh(["nvidia-smi"], 30)
    cuda = next((ln.split("CUDA Version:")[1].strip(" |") for ln in smi.splitlines() if "CUDA Version:" in ln), None)
    try:
        from importlib.metadata import version
        sparkrun_version = version("sparkrun")
    except Exception:  # noqa: BLE001
        sparkrun_version = None
    return {
        "hostname_class": "NVIDIA DGX Spark",
        "gpu": sh(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,compute_cap", "--format=csv,noheader"]),
        "driver": sh(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"]),
        "cuda": cuda,
        "cpu_arch": pyplatform.machine(),
        "cpu_model": sh(["sh", "-c", "lscpu | grep -E 'Model name' | sort -u"]),
        "memory": sh(["free", "-h"]),
        "os": os_release.get("PRETTY_NAME"),
        "kernel": pyplatform.release(),
        "docker": sh(["docker", "version", "--format", "{{.Server.Version}}"]),
        "python": sys.version.split()[0],
        "sparkrun_version": sparkrun_version,
    }


class Harness:
    def __init__(self, recipe: Path, dry_run: bool, smoke: bool):
        self.recipe = recipe
        self.dry_run = dry_run
        self.smoke = smoke
        raw = yaml.safe_load((REPO / "bench" / "config.yaml").read_text())
        self.cfg = lib.effective_config(raw, smoke)
        self.recipe_doc = yaml.safe_load(recipe.read_text()) or {}
        defaults = self.recipe_doc.get("defaults") or {}
        self.model = defaults.get("served_model_name") or str(self.recipe_doc.get("model", recipe.stem))
        self.port = int(defaults.get("port") or 8000)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = "--dryrun" if dry_run else "--smoke" if smoke else ""
        self.run_id = f"{stamp}--{lib.slugify(recipe.stem)}{suffix}"
        self.dir = REPO / "raw-runs" / self.run_id
        self.dir.mkdir(parents=True)
        (self.dir / "diagnostics").mkdir()
        (self.dir / "ctf").mkdir()
        self.phases: dict[str, dict] = {}
        self.summary: dict = {}
        self.platform: dict = {}
        self.current_phase = "setup"
        self.workload_id: str | None = None
        self.launches = 0
        self.skip_run_calls = 0
        self.skip_run_ok = 0

    # ------------------------------------------------------------ plumbing
    def log(self, msg: str) -> None:
        print(f"[{now()}] [{self.current_phase}] {msg}", flush=True)

    def progress(self, ev) -> None:
        rec = {"ts": now(), "phase": self.current_phase, "kind": ev.kind, "data": dict(ev.data)}
        with open(self.dir / "progress.ndjson", "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        d = ev.data
        text = str(d.get("msg") or d.get("line") or "")
        if text.startswith("Pinned llama-benchy version:"):
            self.platform.setdefault("framework_versions", {})["llama-benchy"] = text.split(":", 1)[1].strip()
        if ev.kind in ("task_start",):
            self.log(f"task {d.get('index')} start: {d.get('label')}")
        elif ev.kind == "task_end":
            self.log(f"task {d.get('index')} end: success={d.get('success')} {d.get('duration_s')}s")
        elif ev.kind in ("warning", "error", "info", "banner", "schedule_started", "schedule_finished"):
            self.log(f"{ev.kind}: {d.get('msg') or d.get('line') or d.get('message') or d.get('title') or ''}")

    @staticmethod
    def decide(req) -> bool:
        return True if req.kind == "recipe_trust" else req.default

    def health(self) -> bool:
        if self.dry_run:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/v1/models", timeout=self.cfg["target"]["health_timeout_s"]) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001
            return False

    def bench(self, *, category: str, framework: str, bench_args: dict, output: Path, timeout: int):
        """One sparkrun benchmark call. Never raises. Returns (result|None, error|None)."""
        from sparkrun.api import BenchmarkFailed, BenchmarkFinalizationFailed, BenchmarkOptions, ResumeMode, benchmark

        skip = self.health()
        opts = BenchmarkOptions(
            recipe=str(self.recipe), category=category, framework=framework, bench_args=bench_args,
            solo=self.cfg["target"]["solo"], cluster=self.cfg["target"]["cluster"],
            skip_run=skip, no_stop=True, exit_on_first_fail=False, timeout=timeout,
            resume=ResumeMode.FRESH, output_file=str(output), trust=True, dry_run=self.dry_run,
            sync_tuning=False, progress_callback=self.progress, decision_callback=self.decide,
        )
        self.log(f"benchmark {framework} skip_run={skip} args={json.dumps(bench_args)}")
        if skip:
            self.skip_run_calls += 1
        result, err = None, None
        try:
            result = benchmark(opts, sctx=self.sctx)
        except BenchmarkFinalizationFailed as e:
            result, err = getattr(e, "result", None), f"BenchmarkFinalizationFailed: {e}"
        except BenchmarkFailed as e:
            result, err = getattr(e, "result", None), f"BenchmarkFailed: {e}"
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        if result is not None:
            if getattr(result, "run_result", None) is not None:
                self.launches += 1
            if getattr(result, "workload_id", None):
                self.workload_id = result.workload_id
            if skip and getattr(result, "run_result", None) is None:
                self.skip_run_ok += 1
            for k in ("container_image", "container_image_sha", "container_image_sha_pinned", "host_list"):
                v = getattr(result, k, None)
                if v:
                    self.platform.setdefault("container", {})[k] = list(v) if isinstance(v, tuple) else v
            if not result.success and not err:
                err = "benchmark reported success=False"
        if err:
            self.log(f"benchmark error: {err}")
        return result, err

    @staticmethod
    def results_of(result, output: Path) -> dict:
        # The exported JSON sidecar holds the framework's native shape; result.results
        # may wrap it (e.g. under "json"), so prefer the file.
        j = output.with_suffix(".json")
        if j.exists():
            try:
                data = json.loads(j.read_text())
                if isinstance(data, dict) and data:
                    return data
            except ValueError:
                pass
        res = (result.results if result is not None else None) or {}
        return res.get("json") if isinstance(res.get("json"), dict) else res

    def phase(self, name: str, fn) -> None:
        self.current_phase = name
        t0 = time.monotonic()
        rec = {"status": "running", "started_at": now()}
        self.phases[name] = rec
        diag = self.dir / "diagnostics" / f"{name}.ndjson"
        try:
            from sparkrun.api import capture_diagnostics
            with capture_diagnostics(str(diag), sctx=self.sctx, max_bytes=64 * 1024 * 1024, log_tail=2000, dry_run=self.dry_run):
                err = fn()
            rec["status"] = "failed" if err else "ok"
            rec["error"] = err
        except BaseException as e:  # noqa: BLE001
            traceback.print_exc()
            rec["status"], rec["error"] = "crashed", f"{type(e).__name__}: {e}"
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
        finally:
            rec["duration_s"] = round(time.monotonic() - t0, 1)
            rec["ended_at"] = now()
            self.log(f"phase {name}: {rec['status']} in {rec['duration_s']}s {rec.get('error') or ''}")
            self.write_summary()

    # ------------------------------------------------------------ phases
    def run_perf(self):
        c = self.cfg["performance"]
        out = self.dir / "perf.yaml"
        result, err = self.bench(category="performance", framework=c["framework"], bench_args=c["bench_args"], output=out, timeout=c["timeout_s"])
        res = self.results_of(result, out)
        self.summary["perf_grid"] = lib.perf_grid(res, c["bench_args"]["depth"], c["bench_args"]["concurrency"])
        if result is not None:
            self.platform["perf_metadata"] = result.metadata
        failed = [f"d{x['depth']}c{x['concurrency']}" for x in self.summary["perf_grid"] if not x["ok"]]
        if failed and not self.dry_run:
            err = (err + "; " if err else "") + "failed cells: " + ",".join(failed)
        return err

    def run_tools(self):
        c = self.cfg["tools"]
        out = self.dir / "tools.yaml"
        result, err = self.bench(category="tools", framework=c["framework"], bench_args=c["bench_args"], output=out, timeout=c["timeout_s"])
        self.summary["tools"] = lib.tools_score(self.results_of(result, out))
        self.platform["framework_versions"]["tool-eval-bench"] = self.summary["tools"].get("version") or c["bench_args"].get("ref")
        if result is not None:
            self.platform["tools_metadata"] = result.metadata
        return err

    def run_ctf(self):
        c = self.cfg["ctf"]
        by_depth, errors = {}, []
        for depth in c["depths"]:
            def probe(conc, depth=depth):
                out = self.dir / "ctf" / f"d{depth}_c{conc}.yaml"
                args = {**c["bench_args"], "depth": [depth], "concurrency": [conc]}
                result, err = self.bench(category="performance", framework=c["framework"], bench_args=args, output=out, timeout=c["timeout_s"])
                rows = [r for r in lib.benchy_rows(self.results_of(result, out)) if r["concurrency"] == conc]
                row = rows[0] if rows else {}
                ok = bool(row) and row.get("tg_req_tok_s") is not None
                if self.dry_run:  # fake a pass at c=1 only, so dry-run exercises exactly one probe
                    ok, row = conc == 1 and err is None, {"tg_req_tok_s": 0.0}
                self.log(f"CTF probe depth={depth} c={conc}: ok={ok} tg/req={row.get('tg_req_tok_s')} err={err}")
                return {"ok": ok, "error": err, **row}
            try:
                threshold = 0.0 if self.dry_run else float(c["threshold_tok_s"])
                ramp = c["ramp"][:2] if self.dry_run else c["ramp"]
                by_depth[str(depth)] = lib.find_ctf(probe, ramp, threshold)
                by_depth[str(depth)]["threshold_tok_s"] = c["threshold_tok_s"]
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                by_depth[str(depth)] = {"error": f"{type(e).__name__}: {e}"}
                errors.append(f"d{depth}: {e}")
            self.summary["ctf"] = {"threshold_tok_s": c["threshold_tok_s"], "by_depth": by_depth}
            (self.dir / "ctf.json").write_text(lib.jdump(self.summary["ctf"]))
        return "; ".join(errors) or None

    # ------------------------------------------------------------ outputs
    def write_summary(self) -> None:
        self.summary.update({
            "run_id": self.run_id, "model": self.model, "recipe_name": self.recipe.name,
            "smoke": self.smoke, "dry_run": self.dry_run, "phases": self.phases,
            "container_image": (self.platform.get("container") or {}).get("container_image"),
            "sparkrun_version": self.platform.get("sparkrun_version"), "harness_commit": self.platform.get("harness_commit"),
            "server_reuse": {"launches": self.launches, "skip_run_calls": self.skip_run_calls, "skip_run_ok": self.skip_run_ok},
        })
        (self.dir / "summary.json").write_text(lib.jdump(self.summary))
        (self.dir / "summary.md").write_text(lib.render_summary(self.summary))
        (self.dir / "platform.json").write_text(lib.jdump(self.platform))

    def stop_server(self) -> None:
        if self.dry_run:
            return
        self.current_phase = "teardown"
        try:
            from sparkrun.api import stop
            kw = {"workload_id": self.workload_id} if self.workload_id else {"recipe": str(self.recipe), "cluster": self.cfg["target"]["cluster"]}
            self.log(f"stopping inference via sparkrun.api.stop({kw})")
            r = stop(sctx=self.sctx, **kw)
            self.log(f"stop result: {r}")
        except Exception as e:  # noqa: BLE001
            self.log(f"api stop failed: {type(e).__name__}: {e}")
        for _ in range(12):
            if not self.health():
                break
            time.sleep(5)
        if self.health():
            self.log("server still up; falling back to `sparkrun stop <recipe>`")
            self.log(sh([str(Path.home() / ".local/bin/sparkrun"), "stop", str(self.recipe)], 300))
        self.platform["server_stopped"] = not self.health()

    def publish(self) -> None:
        if self.dry_run:
            return
        dest_root = REPO / ("smoke-runs" if self.smoke else "runs")
        dest = dest_root / self.run_id
        skipped = lib.sanitize_tree(self.dir, dest)
        self.log(f"published sanitized copy to {dest} (skipped binaries: {skipped})")
        if not self.smoke:
            sums = []
            for p in sorted((REPO / "runs").glob("*/summary.json")):
                try:
                    sums.append(json.loads(p.read_text()))
                except ValueError:
                    pass
            (REPO / "leaderboard.md").write_text(lib.leaderboard(sums))

    def preflight(self) -> None:
        """Stop other sparkrun workloads and GPU containers; record what was stopped."""
        self.current_phase = "preflight"
        pf = self.cfg.get("preflight") or {}
        rec = {"sparkrun_workloads": [], "systemd_units": [], "containers": [], "errors": []}
        self.platform["preflight"] = rec
        if self.dry_run:
            return
        for unit in pf.get("systemd_units") or []:
            if sh(["systemctl", "is-active", unit], 15) == "active":
                out = sh(["sudo", "-n", "systemctl", "stop", unit], 300)
                rec["systemd_units"].append({"unit": unit, "result": out or "stopped", "active_after": sh(["systemctl", "is-active", unit], 15)})
                self.log(f"stopped systemd unit {unit}: {out or 'ok'}")
        try:
            from sparkrun.api import status, stop
            st = status(cluster=self.cfg["target"]["cluster"], sctx=self.sctx)
            ids = {w.cluster_id: (w.recipe_name, h.host) for h in st.hosts for w in h.workloads}
            for wid, (recipe_name, host) in ids.items():
                self.log(f"stopping sparkrun workload {wid} ({recipe_name}) on {host}")
                try:
                    r = stop(workload_id=wid, sctx=self.sctx)
                    rec["sparkrun_workloads"].append({"workload_id": wid, "recipe": recipe_name, "host": host, "containers_removed": r.containers_removed, "errors": list(r.errors)})
                except Exception as e:  # noqa: BLE001
                    rec["errors"].append(f"stop {wid}: {e}")
        except Exception as e:  # noqa: BLE001
            rec["errors"].append(f"sparkrun status: {type(e).__name__}: {e}")
        ids = sh(["docker", "ps", "-q"], 30).split()
        if ids:
            try:
                inspected = json.loads(sh(["docker", "inspect", *ids], 60))
            except ValueError as e:
                inspected, _ = [], rec["errors"].append(f"docker inspect: {e}")
            for c in lib.gpu_containers_to_stop(inspected, pf.get("keep_containers") or []):
                c["result"] = sh(["docker", "stop", "-t", "60", c["name"]], 120)
                rec["containers"].append(c)
                self.log(f"docker stop {c['name']} ({c['image']}): {c['result']}")
        if not any(rec[k] for k in ("sparkrun_workloads", "systemd_units", "containers")):
            self.log("nothing to stop")
        for e in rec["errors"]:
            self.log(f"preflight error: {e}")

    def main(self) -> int:
        tee_output(self.dir / "harness.log")
        self.log(f"run {self.run_id} recipe={self.recipe} smoke={self.smoke} dry_run={self.dry_run}")
        shutil.copyfile(self.recipe, self.dir / "recipe.yml")
        (self.dir / "config.yaml").write_text(yaml.safe_dump(self.cfg, sort_keys=False))
        self.platform.update(platform_info())
        self.platform.update({"harness_commit": harness_commit(), "config": self.cfg, "run_id": self.run_id,
                              "framework_versions": {"tool-eval-bench": self.cfg["tools"]["bench_args"].get("ref")}})
        self.write_summary()
        # Frameworks such as tool-eval-bench drop report files into the cwd; keep them in the run dir.
        os.chdir(self.dir)
        from sparkrun.application import initialize
        self.sctx = initialize()
        self.preflight()
        self.write_summary()
        if self.health():
            self.log(f"ERROR: something already serves on port {self.port}; refusing to benchmark it")
            return 2
        try:
            self.phase("performance", self.run_perf)
            self.phase("tools", self.run_tools)
            self.phase("ctf", self.run_ctf)
        finally:
            self.stop_server()
            self.platform["framework_versions"].setdefault("llama-benchy", find_benchy_version(self.platform))
            if not self.platform["framework_versions"]["llama-benchy"]:
                self.platform["framework_versions"]["llama-benchy"] = find_benchy_version(self.platform)
            self.write_summary()
            try:
                self.publish()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            self.log("done")
        return 0


def find_benchy_version(platform: dict):
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if "version" in str(k).lower() and isinstance(v, str) and v[:1].isdigit():
                    yield k, v
                yield from walk(v)
    for k, v in walk(platform.get("perf_metadata") or {}):
        return v
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("recipe")
    ap.add_argument("--dry-run", action="store_true", help="validate every phase with sparkrun dry_run=True")
    a = ap.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    h = Harness(Path(a.recipe).resolve(), a.dry_run, os.environ.get("BENCH_SMOKE") == "1")
    return h.main()


if __name__ == "__main__":
    sys.exit(main())
