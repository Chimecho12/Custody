"""시나리오 기대 결과 고정. 05 검토서 §10.2 필수 사건의 기대치를 그대로 검사한다.

실패한 방어·탐지 불가 사건도 '기대된 결과' 로 검사한다. 성공 장면만 검사하는 스위트는
'모두 위반' 으로 판정하는 엔진에 높은 점수를 준다."""
import unittest
from functools import cache

from itx.sim import run_q1_matrix, run_scenario, scenario_by_id


@cache
def _run(sid: str, mode: str):
    return run_scenario(scenario_by_id(sid), mode, seed=42)


def _last(sid, mode):
    r = _run(sid, mode)
    return r, r["attempts"][-1]


def _codes(attempt):
    return {d["code"] for d in attempt["final_verdict"]["discrepancies"]}


class BaselineTest(unittest.TestCase):
    def test_S01_normal_all_modes(self):
        for mode, action in (("observe", "accept_unverified"), ("protect", "accept"), ("strict", "accept")):
            r, a = _last("S01", mode)
            fv = a["final_verdict"]
            self.assertEqual(fv["verification_status"], "passed", (mode, fv["discrepancies"]))
            self.assertEqual(fv["completeness"], "complete")
            self.assertEqual(fv["established_assurance"], "air-local")
            self.assertEqual(a["gate"]["action"], action)
            self.assertTrue(r["audit"]["ok"])
            self.assertTrue(all(x["ok"] for x in r["audit"]["anchors"]))
        # 관찰 모드는 결정 전에 소비한다 — 그것이 비용이다.
        _, a = _last("S01", "observe")
        self.assertTrue(a["gate"]["consumed_before_decision"])

    def test_S04_approved_fallback_not_blocked(self):
        _, a = _last("S04", "protect")
        self.assertEqual(a["final_verdict"]["verification_status"], "passed")
        self.assertEqual(a["gate"]["action"], "accept")
        self.assertEqual(a["final_verdict"]["equations"]["E8"]["detail"]["route_kind"], "declared_approved_fallback")


class IntegrityTest(unittest.TestCase):
    def test_S02_request_modification(self):
        _, a = _last("S02", "protect")
        self.assertEqual(a["final_verdict"]["verification_status"], "failed")
        self.assertIn("D-REQ-UNAPPROVED", _codes(a))
        self.assertEqual(a["final_verdict"]["equations"]["E3"]["result"], "pass")  # 진술은 모순 없음
        self.assertEqual(a["gate"]["action"], "quarantine")
        self.assertEqual(a["gate"]["local_checks"]["request_binding"]["result"], "fail")

    def test_S03_response_modification_counterexample(self):
        _, a = _last("S03", "protect")
        eq = a["final_verdict"]["equations"]
        self.assertEqual(eq["E6"]["result"], "pass")
        self.assertEqual(eq["E7"]["result"], "pass")
        self.assertEqual(eq["E10"]["result"], "fail")
        self.assertIn("D-RESP-UNAPPROVED", _codes(a))
        self.assertEqual(a["gate"]["action"], "quarantine")
        self.assertFalse(a["gate"]["consumed_before_decision"])
        self.assertFalse(a["metrics"]["harm_exposed"])
        _, o = _last("S03", "observe")
        self.assertTrue(o["metrics"]["harm_exposed"])  # 관찰 모드에서는 피해가 노출된다

    def test_S17_model_pre_exec_refuses(self):
        r, a = _last("S17", "protect")
        self.assertTrue(any(e["kind"] == "refused" and e["actor"] == "M" for e in r["timeline"]))
        self.assertIsNone(a["response_body"])
        self.assertEqual(a["final_verdict"]["completeness"], "not_observable")
        self.assertIn("D-REQ-UNAPPROVED", _codes(a))


class RoutingTest(unittest.TestCase):
    def test_S05_unapproved_declared_fallback(self):
        _, a = _last("S05", "protect")
        self.assertIn("D-ROUTE-UNAPPROVED", _codes(a))
        self.assertEqual(a["gate"]["action"], "quarantine")

    def test_S06_undeclared_fallback(self):
        _, a = _last("S06", "protect")
        self.assertIn("D-ROUTE-UNDECLARED", _codes(a))
        self.assertEqual(a["gate"]["action"], "quarantine")


class ReplayTest(unittest.TestCase):
    def test_S07_legit_retry(self):
        r = _run("S07", "protect")
        statuses = [x["final_verdict"]["verification_status"] for x in r["attempts"]]
        comps = [x["final_verdict"]["completeness"] for x in r["attempts"]]
        self.assertEqual(statuses, ["insufficient_evidence", "passed"])
        self.assertEqual(comps, ["not_observable", "complete"])
        self.assertEqual(r["attempts"][-1]["gate"]["action"], "accept")
        self.assertFalse(_codes(r["attempts"][0]) & {"D-RESP-UNAPPROVED", "D-REQ-UNAPPROVED"})

    def test_S08_replayed_response(self):
        r = _run("S08", "protect")
        first, second = r["attempts"]
        self.assertEqual(first["final_verdict"]["verification_status"], "passed")
        self.assertEqual(second["final_verdict"]["verification_status"], "failed")
        self.assertTrue({"D-NONCE", "D-ATTEMPT-MISMATCH"} <= _codes(second))
        self.assertEqual(second["gate"]["action"], "quarantine")
        self.assertEqual(second["gate"]["local_checks"]["nonce_match"]["result"], "fail")


class EvidenceAndAvailabilityTest(unittest.TestCase):
    def test_S09_missing_relay_is_gap_not_violation(self):
        _, a = _last("S09", "protect")
        fv = a["final_verdict"]
        self.assertEqual(fv["verification_status"], "passed")
        self.assertEqual(fv["completeness"], "gap")
        self.assertIn("D-GAP", _codes(a))
        self.assertTrue(all(d["severity"] == "observation" for d in fv["discrepancies"]))

    def test_S10_third_party_down(self):
        _, p = _last("S10", "protect")
        self.assertEqual(p["gate"]["action"], "accept")  # 로컬 증거로 계속
        _, s = _last("S10", "strict")
        self.assertEqual(s["gate"]["action"], "reject_timeout")
        self.assertEqual(s["final_verdict"]["verification_status"], "passed")  # 복구 후 재제출로 사후 판정
        self.assertIn("D-LATE", _codes(s))

    def test_S11_delay_costs_strict_only(self):
        _, p = _last("S11", "protect")
        _, s = _last("S11", "strict")
        self.assertEqual(p["gate"]["action"], "accept")
        self.assertEqual(s["gate"]["action"], "accept")
        self.assertGreaterEqual(s["gate"]["waited_ms"], 900)
        self.assertLess(p["gate"]["waited_ms"], 50)

    def test_availability_axis_separates_protect_from_strict_under_pressure(self):
        """무결성 검사가 가용성 스위치가 되면 안 된다. R 진술 보류·T 정지·지연·큐 포화 아래의 정상 요청을
        protect 는 전부 서비스하고, strict 는 T 없이는 거부한다 — 그 차이가 지표에 숫자로 남아야 한다."""
        from itx.metrics import aggregate
        _, s09 = _last("S09", "protect")
        self.assertTrue(s09["metrics"]["served"])
        self.assertEqual(s09["metrics"]["availability_pressure"], "relay_withholds_statement")
        runs = [_run(sid, mode) for sid in ("S09", "S10", "S11", "S12") for mode in ("protect", "strict")]
        summary = aggregate(runs)
        protect, strict = summary["protect"]["availability_under_pressure"], summary["strict"]["availability_under_pressure"]
        self.assertEqual(protect["den"], 7)
        self.assertEqual(protect["num"], protect["den"])
        self.assertLess(strict["num"], strict["den"])
        self.assertEqual(protect["causes"], ["queue_saturation", "relay_withholds_statement", "t_delay", "t_down"])
        self.assertEqual(summary["protect"]["availability_legit"]["denied"], {"gate_blocked": 0, "no_response": 0})

    def test_S12_queue_saturation_leaves_gaps(self):
        r = _run("S12", "protect")
        drops = sum(len(v) for v in r["ts"]["queue_drops"].values())
        self.assertGreater(drops, 0)
        self.assertTrue(any(a["final_verdict"]["completeness"] == "gap" for a in r["attempts"]))


class ThirdPartyTest(unittest.TestCase):
    def test_S13_misjudging_T_is_caught(self):
        r, a = _last("S13", "protect")
        self.assertEqual(a["final_verdict"]["verification_status"], "passed")  # T 의 오판
        self.assertEqual(a["gate"]["action"], "quarantine")  # U 는 T 를 맹신하지 않음
        self.assertFalse(r["audit"]["ok"])
        self.assertEqual(len(r["audit"]["verdict_mismatches"]), 1)
        self.assertEqual(r["audit"]["verdict_mismatches"][0]["recomputed"]["verification_status"], "failed")
        _, s = _last("S13", "strict")
        self.assertEqual(s["gate"]["action"], "quarantine")

    def test_S14_history_rewrite_detected_by_anchor(self):
        r, _ = _last("S14", "protect")
        self.assertFalse(all(x["ok"] for x in r["audit"]["anchors"]))
        self.assertFalse(r["audit"]["ok"])

    def test_S15_collusion_is_honestly_undetectable(self):
        r, a = _last("S15", "protect")
        self.assertTrue(r["scenario"]["ground_truth"]["attack_present"])
        self.assertFalse(r["scenario"]["ground_truth"]["detectable_by_evidence"])
        self.assertEqual(a["final_verdict"]["verification_status"], "passed")
        self.assertEqual(a["gate"]["action"], "accept")
        self.assertTrue(a["metrics"]["harm_exposed"])

    def test_S16_integrity_passes_but_tool_policy_blocks(self):
        _, a = _last("S16", "protect")
        self.assertEqual(a["final_verdict"]["verification_status"], "passed")
        self.assertEqual(a["gate"]["local_checks"]["tool_policy"]["result"], "fail")
        self.assertEqual(a["gate"]["action"], "quarantine")

    def test_S18_omitted_entries_are_seen_only_through_held_receipts(self):
        """T 가 항목을 빼고 재서명한 로그는 스스로 일관적이다. 영수증을 버린 감사는 통과하고,
        영수증을 보관한 감사만 누락을 본다. 이 차이를 기대 결과로 고정한다."""
        r, a = _last("S18", "protect")
        self.assertEqual(a["gate"]["action"], "accept")  # 사용자 쪽 사건은 정상이었다
        self.assertTrue(r["ts"]["omitted_indexes"])
        without = r["audit_without_held_receipts"]
        self.assertTrue(without["ok"])  # 트리·헤드·앵커·재실행 전부 일관 — 누락이 보이지 않는다
        self.assertEqual(without["subs_checked"], 0)
        audit = r["audit"]
        self.assertTrue(audit["tree_recomputed_matches_head"] and audit["head_signature_valid"])
        self.assertTrue(all(x["ok"] for x in audit["anchors"]))
        self.assertFalse(audit["ok"])
        held = audit["held_receipts"]
        self.assertEqual(held["held"], r["ts"]["held_receipts"])
        self.assertGreater(len(held["missing"]), 0)
        self.assertEqual(held["included"] + len(held["missing"]), held["held"])
        self.assertIn(a["sub"], {m["sub"] for m in held["missing"]})
        self.assertFalse(all(c["ok"] for c in held["receipt_checkpoints"]))
        # R·M 이 제출한 중계 진술·영수증의 누락도 그들의 보관 영수증으로 드러난다.
        self.assertEqual({m["holder"] for m in held["missing"]}, {"U", "R", "M"})
        self.assertEqual(held["scope"], "all_parties")
        self.assertEqual(r["ts"]["held_receipts_by_holder"]["R"], 1)

    def test_S01_held_receipts_are_all_included(self):
        r, _ = _last("S01", "protect")
        held = r["audit"]["held_receipts"]
        self.assertGreater(held["held"], 0)
        self.assertEqual(held["included"], held["held"])
        self.assertEqual(held["missing"], [])
        self.assertTrue(all(c["ok"] for c in held["receipt_checkpoints"]))


class TContributionTest(unittest.TestCase):
    """'제3자가 실제로 무엇을 더해 주는가' 에 대한 답을 고정한다. 사용 전 차단은 U 로컬 검증의 몫이라
    T 없이도 같아야 하고, T 는 실행 전 거부·서명된 탐지 기록·감사 발견을 더한다. strict 는 차단을
    더하지 못하고 가용성만 잃는다 — 이 결과가 바뀌면 문서의 주장도 같이 바꿔야 한다."""

    @classmethod
    def setUpClass(cls):
        from itx.sim import run_t_contribution, summarize_t_contribution
        cls.rows = {r["scenario_id"]: r for r in run_t_contribution(seed=42)}
        cls.summary = summarize_t_contribution(list(cls.rows.values()))

    def test_defense_before_use_does_not_depend_on_t(self):
        self.assertEqual(self.summary["defense_same_without_t"], self.summary["scenarios"])
        self.assertEqual(self.summary["attacks_blocked_local_only"], self.summary["attacks_blocked_with_t_protect"])
        self.assertEqual(self.summary["strict_block"], [])

    def test_what_t_adds(self):
        self.assertEqual(self.summary["pre_execution_refusal"], ["S17"])
        self.assertEqual(self.summary["audit_finding"], ["S13", "S14", "S18"])
        self.assertEqual(set(self.summary["signed_detection_record"]), {"S02", "S03", "S05", "S06", "S08", "S17"})
        s17 = self.rows["S17"]
        self.assertFalse(s17["local_only"]["model_refused_before_execution"])  # T 없이는 변조 요청이 실행된 뒤 격리된다
        self.assertTrue(s17["with_t_protect"]["model_refused_before_execution"])
        self.assertIsNone(s17["local_only"]["detected_by_verdict"])  # T 가 없으면 탐지 기록은 '0' 이 아니라 '없음'
        self.assertIsNone(s17["local_only"]["audit_finding"])

    def test_strict_costs_availability_without_adding_defense(self):
        for sid in ("S10", "S12"):
            self.assertEqual(self.rows[sid]["with_t_strict"]["gate_action"], "reject_timeout")
            self.assertEqual(self.rows[sid]["local_only"]["gate_action"], "accept")


class Q1MatrixTest(unittest.TestCase):
    def test_cooperation_sets_change_detectability(self):
        rows = {(r["scenario_id"], r["cooperation"]): r for r in run_q1_matrix(seed=42)}
        self.assertEqual(rows[("S03", "U")]["verification_status"], "insufficient_evidence")
        self.assertEqual(rows[("S03", "U+R")]["verification_status"], "insufficient_evidence")  # M 없이는 E10 불가
        self.assertEqual(rows[("S03", "U+M")]["verification_status"], "failed")
        self.assertEqual(rows[("S03", "U+R+M")]["verification_status"], "failed")
        self.assertEqual(rows[("S02", "U+M")]["verification_status"], "failed")
        self.assertIn("D-REQ-UNAPPROVED", rows[("S02", "U+M")]["codes"])


if __name__ == "__main__":
    unittest.main()
