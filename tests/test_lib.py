import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bench"))
import lib  # noqa: E402


def row(depth, conc, tg, tg_req=None, ctx=False):
    return {"context_size": depth, "concurrency": conc, "is_context_prefill_phase": ctx,
            "pp_throughput": {"mean": 1000.0, "values": [1000.0]}, "tg_throughput": {"mean": tg},
            "tg_req_throughput": None if tg_req is None else {"mean": tg_req}, "ttfr": 250}


class TestCTF(unittest.TestCase):
    def mk(self, speed_of):
        calls = []

        def probe(c):
            calls.append(c)
            s = speed_of(c)
            return {"ok": s is not None, "tg_req_tok_s": s}
        return probe, calls

    def test_bisect_exact(self):
        probe, calls = self.mk(lambda c: 100.0 / c)  # >=10 up to c=10
        r = lib.find_ctf(probe, [1, 2, 4, 8, 16, 32], 10.0)
        self.assertEqual(r["ctf"], 10)
        self.assertEqual(r["first_fail"], 11)
        self.assertEqual(len(calls), len(set(calls)))
        self.assertFalse(r["capped_at_ramp_max"])

    def test_request_failure_counts_as_fail(self):
        probe, _ = self.mk(lambda c: None if c >= 6 else 50.0)
        self.assertEqual(lib.find_ctf(probe, [1, 2, 4, 8], 10.0)["ctf"], 5)

    def test_first_probe_fails(self):
        probe, calls = self.mk(lambda c: 5.0)
        r = lib.find_ctf(probe, [1, 2, 4], 10.0)
        self.assertEqual((r["ctf"], r["first_fail"], calls), (0, 1, [1]))

    def test_capped(self):
        probe, _ = self.mk(lambda c: 99.0)
        r = lib.find_ctf(probe, [1, 2, 4], 10.0)
        self.assertEqual(r["ctf"], 4)
        self.assertTrue(r["capped_at_ramp_max"])

    def test_threshold_inclusive(self):
        probe, _ = self.mk(lambda c: 10.0 if c <= 3 else 9.99)
        self.assertEqual(lib.find_ctf(probe, [1, 2, 4], 10.0)["ctf"], 3)


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
                "perf_grid": lib.perf_grid({"benchmarks": [row(0, 1, 20.0)]}, [0, 131072], [1, 8]),
                "tools": {"final_score": 80}, "ctf": {"threshold_tok_s": 10, "by_depth": {
                    "0": {"ctf": 6, "first_fail": 7, "probes": [{"concurrency": 1, "ok": True, "tg_req_tok_s": 30.0}]},
                    "32768": {"error": "boom"}}}}

    def test_render(self):
        md = lib.render_summary(self.summary())
        self.assertIn("FAIL", md)
        self.assertIn("| 0 | 6 | 7 |", md)
        self.assertIn("x\\|y", md)
        self.assertIn("ERROR", md)

    def test_leaderboard(self):
        lb = lib.leaderboard([self.summary()])
        self.assertIn("| 20.0 |", lb)
        self.assertIn("| 6 |", lb)


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


class TestSanitize(unittest.TestCase):
    def test_sanitize(self):
        s = lib.sanitize_text("path /home/ryanb/x host dgx01.ff.lan ip 192.168.1.5 10.0.0.1 pub 8.8.8.8 "
                              "key -i /home/ryanb/.ssh/id_ed25519 Authorization: Bearer abcdefghij123 "
                              "api_key=sk-abcdefghijklmnopqrstuv HF_TOKEN=hf_abcdefghijklmnopqrstuvwx svc.ryanb.tv")
        for bad in ("/home/ryanb", "ff.lan", "192.168", "10.0.0.1", "id_ed25519", "abcdefghij123", "sk-abc", "hf_abc", "ryanb.tv"):
            self.assertNotIn(bad, s)
        self.assertIn("~/x", s)
        self.assertIn("8.8.8.8", s)


if __name__ == "__main__":
    unittest.main()
