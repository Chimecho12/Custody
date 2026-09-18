"""장기 가용성 실측: T 가 죽었다 살아나는 동안 protect 는 계속 서비스하고, strict 는 정지 중 거부하되
복구 뒤 적체가 비고 모든 요청이 사후 판정을 받아야 한다. 복구 뒤 감사도 통과해야 한다."""
import json
import tempfile
import unittest
from pathlib import Path

from itx.crypto import HAS_CRYPTOGRAPHY
from itx.runtime.endurance import parse_outage


class OutageWindowTest(unittest.TestCase):
    def test_window_parsing(self):
        self.assertEqual(parse_outage("2:4", 6), (2, 4))
        for bad in ("4:2", "0:7", "x", "3"):
            with self.assertRaises(ValueError):
                parse_outage(bad, 6)


@unittest.skipUnless(HAS_CRYPTOGRAPHY, "network runtime requires cryptography")
class EnduranceRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from itx.runtime.endurance import endurance
        cls.temp = tempfile.TemporaryDirectory(prefix="itx-endurance-test-")
        cls.output = Path(cls.temp.name) / "endurance.json"
        # strict 대기를 줄여 정지 구간의 거부를 빨리 받는다 (기본 2,500 ms). 복구 직후의 요청은 밀린 증거를
        # 먼저 흘려보내고 M 의 영수증 제출(0.2 s 주기)도 기다려야 하므로 너무 짧게 잡으면 정상 회복도 거부로 보인다.
        cls.report = endurance(cls.output, requests=6, outage="2:4", strict_timeout_ms=1500)
        cls.by_mode = {r["mode"]: r for r in cls.report["results"]}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_report_is_written_and_labelled_mock(self):
        self.assertTrue(self.output.exists())
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8"))["claim_status"], "mock_result")

    def test_protect_keeps_serving_through_the_outage(self):
        p = self.by_mode["protect"]["by_phase"]
        for phase in ("before", "outage", "after"):
            self.assertEqual(p[phase]["served"], p[phase]["requests"], (phase, p[phase]))
        self.assertGreater(p["outage"]["max_backlog"], 0)  # 정지 중 증거는 큐에 쌓인다

    def test_strict_refuses_during_outage_but_recovers(self):
        s = self.by_mode["strict"]
        self.assertEqual(s["by_phase"]["outage"]["served"], 0)
        self.assertEqual(s["by_phase"]["outage"]["states"], ["reject_timeout"])
        self.assertEqual(s["by_phase"]["after"]["served"], s["by_phase"]["after"]["requests"])

    def test_backlog_clears_and_every_request_gets_a_verdict(self):
        for mode, r in self.by_mode.items():
            self.assertTrue(r["backlog_cleared"], mode)
            self.assertIsNotNone(r["recovery_ms_after_restart"], mode)
            self.assertTrue(r["all_verdicts_eventually"], (mode, r["verdicts_eventually"]))
            self.assertTrue(r["audit_ok_after_recovery"], mode)
            self.assertEqual(r["held_receipts_missing"], 0)


if __name__ == "__main__":
    unittest.main()
