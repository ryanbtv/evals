import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bench"))
import lib  # noqa: E402


def row(depth, conc, tg, tg_req=None, ctx=False):
    return {"context_size": depth, "concurrency": conc, "is_context_prefill_phase": ctx,
            "pp_throughput": {"mean": 1000.0, "values": [1000.0]}, "tg_throughput": {"mean": tg},
            "tg_req_throughput": None if tg_req is None else {"mean": tg_req}, "ttfr": 250}


class TestRecovery(unittest.TestCase):
    def test_consolidate_benchy_tasks(self):
        out = lib.consolidate_tasks([{"model": "m", "benchmarks": [row(65536, 1, 20.0)]}, {}, {"model": "m", "benchmarks": [row(65536, 4, 40.0, 10.0)]}])
        self.assertEqual((out["model"], out["max_concurrency"], len(out["benchmarks"])), ("m", 4, 2))
        self.assertTrue(lib.perf_grid(out, [65536], [4])[0]["ok"])

    def test_consolidate_tool_suite_and_empty(self):
        self.assertEqual(lib.consolidate_tasks([{"final_score": 90, "scores": {}}])["final_score"], 90)
        self.assertEqual(lib.consolidate_tasks([]), {})


class TestParsing(unittest.TestCase):
    def test_rows_and_grid(self):
        res = {"benchmarks": [row(0, 1, 20.0), row(4096, 1, 18.0, ctx=True), row(4096, 1, 17.0), row(0, 2, 36.0, 18.0)]}
        g = lib.perf_grid(res, [0, 4096], [1, 2])
        cell = {(c["depth"], c["concurrency"]): c for c in g}
        self.assertEqual(cell[(0, 1)]["tg_req_tok_s"], 20.0)  # c=1: per-request == aggregate
        self.assertEqual(cell[(0, 2)]["tg_tok_s"], 36.0)
        self.assertEqual(cell[(0, 2)]["tg_req_tok_s"], 18.0)
        self.assertEqual(cell[(4096, 1)]["tg_tok_s"], 17.0)  # context-prefill row ignored
        self.assertFalse(cell[(4096, 2)]["ok"])
        self.assertEqual(cell[(0, 1)]["ttfr_ms"], 250.0)

    def test_metric_mean(self):
        self.assertEqual(lib.metric_mean({"values": [1, 3]}), 2.0)
        self.assertIsNone(lib.metric_mean(None))
        self.assertIsNone(lib.metric_mean(True))

    def test_tools_score(self):
        t = lib.tools_score({"final_score": 81.5, "scores": {"max_points": 10, "scenario_results": [
            {"status": "pass"}, {"status": "fail"}, {"status": "pass"}]}, "trial_statistics": {"trials": 3}})
        self.assertEqual((t["final_score"], t["pass"], t["fail"], t["trials"]), (81.5, 2, 1, 3))

    def test_effective_config_smoke(self):
        raw = {"performance": {"bench_args": {"depth": [0, 1], "runs": 3, "pp": [2048]}}, "smoke": {"performance": {"bench_args": {"depth": [0]}}}}
        self.assertEqual(lib.effective_config(raw, False)["performance"]["bench_args"]["depth"], [0, 1])
        s = lib.effective_config(raw, True)["performance"]["bench_args"]
        self.assertEqual((s["depth"], s["pp"]), ([0], [2048]))


class TestSummary(unittest.TestCase):
    def summary(self):
        return {"run_id": "20260101T000000Z--m", "model": "m", "phases": {"performance": {"status": "failed", "duration_s": 5, "error": "x|y"}},
                "perf_grid": lib.perf_grid({"benchmarks": [row(65536, 1, 20.0)]}, [65536, 259968], [1, 4]),
                "tools": {"final_score": 80}}

    def test_render(self):
        md = lib.render_summary(self.summary())
        self.assertIn("FAIL", md)
        self.assertIn("x\\|y", md)
        self.assertNotIn("oncurrency to failure", md)

    def test_leaderboard(self):
        lb = lib.leaderboard([self.summary()])
        self.assertIn("| 20.0 |", lb)
        self.assertIn("| FAIL |", lb)
        self.assertIn("| 80 |", lb)


class TestPreflight(unittest.TestCase):
    def test_gpu_containers(self):
        def c(name, running=True, dev=False, runtime="runc", env=()):
            return {"Name": "/" + name, "Id": "abcdef1234567890", "State": {"Running": running},
                    "HostConfig": {"DeviceRequests": [{"Driver": "nvidia"}] if dev else None, "Runtime": runtime},
                    "Config": {"Image": "img", "Env": list(env)}}
        got = lib.gpu_containers_to_stop([
            c("caddy"), c("bifrost", dev=True), c("vllm-stack", dev=True), c("old", running=False, dev=True),
            c("rt", runtime="nvidia"), c("envgpu", env=["NVIDIA_VISIBLE_DEVICES=all"]), c("envvoid", env=["NVIDIA_VISIBLE_DEVICES=void"]),
        ], keep=["caddy", "bifrost", "dockhand", "dockhand-postgres"])
        self.assertEqual([x["name"] for x in got], ["vllm-stack", "rt", "envgpu"])


class TestPartialCells(unittest.TestCase):
    LOG = ("Running test: pp=2048, tg=128, depth=259968, concurrency=1\n"
           "  Run 1/3 (Inference, batch size 1)...\n"
           'HTTP 400: {"object":"error","message":"Requested token count exceeds the model\'s maximum context length of 262144 tokens. You requested a total of 262145 tokens"}\n'
           'HTTP 400: {"object":"error","message":"again"}\n')

    def test_context_only_cell_is_partial(self):
        empty = {"context_size": 259968, "concurrency": 1, "is_context_prefill_phase": False, "pp_throughput": None,
                 "tg_throughput": None, "tg_req_throughput": None, "ttfr": None}
        res = {"benchmarks": [row(259968, 1, 15.8, ctx=True), empty]}
        errs = {(259968, 1): lib.request_errors(self.LOG)}
        cell = lib.perf_grid(res, [259968], [1], errs)[0]
        self.assertEqual((cell["status"], cell["ctx_only"], cell["tg_tok_s"]), ("partial", True, 15.8))
        self.assertEqual(cell["request_errors"]["count"], 2)
        self.assertEqual(lib.cell_text(cell, "tg_tok_s", 1), "15.8†")
        md = lib.render_summary({"perf_grid": [cell]})
        self.assertIn("15.8†", md)
        self.assertIn("262145 tokens", md)

    def test_ok_cell_with_some_failed_requests(self):
        res = {"benchmarks": [row(259968, 2, 18.9, 18.9)]}
        cell = lib.perf_grid(res, [259968], [2], {(259968, 2): lib.request_errors(self.LOG)})[0]
        self.assertEqual(cell["status"], "ok")
        self.assertEqual(lib.cell_text(cell, "tg_tok_s", 1), "18.9*")
        self.assertEqual(lib.cell_text(lib.perf_grid({}, [1], [1])[0], "tg_tok_s", 1), "FAIL")

    def test_request_errors_none(self):
        self.assertEqual(lib.request_errors("all good\n")["count"], 0)


class TestProxyGuard(unittest.TestCase):
    def fake(self, active):
        state = {"active": active, "calls": []}

        def run(argv):
            state["calls"].append(argv[-2] if argv[0] == "sudo" else "is-active")
            if argv[0] == "sudo":
                state["active"] = argv[-2] == "start"
                return ""
            return "active" if state["active"] else "inactive"
        ticks = iter(["t1", "t2", "t3"])
        return state, lib.ProxyGuard("sparkrun-proxy.service", run, lambda: next(ticks), log=lambda *_: None)

    def test_stops_and_restores_once(self):
        state, g = self.fake(True)
        g.stop()
        self.assertFalse(state["active"])
        g.restore()
        g.restore()
        self.assertTrue(state["active"])
        self.assertEqual(state["calls"].count("start"), 1)
        self.assertEqual((g.record["stopped_at"], g.record["started_at"], g.record["active_after_restart"]), ("t1", "t2", True))

    def test_inactive_unit_left_alone(self):
        state, g = self.fake(False)
        g.stop()
        g.restore()
        self.assertNotIn("stop", state["calls"])
        self.assertNotIn("start", state["calls"])
        self.assertIsNone(g.record["stopped_at"])

    def test_restore_without_stop_is_noop(self):
        state, g = self.fake(True)
        g.restore()
        self.assertEqual(state["calls"], [])


class TestMerge(unittest.TestCase):
    def test_merge_replaces_depth(self):
        orig = {"model": "m", "benchmarks": [row(65536, 1, 24.0), row(259968, 1, 15.8, ctx=True), row(259968, 2, 18.9)]}
        new = {"model": "m", "benchmarks": [row(259840, 1, 16.0, ctx=True), row(259840, 1, 16.5)]}
        m = lib.merge_perf(orig, new, [259968])
        self.assertEqual(sorted({b["context_size"] for b in m["benchmarks"]}), [65536, 259840])
        self.assertEqual(m["merged"], {"replaced_depths": [259968], "kept_rows": 1, "rerun_rows": 2})
        g = {(c["depth"], c["concurrency"]): c for c in lib.perf_grid(m, [65536, 259840], [1])}
        self.assertEqual((g[(259840, 1)]["status"], g[(259840, 1)]["tg_tok_s"]), ("ok", 16.5))

    def test_notes_rendered(self):
        self.assertIn("> **Note:** merged", lib.render_summary({"notes": ["merged"]}))


class TestSanitize(unittest.TestCase):
    def test_sanitize(self):
        s = lib.sanitize_text("path /home/ryanb/x host dgx01.ff.lan ip 192.168.1.5 10.0.0.1 pub 8.8.8.8 "
                              "key -i /home/ryanb/.ssh/id_ed25519 Authorization: Bearer abcdefghij123 "
                              "api_key=sk-abcdefghijklmnopqrstuv HF_TOKEN=hf_abcdefghijklmnopqrstuvwx svc.ryanb.tv")
        for bad in ("/home/ryanb", "ff.lan", "192.168", "10.0.0.1", "id_ed25519", "abcdefghij123", "sk-abc", "hf_abc", "ryanb.tv"):
            self.assertNotIn(bad, s)
        self.assertIn("~/x", s)
        self.assertIn("8.8.8.8", s)


class TestResources(unittest.TestCase):
    GB = 1024 ** 3

    def s(self, phase, avail_gb, healthy=False, **kw):
        return {"phase": phase, "mem_total": 120 * self.GB, "mem_available": avail_gb * self.GB, "healthy": healthy, **kw}

    def test_parse_meminfo_and_smi(self):
        mi = lib.parse_meminfo("MemTotal:       127597524 kB\nMemFree: 1 kB\nMemAvailable:   13918012 kB\n")
        self.assertEqual(mi, {"total": 127597524 * 1024, "available": 13918012 * 1024})
        self.assertEqual(lib.parse_smi("96, 69.98, 79\n"), {"gpu_util_pct": 96.0, "power_w": 69.98, "temp_c": 79.0})
        self.assertEqual(lib.parse_smi("[N/A], [N/A], 40"), {"temp_c": 40.0})
        self.assertEqual(lib.parse_smi("<error: x>"), {})

    def test_summarize(self):
        samples = [self.s("baseline", 110), self.s("baseline", 112), self.s("performance", 100),
                   self.s("performance", 30, True, gpu_util_pct=90, power_w=70, container_mem=8 * self.GB),
                   self.s("performance", 20, True, gpu_util_pct=100, power_w=80), self.s("tools", 25, True), {"phase": "x"}]
        r = lib.summarize_resources(samples)
        self.assertEqual((r["baseline_used_gib"], r["loaded_used_gib"], r["model_footprint_gib"]), (8.0, 90.0, 82.0))
        self.assertEqual((r["peak_used_gib"], r["min_available_gib"], r["mem_total_gib"]), (100.0, 20.0, 120.0))
        p = r["phases"]["performance"]
        self.assertEqual((p["gpu_util_mean_pct"], p["power_max_w"], p["container_peak_gib"], p["samples"]), (95.0, 80, 8.0, 3))
        self.assertEqual(lib.summarize_resources([]), {})

    def test_parse_vllm_log(self):
        log = ("INFO [model_runner.py:412] Model loading took 73.92 GiB memory and 46.6 seconds\n"
               "INFO Initial free memory 114.59 GiB, reserved 9.31 GiB memory for KV Cache as specified\n"
               "INFO GPU KV cache size: 328,932 tokens, Maximum concurrency for 262,144 tokens per request: 1.25x\n"
               "INFO Running: 1 reqs, Waiting: 3 reqs, GPU KV cache usage: 12.1%, Prefix cache hit rate: 0.0%\n"
               "INFO Running: 2 reqs, Waiting: 0 reqs, GPU KV cache usage: 98.5%\n"
               "WARNING Sequence group 7 is preempted by PreemptionMode.RECOMPUTE\n")
        r = lib.parse_server_log(log)
        self.assertEqual((r["kv_tokens"], r["weights_gib"], r["kv_cache_gib"], r["kv_usage_peak_pct"]), (328932, 73.92, 9.31, 98.5))
        self.assertEqual((r["kv_max_concurrency"]["x"], r["max_waiting_requests"], r["preemptions"], r["retractions"]), (1.25, 3, 1, 0))

    def test_parse_sglang_log(self):
        log = ("max_total_num_tokens=412345, chunked_prefill_size=8192, max_running_requests=48, retract_decode_steps=20\n"
               "Decode batch. #running-req: 4, #token: 400000, token usage: 0.97, #queue-req: 2\n"
               "KV cache pool is full. Retract requests. #retracted_reqs: 1\n")
        r = lib.parse_server_log(log)
        self.assertEqual((r["kv_tokens"], r["max_running_requests"], r["kv_usage_peak_pct"], r["max_waiting_requests"]), (412345, 48, 97.0, 2))
        self.assertEqual(r["retractions"], 1)

    def test_resource_config(self):
        doc = {"runtime": "sglang", "container": "img@sha", "defaults": {"gpu_memory_utilization": 0.5, "port": 8000},
               "command": "launch --mem-fraction-static {gpu_memory_utilization} --chunked-prefill-size 8192"}
        self.assertEqual(lib.resource_config(doc), {"runtime": "sglang", "container": "img@sha", "gpu_memory_utilization": 0.5,
                                                    "--mem-fraction-static": 0.5, "--chunked-prefill-size": "8192"})

    def test_render_and_leaderboard_missing(self):
        old = {"run_id": "r1", "model": "m", "perf_grid": []}
        self.assertNotIn("## Resources", lib.render_summary(old))
        row = lib.leaderboard([old]).splitlines()[-1]
        self.assertTrue(row.endswith("| — | — | — |"), row)
        new = {**old, "resources": {"memory": lib.summarize_resources([self.s("baseline", 110), self.s("performance", 30, True)]),
                                    "server": {"kv_tokens": 5}, "config": {"runtime": "vllm"}}}
        md = lib.render_summary(new)
        self.assertIn("## Resources", md)
        self.assertIn("| 120.0 | 10.0 | 90.0 | 80.0 | 90.0 | 30.0 |", md)
        self.assertTrue(lib.leaderboard([new]).splitlines()[-1].endswith("| 80.0 | 90.0 | 30.0 |"))


@unittest.skipUnless(__import__("importlib").util.find_spec("yaml"), "driver needs PyYAML")
class TestSampler(unittest.TestCase):
    def test_sampler_never_raises_and_stops(self):
        import tempfile
        import time
        import driver
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "resources.jsonl"
            smp = driver.ResourceSampler(p, 0.05, lambda: "performance", lambda: True)
            smp.write(smp.sample("baseline"))
            smp.start()
            time.sleep(0.2)
            t0 = time.monotonic()
            smp.stop()
            self.assertLess(time.monotonic() - t0, 10)
            self.assertFalse(smp.thread.is_alive())
            lines = p.read_text().splitlines()
            self.assertGreaterEqual(len(lines), 2)
            self.assertEqual(__import__("json").loads(lines[0])["phase"], "baseline")


class TestOverview(unittest.TestCase):
    def test_overview_rows_and_missing(self):
        grid = [{"depth": 65536, "concurrency": 1, "status": "ok", "tg_tok_s": 24.08, "tg_req_tok_s": 24.08, "pp_tok_s": 207.5},
                {"depth": 65536, "concurrency": 4, "status": "ok", "tg_tok_s": 7.21, "tg_req_tok_s": 5.83, "pp_tok_s": 86.96},
                {"depth": 259840, "concurrency": 1, "status": "fail"}]
        ov = lib.perf_overview(grid)
        self.assertEqual(ov["columns"], ["c1", "c4"])
        md = "\n".join(lib.render_overview(ov))
        self.assertIn("| metric, depth | c1 | c4 |", md)
        self.assertIn("| Aggregate decode tok/s, 65536 | 24.1 | 7.2 |", md)
        self.assertIn("| Per-request decode tok/s, 65536 | 24.1 | 5.8 |", md)
        self.assertIn("| Prefill tok/s, 65536 | 208 | 87 |", md)
        self.assertIn("| Prefill tok/s, 259840 | FAIL | — |", md)
        self.assertEqual([r["metric"] for r in ov["rows"]][::2], ["Aggregate decode tok/s", "Per-request decode tok/s", "Prefill tok/s"])
        self.assertEqual(lib.render_overview(lib.perf_overview([])), [])


class TestDisplayModel(unittest.TestCase):
    def test_prefers_recipe_model(self):
        doc = {"model": "RadixArk/Qwen3.8-27B-NVFP4", "defaults": {"served_model_name": "qwen3.8-27b"}}
        self.assertEqual(lib.display_model(doc, "stem"), "RadixArk/Qwen3.8-27B-NVFP4")

    def test_fallbacks(self):
        self.assertEqual(lib.display_model({"defaults": {"served_model_name": "q"}}, "stem"), "q")
        self.assertEqual(lib.display_model({}, "stem"), "stem")
        self.assertEqual(lib.display_model(None, "stem"), "stem")


if __name__ == "__main__":
    unittest.main()
