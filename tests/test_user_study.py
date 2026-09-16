"""사용자 시험 도구: 정답 키는 매트릭스에서 기계적으로 나오고, 채점은 핵심 오독을 따로 센다.

결과 파일은 없다 — 여기서 검사하는 것은 도구가 절차대로 동작하는가뿐이다.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("user_study", ROOT / "scripts" / "user-study.py")
study = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(study)

ROWS = [
    {"scenario_id": "S03", "title": "응답 변조", "cooperation": "U", "verification_status": "insufficient_evidence",
     "completeness": "gap", "codes": [], "gate_action": "quarantine"},
    {"scenario_id": "S03", "title": "응답 변조", "cooperation": "U+R", "verification_status": "insufficient_evidence",
     "completeness": "gap", "codes": [], "gate_action": "quarantine"},
    {"scenario_id": "S03", "title": "응답 변조", "cooperation": "U+M", "verification_status": "failed",
     "completeness": "gap", "codes": ["D-RESP-UNAPPROVED"], "gate_action": "quarantine"},
    {"scenario_id": "S03", "title": "응답 변조", "cooperation": "U+R+M", "verification_status": "failed",
     "completeness": "complete", "codes": ["D-RESP-UNAPPROVED"], "gate_action": "quarantine"},
]
FULL = ROWS[3]


class AnswerKeyTest(unittest.TestCase):
    def test_insufficient_is_not_no_violation(self):
        self.assertEqual(study.answer_key(ROWS[0], FULL)["q1"], "B")
        self.assertEqual(study.answer_key(ROWS[3], FULL)["q1"], "A")

    def test_needed_evidence_follows_the_missing_party(self):
        self.assertEqual(study.answer_key(ROWS[0], FULL)["q3"], "C")   # R·M 둘 다 없음
        self.assertEqual(study.answer_key(ROWS[1], FULL)["q3"], "B")   # M 영수증이 있어야 E10 이 선다
        self.assertEqual(study.answer_key(ROWS[2], FULL)["q3"], "D")   # 이미 위반이 드러남
        self.assertEqual(study.answer_key(ROWS[3], FULL)["q3"], "D")

    def test_every_display_renders_every_row(self):
        for row in ROWS:
            for display in study.DISPLAYS:
                text = study.render(display, row, FULL)
                self.assertIn(row["scenario_id"], text)
        self.assertIn("감춰짐", study.render("iii", ROWS[1], FULL))
        self.assertNotIn("감춰짐", study.render("i", ROWS[1], FULL))


class ScoringTest(unittest.TestCase):
    def test_run_with_scripted_answers_and_score(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.json"
            summary.write_text(json.dumps({"q1_matrix": ROWS}), encoding="utf-8")
            trials = study.trials_for(ROWS, seed=3, count=None)
            answers = []
            for row, full in trials:
                key = study.answer_key(row, full)
                # 증거 부족을 '위반 없음' 으로 읽는 핵심 오독을 일부러 한 번 넣는다.
                answers.append({"q1": "C" if key["q1"] == "B" and row["cooperation"] == "U" else key["q1"],
                                "q2": key["q2"], "q3": key["q3"]})
            answers_path = Path(directory) / "answers.json"
            answers_path.write_text(json.dumps(answers), encoding="utf-8")
            rc = study.main(["run", "--participant", "P1", "--display", "i", "--seed", "3", "--summary", str(summary),
                             "--answers", str(answers_path), "--out", directory])
            self.assertEqual(rc, 0)
            record = json.loads((Path(directory) / "P1-i.json").read_text(encoding="utf-8"))
            self.assertEqual(len(record["trials"]), 4)
            result = study.score([record])["i"]
            self.assertEqual(result["insufficient_trials"], 2)
            self.assertEqual(result["insufficient_read_as_no_violation"], 1)
            self.assertEqual(result["critical_misread_rate"], 0.5)
            self.assertEqual(result["accuracy"]["q2"], 1.0)
            self.assertEqual(result["accuracy"]["q3"], 1.0)


if __name__ == "__main__":
    unittest.main()
