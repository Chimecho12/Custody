"""실제 통신 런타임 CLI — `python runtime.py <명령>` 이 그대로 이 모듈을 부른다.

데스크톱 앱은 이 파일을 PyInstaller 로 묶은 `itx-agent.exe` 를 사이드카로 띄우고
`desktop` 명령의 stdio 프로토콜로 말한다. 나머지 명령은 운영자가 직접 쓰는 것으로,
키 생성·배포 합의·감사 패키지처럼 화면 없이도 끝나야 하는 절차다.

명령 정의는 아래 SPEC 표 하나에 모아 두었다. 새 명령을 넣을 때 파서 조립 코드를
고칠 일이 없도록 (인자 이름과 기본값이 곧 문서가 되도록) 선언형으로 적는다.
"""
from __future__ import annotations

import argparse
import json

_REQ = {"required": True}

#: (명령, 도움말, [(플래그, argparse 옵션), ...])
SPEC: list[tuple[str, str, list[tuple[str, dict]]]] = [
    ("desktop", "데스크톱 사이드카: stdin/stdout 으로 앱과 주고받는다", [
        ("--data-dir", _REQ)]),
    ("service", "R·M·T 중 한 역할을 TLS 서버로 띄운다", [
        ("--config", _REQ),
        ("--parent-pipe", {"action": "store_true"})]),
    ("init", "한 PC 안에 실험용 배포 일습을 만든다", [
        ("--directory", _REQ),
        ("--connected", {"action": "store_true"})]),

    # --- 운영자 등록과 배포 합의 -------------------------------------------------
    ("operator-init", "로컬에서 키를 만들고 서명된 공개 카드를 내보낸다", [
        ("--directory", _REQ),
        ("--role", {"required": True, "choices": list("URMTW")}),
        ("--endpoint", {})]),
    ("deployment-propose", "공개 카드들을 모아 배포안을 만든다", [
        ("--cards", {"nargs": "+", "required": True}),
        ("--previous", {}),
        ("--checkpoint", {}),
        ("--model-id", {"default": "itx-reference-v1"}),
        ("--model-hash", {}),
        ("--model-kind", {"choices": ["deterministic_mock", "ollama"], "default": "deterministic_mock"}),
        ("--model-name", {}),
        ("--pre-exec", {"action": "store_true"}),
        ("--output", _REQ)]),
    ("deployment-endorse", "운영자 한 명이 배포안에 서명한다", [
        ("--operator", _REQ),
        ("--proposal", _REQ),
        ("--fingerprint", _REQ),
        ("--previous-config", {}),
        ("--output", _REQ)]),
    ("deployment-assemble", "서명들을 모아 배포 묶음을 만든다", [
        ("--proposal", _REQ),
        ("--endorsements", {"nargs": "+", "required": True}),
        ("--previous", {}),
        ("--output", _REQ)]),
    ("deployment-activate", "배포 묶음을 이 운영자의 설정으로 적용한다", [
        ("--operator", _REQ),
        ("--bundle", _REQ),
        ("--fingerprint", _REQ),
        ("--bind", {"default": "127.0.0.1"}),
        ("--model-endpoint", {}),
        ("--previous-config", {})]),

    # --- 외부 감사 ---------------------------------------------------------------
    ("audit-recipient", "감사자 쪽에서 수신용 암호화 키를 만든다", [
        ("--directory", _REQ)]),
    ("audit-trust", "현재 설정에서 신뢰 기준(trust.json)을 뽑는다", [
        ("--config", _REQ),
        ("--output", _REQ)]),
    ("audit-export", "증거 패키지를 내보낸다 (--recipient 를 주면 암호화)", [
        ("--config", _REQ),
        ("--output", _REQ),
        ("--recipient", {}),
        ("--recipient-fingerprint", {})]),
    ("audit-verify", "받은 패키지를 T 에 연결하지 않고 검증한다", [
        ("--package", _REQ),
        ("--trust", _REQ),
        ("--fingerprint", _REQ),
        ("--recipient-directory", {}),
        ("--output", {})]),

    # --- 점검·요청·측정 ----------------------------------------------------------
    ("preflight", "역할별 TLS·서명 신원을 점검한다", [
        ("--config", _REQ),
        ("--output", {})]),
    ("witness", "목격자 W 에게 체크포인트 확인을 요청한다", [
        ("--config", _REQ),
        ("--output", {})]),
    ("request", "한 건을 실제로 요청하고 게이트 결정을 받는다", [
        ("--config", _REQ),
        ("--prompt", _REQ),
        ("--mode", {"choices": ["protect", "strict", "observe"], "default": "protect"})]),
    ("benchmark", "세 모드를 반복 실행해 지연을 실측한다", [
        ("--output", _REQ),
        ("--repeats", {"type": int, "default": 5})]),

    # --- 표준 적합성과 키 보관 ------------------------------------------------
    ("conformance", "CBOR·COSE·Merkle 적합성 벡터를 실행한다 (설정 불필요)", [
        ("--output", {}),
        ("--group", {"nargs": "+", "help": "일부 묶음만: cose cbor scitt merkle tee gossip"}),
        ("--no-external", {"action": "store_true",
                           "help": "제3자 구현(cbor2·pycose) 교차 검증을 건너뛴다"})]),
    ("key-inventory", "서명 키의 보관처·평문 노출·회전 기한을 낸다", [
        ("--config", _REQ),
        ("--output", {})]),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text, arguments in SPEC:
        command = sub.add_parser(name, help=help_text)
        for flag, options in arguments:
            command.add_argument(flag, **options)
    return parser


def main(argv: list[str] | None = None) -> int:
    from . import use_utf8

    use_utf8()
    args = build_parser().parse_args(argv)
    # 오래 사는 세 명령은 자기 루프를 돌고, 나머지는 결과 JSON 을 한 번 내고 끝난다.
    if args.command == "desktop":
        from itx.runtime.desktop import stdio
        stdio(args.data_dir)
        return 0
    if args.command == "service":
        from itx.runtime.service import serve
        serve(args.config, args.parent_pipe)
        return 0
    if args.command == "init":
        from itx.runtime.lab import create_deployment
        print(create_deployment(args.directory, lab=not args.connected))
        return 0

    from itx.runtime.commands import execute

    result = execute(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if isinstance(result, dict) and result.get("ok") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
