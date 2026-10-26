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
