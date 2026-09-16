"""시뮬레이션 CLI — `python run.py <명령>` 이 그대로 이 모듈을 부른다.

  doctor            환경 점검 (Python 버전, 서명 백엔드)
  test              단위 테스트
  run [--out DIR]   시나리오 17종 × 모드 3종 실행 + Q1 매트릭스 → artifacts/
  report [--out DIR] artifacts/results.json → artifacts/report.html
  audit [--out DIR] artifacts/log-export-S01.json 을 독립 재실행해 판정·앵커·보관 영수증 포함 검증
  all               run + report + audit
"""
from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def cmd_doctor(_: argparse.Namespace) -> int:
    from itx import __version__
    from itx.crypto import BACKEND, HAS_CRYPTOGRAPHY

    print(f"itx {__version__}")
    print(f"python {sys.version.split()[0]}")
    print(f"signature backend: {BACKEND} (cryptography installed: {HAS_CRYPTOGRAPHY})")
    if sys.version_info < (3, 10):  # noqa: UP036 — 사용자가 실제로 구형 Python 으로 부를 수 있어 남겨 둔다
        print("Python 3.10 이상이 필요합니다.")
        return 1
    print("READY: 표준 라이브러리만으로 실행 가능")
    return 0


def cmd_test(_: argparse.Namespace) -> int:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


def cmd_run(args: argparse.Namespace) -> int:
    from itx.sim import run_all

    out = Path(args.out)
    bundle = run_all(out, seed=args.seed)
    print(f"scenarios: {len(bundle['scenarios'])}, runs: {len(bundle['results'])}, q1 rows: {len(bundle['q1_matrix'])}")
    for mode, m in bundle["summary"].items():
        print(f"  [{mode:7s}] detection {m['detection']['num']}/{m['detection']['den']}  "
              f"defense-before-use {m['defense_before_use']['num']}/{m['defense_before_use']['den']}  "
              f"false-block {m['false_block']['num']}/{m['false_block']['den']}  "
              f"availability {m['availability_legit']['num']}/{m['availability_legit']['den']} "
              f"(under pressure {m['availability_under_pressure']['num']}/{m['availability_under_pressure']['den']})  "
              f"wait mean {m['decision_wait_ms']['mean']} ms")
    print(f"written: {out / 'results.json'}, {out / 'summary.json'}, {out / 'log-export-S01.json'}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from itx.report import build_report

    out = Path(args.out)
    src = out / "results.json"
    if not src.exists():
        print(f"{src} 가 없습니다. 먼저 `python run.py run` 을 실행하세요.")
        return 1
    bundle = json.loads(src.read_text(encoding="utf-8"))
    html_path = out / "report.html"
    html_path.write_text(build_report(bundle), encoding="utf-8")
    artifact_path = out / "report-artifact.html"
    artifact_path.write_text(build_report(bundle, artifact=True), encoding="utf-8")
    print(f"written: {html_path} (독립 실행), {artifact_path} (아티팩트 게시용)")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """T 의 내보내기 파일만으로 판정을 재실행한다 (S01 예시). 앵커 파일이 있으면 함께 검증."""
    from itx.audit import replay_audit
    from itx.sim.model import reference_hashes

    out = Path(args.out)
    export_path = out / "log-export-S01.json"
    if not export_path.exists():
        print(f"{export_path} 가 없습니다. 먼저 `python run.py run` 을 실행하세요.")
        return 1
    export = json.loads(export_path.read_text(encoding="utf-8"))
    anchors_path = out / "anchors-S01.json"
    anchors = json.loads(anchors_path.read_text(encoding="utf-8")) if anchors_path.exists() else []
    # 앵커 파일은 verify 결과 형식이므로 원 기록 형식으로 바꾼다.
    anchor_records = [{"tree_size": a["tree_size"], "root_hash": a["anchored_root"], "anchored_at": a["anchored_at"]} for a in anchors]
    # 제출자(U)가 보관한 등록 영수증. 있으면 "약속된 항목이 지금도 로그에 있는가" 를 함께 검사한다.
    receipts_path = out / "receipts-S01.json"
    held = json.loads(receipts_path.read_text(encoding="utf-8")) if receipts_path.exists() else []
    # 비공개 증거가 없는 공개 감사자 관점: E1 은 평가 불가로 남으므로 비교에서 제외하고 나머지를 재계산한다.
    report = replay_audit(export, anchor_records, private_by_sub={}, expected_parties_by_sub={},
                          reference_model_hashes=reference_hashes(), held_receipts=held)
    print(f"log {export['log_id']}: entries={len(export['entries'])} tree_size={export['head']['tree_size']}")
    print(f"  트리 재계산 == 헤드: {report['tree_recomputed_matches_head']}")
    print(f"  헤드 서명 유효: {report['head_signature_valid']}")
    print(f"  앵커 {len(report['anchors'])}건 중 일치 {sum(a['ok'] for a in report['anchors'])}건")
    hr = report["held_receipts"]
    print(f"  보관 영수증 {hr['held']}건: 포함 {hr['included']}건 · 누락 {len(hr['missing'])}건 · 검증 불가 {len(hr['unverifiable'])}건"
          + ("" if hr["held"] else " (영수증이 없으면 누락은 검사할 수 없다)"))
    for m in hr["missing"]:
        print(f"    - #{m['leaf_index']} {m['sub']} {m['content_type']}: {m['reason']}")
    print(f"  요청 {report['subs_checked']}건 재실행, T 판정과 불일치 {len(report['verdict_mismatches'])}건 "
          f"(비교 제외 등식: {', '.join(report['compared_without']) or '없음'})")
    for m in report["verdict_mismatches"]:
        print(f"    - {m['sub']}: T={m['t_verdict']['verification_status'] if m['t_verdict'] else '없음'} "
              f"재계산={m['recomputed']['verification_status']} codes={m['recomputed']['codes']}")
    bad = report["unauthenticated_verdicts"]
    print(f"  인증되지 않는 판정 진술 {len(bad)}건")
    for b in bad:
        print(f"    - #{b['log_index']} {b['sub']}: {b['problem']}")
    print(f"  종합: {'일치' if report['ok'] else '불일치 발견'}")
    print("주의: 공개 감사자는 사용자 비공개 증거(솔트)가 없어 E1·E4 를 재계산할 수 없다. "
          "권한 감사자는 증거 묶음을 받아 그 등식까지 완전히 재현한다 (시나리오 실행 중의 감사가 그 경우다).")
    return 0 if report["ok"] else 2


def cmd_all(args: argparse.Namespace) -> int:
    rc = cmd_run(args)
    if rc:
        return rc
    rc = cmd_report(args)
    if rc:
        return rc
    return cmd_audit(args)


def main(argv: list[str] | None = None) -> int:
    from . import use_utf8

    use_utf8()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("doctor", cmd_doctor), ("test", cmd_test), ("run", cmd_run), ("report", cmd_report),
                     ("audit", cmd_audit), ("all", cmd_all)):
        sp = sub.add_parser(name)
        sp.add_argument("--out", default=str(ROOT / "artifacts"))
        sp.add_argument("--seed", type=int, default=42)
        sp.set_defaults(fn=fn)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
