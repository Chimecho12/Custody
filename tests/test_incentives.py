"""인센티브 원장: '부당한 책임 없음' 은 구조적으로, '편익 > 비용' 은 가설 단위로 따로 검사한다.

구조 결과(누가 지목되는가)는 단위 파라미터와 무관해야 한다. 파라미터를 바꿔도 지목은 그대로다.
"""
import unittest
from functools import cache

from itx.sim import IncentiveParams, ledger_for_run, run_scenario, scenario_by_id, summarize_ledgers
from itx.sim.incentives import culprits_for
from itx.sim.runner import MODES
from itx.sim.scenarios import SCENARIOS


@cache
def _rows():
    return [ledger_for_run(run_scenario(sc, mode, seed=42)) for sc in SCENARIOS for mode in MODES]


class StructuralTest(unittest.TestCase):
    def test_no_honest_party_is_ever_blamed(self):
        s = summarize_ledgers(_rows())
        self.assertTrue(s["structural"]["no_unjust_liability"], s["per_party"])
        self.assertEqual(s["structural"]["unjust_liability_total"], 0)

    def test_attacks_with_a_culprit_are_resolved_except_collusion(self):
        s = summarize_ledgers(_rows())
        self.assertEqual(s["structural"]["attacks_unresolved"], ["S15"])   # 공모는 증거 구조가 보지 못한다
        self.assertEqual(s["structural"]["attacks_without_party"], ["S16"])  # 인젝션은 지목할 당사자가 없다
        self.assertEqual(s["structural"]["attacks_resolved"], s["structural"]["attacks"] - 3)

    def test_t_misconduct_is_charged_to_t_and_r_attack_to_r(self):
        rows = {(r["scenario_id"], r["mode"]): r for r in _rows()}
        s13 = rows[("S13", "protect")]
        self.assertEqual(s13["culprits"], ["R", "T"])
        self.assertEqual(s13["parties"]["T"]["just_liability"], 1)  # 오판은 독립 감사가 T 에게 돌린다
        self.assertEqual(s13["parties"]["R"]["just_liability"], 1)  # 재계산된 위반은 R 에게
        self.assertEqual(s13["parties"]["M"]["unjust_liability"], 0)
        for sid in ("S14", "S18"):
            self.assertEqual(rows[(sid, "protect")]["parties"]["T"]["just_liability"], 1)
        self.assertEqual(rows[("S09", "protect")]["parties"]["R"]["just_liability"], 0)  # 결손은 책임이 아니다

    def test_honest_m_is_exonerated_when_r_is_pinned(self):
        rows = {(r["scenario_id"], r["mode"]): r for r in _rows()}
        self.assertEqual(rows[("S03", "protect")]["parties"]["M"]["exonerated"], 1)
        self.assertEqual(rows[("S15", "protect")]["parties"]["M"]["exonerated"], 0)

    def test_culprits_come_from_scenario_definitions(self):
        self.assertEqual(culprits_for(scenario_by_id("S15").to_dict()), {"R", "M"})
        self.assertEqual(culprits_for(scenario_by_id("S01").to_dict()), set())
        self.assertEqual(culprits_for(scenario_by_id("S16").to_dict()), set())


class ParametricTest(unittest.TestCase):
    def test_blame_does_not_depend_on_unit_costs(self):
        run = run_scenario(scenario_by_id("S03"), "protect", seed=42)
        cheap = ledger_for_run(run, IncentiveParams(sign=0, register=0, inference=0, harm=1, liability=1))
        dear = ledger_for_run(run, IncentiveParams(sign=100, register=100, inference=1000, harm=1000, liability=500))
        for p in ("U", "R", "M", "T"):
            self.assertEqual(cheap["parties"][p]["just_liability"], dear["parties"][p]["just_liability"])
            self.assertEqual(cheap["parties"][p]["unjust_liability"], dear["parties"][p]["unjust_liability"])

    def test_parametric_axis_is_labelled_hypothesis_and_shows_the_gap(self):
        s = summarize_ledgers(_rows())
        self.assertEqual(s["parametric"]["claim_status"], "hypothesis")
        self.assertEqual(s["structural"]["claim_status"], "mock_result")
        # 정직한 U 는 피해 회피로 양수, 정직한 R·M·T 는 모형에 편익(수수료·평판)이 없어 음수다.
        # 이 음수가 '인센티브 구조의 빈 자리' 이며 숨기지 않는다.
        self.assertTrue(s["parametric"]["honest_net_positive"]["U"])
        self.assertFalse(s["parametric"]["honest_net_positive"]["R"])
        self.assertFalse(s["parametric"]["honest_net_positive"]["T"])

    def test_costs_count_real_events(self):
        row = ledger_for_run(run_scenario(scenario_by_id("S01"), "protect", seed=42))
        self.assertEqual(row["parties"]["M"]["cost_events"].get("inferred"), 1)
        self.assertEqual(row["parties"]["U"]["cost_events"].get("contract_signed"), 1)
        self.assertGreater(row["parties"]["T"]["cost_units"], 0)


if __name__ == "__main__":
    unittest.main()
