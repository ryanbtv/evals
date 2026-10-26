"""sparkrun benchmark harness driver. Run via ./bench/run <recipe-path>."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform as pyplatform
import re
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
    def __init__(self, recipe: Path, dry_run: bool, smoke: bool, rerun_depth: int | None = None,
                 merge_into: Path | None = None, replaces: list[int] | None = None):
        self.recipe = recipe
        self.dry_run = dry_run
        self.smoke = smoke
        self.rerun_depth = rerun_depth
        self.merge_into = merge_into
        self.replaces = replaces
        raw = yaml.safe_load((REPO / "bench" / "config.yaml").read_text())
        self.cfg = lib.effective_config(raw, smoke)
        self.recipe_doc = yaml.safe_load(recipe.read_text()) or {}
        defaults = self.recipe_doc.get("defaults") or {}
        self.model = lib.display_model(self.recipe_doc, recipe.stem)
        self.served_model_name = defaults.get("served_model_name")
        self.port = int(defaults.get("port") or 8000)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if rerun_depth is not None:
            # Repair mode: one performance depth, results merged into an existing run.
            self.cfg["performance"]["bench_args"]["depth"] = [int(rerun_depth)]
            self.cfg["rerun"] = {"depth": int(rerun_depth), "merge_into": merge_into.name, "replaces": replaces}
            self.run_id = f"{merge_into.name}/rerun-{stamp}{'--dryrun' if dry_run else ''}"
            self.dir = merge_into / f"rerun-{stamp}{'--dryrun' if dry_run else ''}"
        else:
            suffix = "--dryrun" if dry_run else "--smoke" if smoke else ""
            self.run_id = f"{stamp}--{lib.slugify(recipe.stem)}{suffix}"
            self.dir = REPO / "raw-runs" / self.run_id
        self.dir.mkdir(parents=True)
        (self.dir / "diagnostics").mkdir()
        self.proxy = None
        self.phases: dict[str, dict] = {}
        self.results: dict = {}
        self.state_dirs: dict = {}
        self.benchmark_id: str | None = None
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
        if d.get("benchmark_id"):
            self.benchmark_id = d["benchmark_id"]
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
        self.benchmark_id = None
        try:
            result = benchmark(opts, sctx=self.sctx)
        except BenchmarkFinalizationFailed as e:
            result, err = getattr(e, "result", None), f"BenchmarkFinalizationFailed: {e}"
        except BenchmarkFailed as e:
            result, err = getattr(e, "result", None), f"BenchmarkFailed: {e}"
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        finally:
            sd = getattr(result, "state_dir", None) or (
                str(Path.home() / ".cache" / "sparkrun" / "benchmarks" / self.benchmark_id) if self.benchmark_id else None)
            self.state_dirs[output.stem] = sd
            self.recover(output, sd)
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

    def recover(self, output: Path, state_dir: str | None) -> None:
        """Rebuild <output>.json from sparkrun's per-task cache when the phase did not export it.

        Also runs while a SIGTERM/KeyboardInterrupt unwinds the benchmark call.
        """
        if self.dry_run or output.with_suffix(".json").exists():
            return
        try:
            if state_dir:
                sdir = Path(state_dir)
            elif self.benchmark_id:
                sdir = Path.home() / ".cache" / "sparkrun" / "benchmarks" / self.benchmark_id
            else:
                return
            runs = sdir / "runs"
            if not runs.is_dir():
                return
            tasks = []
            for f in sorted(runs.glob("*.json")):
                try:
                    tasks.append(json.loads(f.read_text()))
                except ValueError:
                    pass
            shutil.copytree(runs, self.dir / f"{output.stem}-tasks", dirs_exist_ok=True)
            data = lib.consolidate_tasks(tasks)
            if data:
                data["recovered_from_task_cache"] = True
                output.with_suffix(".json").write_text(lib.jdump(data))
                self.log(f"recovered {len(tasks)} task result(s) from {sdir} into {output.with_suffix('.json').name}")
        except Exception:  # noqa: BLE001
            traceback.print_exc()

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

    def phase(self, name: str, fn, summarize=None) -> None:
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
            if summarize is not None:
                try:
                    err = summarize(rec.get("error"))
                    if rec["status"] == "ok" and err:
                        rec["status"] = "failed"
                    rec["error"] = err
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
            rec["duration_s"] = round(time.monotonic() - t0, 1)
            rec["ended_at"] = now()
            self.log(f"phase {name}: {rec['status']} in {rec['duration_s']}s {rec.get('error') or ''}")
            self.write_summary()

    # ------------------------------------------------------------ phases
    def run_perf(self):
        c = self.cfg["performance"]
        result, err = self.bench(category="performance", framework=c["framework"], bench_args=c["bench_args"], output=self.dir / "perf.yaml", timeout=c["timeout_s"])
        if result is not None:
            self.platform["perf_metadata"] = result.metadata
        self.results["performance"] = result
        return err

    def summarize_perf(self, err):
        c = self.cfg["performance"]
        res = self.results_of(self.results.get("performance"), self.dir / "perf.yaml")
        errors = self.task_log_errors(self.dir / "perf.yaml")
        self.summary["perf_grid"] = lib.perf_grid(res, c["bench_args"]["depth"], c["bench_args"]["concurrency"], errors)
        notes = [f"d{x['depth']}c{x['concurrency']}:{x['status']}" for x in self.summary["perf_grid"] if x["status"] != "ok"]
        notes += [f"d{x['depth']}c{x['concurrency']}:{x['request_errors']['count']} failed requests"
                  for x in self.summary["perf_grid"] if x["status"] == "ok" and x.get("request_errors")]
        if notes and not self.dry_run:
            err = (err + "; " if err else "") + "cells: " + ", ".join(notes)
        return err

    def task_log_errors(self, output: Path) -> dict:
        """Copy the per-task logs/JSON into <stem>-tasks/ and count failed requests per (depth, conc)."""
        out: dict = {}
        sdir = self.state_dirs.get(output.stem)
        tasks = self.dir / f"{output.stem}-tasks"
        try:
            if sdir and (Path(sdir) / "runs").is_dir():
                shutil.copytree(Path(sdir) / "runs", tasks, dirs_exist_ok=True)
            for log in sorted(tasks.glob("*.log")) if tasks.is_dir() else []:
                m = re.search(r"_d(\d+)_c(\d+)\.log$", log.name)
                if m:
                    out[(int(m.group(1)), int(m.group(2)))] = lib.request_errors(log.read_text(errors="replace"))
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        return out

    def run_tools(self):
        c = self.cfg["tools"]
        result, err = self.bench(category="tools", framework=c["framework"], bench_args=c["bench_args"], output=self.dir / "tools.yaml", timeout=c["timeout_s"])
        if result is not None:
            self.platform["tools_metadata"] = result.metadata
        self.results["tools"] = result
        return err

    def summarize_tools(self, err):
        self.summary["tools"] = lib.tools_score(self.results_of(self.results.get("tools"), self.dir / "tools.yaml"))
        self.platform["framework_versions"]["tool-eval-bench"] = self.summary["tools"].get("version") or self.cfg["tools"]["bench_args"].get("ref")
        return err

    # ------------------------------------------------------------ outputs
    def write_summary(self) -> None:
        self.summary.update({
            "run_id": self.run_id, "model": self.model, "served_model_name": self.served_model_name, "recipe_name": self.recipe.name,
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
        unit = pf.get("proxy_unit")
        if unit:
            self.proxy = lib.ProxyGuard(unit, lambda argv: sh(argv, 300), now, self.log)
            self.platform["proxy"] = self.proxy.record
            self.proxy.stop()
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
        try:
            self.preflight()
            self.write_summary()
            if self.health():
                self.log(f"ERROR: something already serves on port {self.port}; refusing to benchmark it")
                return 2
            self.phase("performance", self.run_perf, self.summarize_perf)
            if self.rerun_depth is None:
                self.phase("tools", self.run_tools, self.summarize_tools)
        finally:
            self.stop_server()
            self.current_phase = "teardown"
            if self.proxy is not None:
                try:
                    self.proxy.restore()
                except BaseException:  # noqa: BLE001
                    traceback.print_exc()
            self.platform["framework_versions"].setdefault("llama-benchy", find_benchy_version(self.platform))
            if not self.platform["framework_versions"]["llama-benchy"]:
                self.platform["framework_versions"]["llama-benchy"] = find_benchy_version(self.platform)
            self.write_summary()
            try:
                if self.rerun_depth is not None:
                    self.merge()
                else:
                    self.publish()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            self.log("done")
        return 0

    def merge(self) -> None:
        """Repair mode: fold this re-run's depth into the parent run, superseding old depths."""
        if self.dry_run:
            self.log("dry-run: skipping merge")
            return
        import resummarize
        parent, rerun = self.merge_into, self.dir.name
        s = json.loads((parent / "summary.json").read_text())
        ba = yaml.safe_load((parent / "config.yaml").read_text())["performance"]["bench_args"]
        depths = s.get("perf_depths") or ba["depth"]
        d = int(self.rerun_depth)
        replaced = sorted(set(self.replaces) if self.replaces else {x for x in depths if x >= d})
        new = json.loads((self.dir / "perf.json").read_text()) if (self.dir / "perf.json").exists() else {}
        if not lib.benchy_rows(new):
            self.log("re-run produced no measured rows; parent run left unchanged")
            return
        sup = parent / "superseded"
        (sup / "perf-tasks").mkdir(parents=True, exist_ok=True)
        old = json.loads((parent / "perf.json").read_text())
        for ext in ("json", "yaml", "csv"):
            f = parent / f"perf.{ext}"
            if f.exists():
                shutil.move(str(f), str(sup / f"perf-before-{rerun}.{ext}"))
        for x in replaced:
            for f in (parent / "perf-tasks").glob(f"*_d{x}_c*"):
                shutil.move(str(f), str(sup / "perf-tasks" / f.name))
        (parent / "perf.json").write_text(lib.jdump(lib.merge_perf(old, new, replaced)))
        note = (f"Depth {d} was re-run on {now()} with `--rerun-perf-depth` ({rerun}/) and merged here. "
                f"It replaces depth(s) {replaced}; their raw data is kept under superseded/.")
        (sup / "README.md").write_text(f"# Superseded data\n\n{note}\n\n"
                                       f"`perf-before-{rerun}.*` is the run's perf output before the merge; "
                                       "`perf-tasks/` holds the replaced cells' task files.\n")
        s["perf_depths"] = sorted((set(depths) - set(replaced)) | {d})
        s.setdefault("notes", []).append(note)
        ph = dict(self.phases.get("performance") or {})
        s.setdefault("phases", {})[f"performance ({rerun}, depth {d})"] = ph
        s.setdefault("reruns", []).append({"dir": rerun, "depth": d, "replaces": replaced, "harness_commit": self.platform.get("harness_commit"),
                                           "phase": ph, "proxy": self.platform.get("proxy"), "container": self.platform.get("container")})
        (parent / "summary.json").write_text(lib.jdump(s))
        s = resummarize.rebuild(parent)
        resummarize.publish(parent, s)
        self.log(f"merged depth {d} into {parent.name}; replaced {replaced}; published")


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
    ap = argparse.ArgumentParser(description="Normal use: ./bench/run <recipe>. The --rerun-* options are a repair tool.")
    ap.add_argument("recipe")
    ap.add_argument("--dry-run", action="store_true", help="validate every phase with sparkrun dry_run=True")
    ap.add_argument("--rerun-perf-depth", type=int, help="REPAIR: re-run only this performance depth (config pp/tg/runs/concurrency)")
    ap.add_argument("--merge-into", help="REPAIR: raw run dir (raw-runs/<id> or runs/<id>) to merge the re-run into")
    ap.add_argument("--replaces-depth", type=int, action="append", help="REPAIR: depth(s) the re-run supersedes (default: all >= the re-run depth)")
    a = ap.parse_args()
    merge_into = None
    if (a.rerun_perf_depth is None) != (a.merge_into is None):
        ap.error("--rerun-perf-depth and --merge-into go together")
    if a.merge_into:
        merge_into = REPO / "raw-runs" / Path(a.merge_into).name
        if not (merge_into / "summary.json").exists():
            ap.error(f"no raw run at {merge_into}")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(130))
    h = Harness(Path(a.recipe).resolve(), a.dry_run, os.environ.get("BENCH_SMOKE") == "1",
                a.rerun_perf_depth, merge_into, a.replaces_depth)
    return h.main()


if __name__ == "__main__":
    sys.exit(main())
