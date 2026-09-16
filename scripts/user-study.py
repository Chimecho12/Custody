"""불확실성 표현 3종 사용자 시험 도구 — 결과가 아니라 결과를 얻는 장치다.

보고서 §5 는 같은 판정을 세 방식으로 보인다: (i) 세 상태 배지, (ii) 증거 커버리지 눈금 계량기, (iii) 확립/미확립
서술 사다리. 어느 것이 오해를 덜 부르는지는 아직 사람에게 물어본 적이 없다. 이 스크립트는 그 시험을 그대로
돌린다 — 참가자에게 한 표현만 보여 주고 세 질문을 묻고, 정답 키는 Q1 매트릭스(모의 결과)에서 기계적으로 만든다.

  python scripts/user-study.py protocol
  python scripts/user-study.py run --participant P1 --display ii [--trials 12] [--seed 7] [--out study/]
  python scripts/user-study.py score study/*.json
  python scripts/user-study.py selfcheck

가장 중요한 오독은 "확인할 수 없음(insufficient_evidence)" 을 "위반 없음" 으로 읽는 것이다. score 는 이 오독을
따로 센다. 참가자 식별자 외의 개인정보는 기록하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DISPLAYS = ("i", "ii", "iii")
COOPS = ("U", "U+M", "U+R", "U+R+M")
STATUS_KO = {"passed": "통과 (위반 없음 확인)", "failed": "실패 (위반 확인)", "insufficient_evidence": "증거 부족 (확인할 수 없음)"}
QUESTIONS = [
    ("q1", "이 협조 수준에서 위반이 있었다고 확인되었는가?",
     {"A": "확인됨 (위반)", "B": "확인할 수 없음 (증거 부족)", "C": "위반 없음이 확인됨"}),
    ("q2", "이 응답은 사용자의 업무에 쓰였는가? (protect 정책)",
     {"A": "예, 수용됨", "B": "아니오, 차단됨"}),
    ("q3", "무엇이 더 있으면 감춰진 위반이 확립되는가?",
     {"A": "R 중계 진술", "B": "M 추론 영수증", "C": "둘 다", "D": "더 필요한 증거 없음"}),
]


# ---------- 정답 키 (Q1 매트릭스에서 기계적으로) ----------
def answer_key(row: dict, full: dict) -> dict[str, str]:
    status = row["verification_status"]
    q1 = "A" if status == "failed" else "B" if status == "insufficient_evidence" else "C"
    q2 = "A" if row["gate_action"] in ("accept", "accept_unverified") else "B"
    missing_codes = [c for c in full["codes"] if c not in row["codes"]]
    coop = set(row["cooperation"].split("+"))
    needed = [p for p in ("R", "M") if p not in coop]
    q3 = "D" if not missing_codes or not needed else ("A" if needed == ["R"] else "B" if needed == ["M"] else "C")
    return {"q1": q1, "q2": q2, "q3": q3}


# ---------- 표현 3종 (report.js §1d 와 같은 정보량) ----------
def render(display: str, row: dict, full: dict) -> str:
    coop = set(row["cooperation"].split("+"))
    title = f"사건 {row['scenario_id']} — {row['title']}\n협조 집합: {row['cooperation']}"
    if display == "i":
        return f"{title}\n\n  [{row['verification_status']}]  [completeness: {row['completeness']}]  [gate: {row['gate_action']}]"
    if display == "ii":
        meter = "  ".join(f"{p} {'■' if p in coop else '□'}" for p in ("U", "R", "M"))
        missing = [p for p in ("U", "R", "M") if p not in coop]
        return (f"{title}\n\n  증거 커버리지: {meter}" + (f"   ({', '.join(missing)} 결손)" if missing else "")
                + f"\n  상태: {row['verification_status']}")
    established = row["codes"]
    hidden = [c for c in full["codes"] if c not in row["codes"]]
    needed = [p for p in ("R", "M") if p not in coop]
    lines = [f"{title}\n", "  [확립]   U 가 서명한 요청 계약과 수신 진술의 자기 결합 (항상 확인 가능)."]
    if established:
        lines.append(f"  [확립]   이 협조 수준에서 이미 드러난 위반: {', '.join(established)}.")
    if hidden:
        lines.append(f"  [미확립] 이 협조 수준에서는 감춰짐: {', '.join(hidden)}. 필요한 증거: "
                     + (", ".join("R 중계 진술" if p == "R" else "M 추론 영수증" for p in needed) or "없음") + ".")
    lines.append(f"  [조치]   protect 정책상 게이트 결정: {row['gate_action']}.")
    return "\n".join(lines)


# ---------- 입력 ----------
def load_rows(summary_path: Path | None) -> list[dict]:
    if summary_path and summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))["q1_matrix"]
    from itx.sim import run_q1_matrix
    return run_q1_matrix()


def trials_for(rows: list[dict], seed: int, count: int | None) -> list[tuple[dict, dict]]:
    full = {r["scenario_id"]: r for r in rows if r["cooperation"] == "U+R+M"}
    pairs = [(r, full[r["scenario_id"]]) for r in rows]
    random.Random(seed).shuffle(pairs)
    return pairs[:count] if count else pairs


# ---------- 명령 ----------
def cmd_protocol(_: argparse.Namespace) -> int:
    print((ROOT / "docs" / "user-study-protocol.md").read_text(encoding="utf-8"))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    rows = load_rows(Path(args.summary) if args.summary else ROOT / "artifacts" / "summary.json")
    scripted = json.loads(Path(args.answers).read_text(encoding="utf-8")) if args.answers else None
    trials = trials_for(rows, args.seed, args.trials)
    record = {"profile": "itx-user-study/1", "participant": args.participant, "display": args.display,
              "seed": args.seed, "started_at": int(time.time()), "trials": []}
    for n, (row, full) in enumerate(trials, 1):
        key = answer_key(row, full)
        print(f"\n===== 시행 {n}/{len(trials)} · 표현 ({args.display}) =====")
        print(render(args.display, row, full))
        answers, started = {}, time.monotonic()
        for qid, text, options in QUESTIONS:
            prompt = f"\n{text}\n" + "\n".join(f"  {k}. {v}" for k, v in options.items()) + "\n> "
            if scripted is not None:
                answer = str(scripted[n - 1][qid]).upper()
                print(prompt + answer)
            else:
                answer = ""
                while answer not in options:
                    answer = input(prompt).strip().upper()
            answers[qid] = answer
        record["trials"].append({"scenario_id": row["scenario_id"], "cooperation": row["cooperation"],
                                 "answers": answers, "key": key,
                                 "correct": {q: answers[q] == key[q] for q in key},
                                 "seconds": round(time.monotonic() - started, 1)})
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{args.participant}-{args.display}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {path}")
    return 0


def score(records: list[dict]) -> dict:
    """표현별 정답률과 핵심 오독(증거 부족 → 위반 없음 / 위반 확인) 비율."""
    out: dict[str, dict] = {}
    for rec in records:
        d = out.setdefault(rec["display"], {"participants": set(), "trials": 0, "correct": {"q1": 0, "q2": 0, "q3": 0},
                                            "insufficient_trials": 0, "insufficient_read_as_no_violation": 0,
                                            "insufficient_read_as_violation": 0, "seconds": 0.0})
        d["participants"].add(rec["participant"])
        for t in rec["trials"]:
            d["trials"] += 1
            d["seconds"] += t["seconds"]
            for q in ("q1", "q2", "q3"):
                d["correct"][q] += int(t["correct"][q])
            if t["key"]["q1"] == "B":
                d["insufficient_trials"] += 1
                d["insufficient_read_as_no_violation"] += int(t["answers"]["q1"] == "C")
                d["insufficient_read_as_violation"] += int(t["answers"]["q1"] == "A")
    for d in out.values():
        n = d["trials"] or 1
        d["participants"] = sorted(d["participants"])
        d["accuracy"] = {q: round(d["correct"][q] / n, 3) for q in ("q1", "q2", "q3")}
        d["mean_seconds"] = round(d["seconds"] / n, 1)
        k = d["insufficient_trials"] or 1
        d["critical_misread_rate"] = round(d["insufficient_read_as_no_violation"] / k, 3)
    return out


def cmd_score(args: argparse.Namespace) -> int:
    records = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.files]
    result = score(records)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    n = sum(len(v["participants"]) for v in result.values())
    if n < 5:
        print(f"\n주의: 참가자 {n}명. 결론을 내기에는 5명 이상이 필요하다 (docs/user-study-protocol.md).")
    return 0


def cmd_selfcheck(args: argparse.Namespace) -> int:
    rows = load_rows(Path(args.summary) if args.summary else ROOT / "artifacts" / "summary.json")
    trials = trials_for(rows, 1, None)
    options = {qid: opts for qid, _text, opts in QUESTIONS}
    for row, full in trials:
        key = answer_key(row, full)
        assert set(key) == set(options) and all(key[q] in options[q] for q in key), (row["scenario_id"], key)
        for display in DISPLAYS:
            assert render(display, row, full)
    print(f"selfcheck ok: {len(trials)} trials × {len(DISPLAYS)} displays")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("protocol").set_defaults(fn=cmd_protocol)
    r = sub.add_parser("run")
    r.add_argument("--participant", required=True)
    r.add_argument("--display", required=True, choices=DISPLAYS)
    r.add_argument("--trials", type=int, default=None)
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--summary", default=None)
    r.add_argument("--answers", default=None, help="대화식 대신 답을 JSON 목록에서 읽는다 (검사·재현용)")
    r.add_argument("--out", default=str(ROOT / "artifacts" / "user-study"))
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("score")
    s.add_argument("files", nargs="+")
    s.set_defaults(fn=cmd_score)
    c = sub.add_parser("selfcheck")
    c.add_argument("--summary", default=None)
    c.set_defaults(fn=cmd_selfcheck)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
