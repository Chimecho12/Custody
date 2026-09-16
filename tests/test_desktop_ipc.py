"""데스크톱 IPC 경계에 있는 세 목록이 서로 맞는지 검사한다.

명령 하나를 추가하려면 세 곳을 같이 고쳐야 한다.

    desktop/src-tauri/src/main.rs   Rust 가 통과시킬 명령 (OPS)
    itx/runtime/desktop/operations.py Agent 가 받을 명령 (ALLOWED_OPERATIONS)
    desktop/src/**/*.ts               화면이 실제로 부르는 명령

한 곳을 빠뜨리면 **브라우저 미리보기에서는 멀쩡하고 설치형 앱에서만** 깨진다.
미리보기는 previewCall 로 표본 데이터를 읽어서 Rust 를 거치지 않기 때문이다
(scripts/check-ui.cjs 도 같은 이유로 native IPC 를 검사하지 않는다고 스스로 적어 두었다).
파이썬 테스트는 Rust 를 빌드하지 않고, tsc·vite 는 Rust 를 보지 않는다.

즉 기존 검사 중 어느 것도 이 어긋남을 잡지 못한다. 그래서 소스를 직접 읽어 대조한다.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from itx.runtime.desktop import AGENT_OPERATIONS, ALLOWED_OPERATIONS, DIRECT_OPERATIONS

ROOT = Path(__file__).resolve().parents[1]
MAIN_RS = ROOT / "desktop" / "src-tauri" / "src" / "main.rs"
SRC = ROOT / "desktop" / "src"


def rust_operations() -> set[str]:
    """main.rs 의 const OPS 배열을 읽는다."""
    source = MAIN_RS.read_text(encoding="utf-8")
    start = source.index("const OPS")
    block = source[start:source.index("];", start)]
    return set(re.findall(r'"([a-z_]+)"', block))


def frontend_operations() -> set[str]:
    """화면이 call(...) 로 부르는 명령. 첫 인자가 문자열 리터럴인 것만 센다."""
    found: set[str] = set()
    for path in SRC.rglob("*.ts"):
        text = path.read_text(encoding="utf-8")
        # call('op'  ·  call<T>('op'  ·  this.call('op'  — 뒤가 ) 또는 , 인 것만
        found |= set(re.findall(r"\bcall(?:<[^>]*>)?\(\s*'([a-z_]+)'\s*[,)]", text))
        # 공통 버튼 바인더도 실제 Agent 호출이다.
        found |= set(re.findall(r"\baction\(\s*'[^']+'\s*,\s*'([a-z_]+)'", text))
    return found


class OperationAllowlists(unittest.TestCase):
    def test_rust_and_python_allowlists_are_identical(self):
        """이 검사가 없어서 standards·key_inventory·cose_export 가 Rust 에서 빠졌었다."""
        rust, python = rust_operations(), set(ALLOWED_OPERATIONS)
        self.assertEqual(rust - python, set(), "Rust 만 통과시키는 명령 — Agent 가 거부한다")
        self.assertEqual(python - rust, set(),
                         "Agent 는 받는데 Rust 가 막는 명령 — 설치형 앱에서만 실패한다")

    def test_frontend_only_calls_allowed_operations(self):
        unknown = frontend_operations() - set(ALLOWED_OPERATIONS)
        self.assertEqual(unknown, set(), "화면이 허용되지 않은 명령을 부른다")

    def test_the_two_new_screens_can_reach_the_agent(self):
        """표준 적합성·키 신뢰 기준점 화면이 쓰는 명령이 세 목록에 모두 있어야 한다."""
        needed = {"standards", "key_inventory", "cose_export"}
        self.assertTrue(needed <= set(ALLOWED_OPERATIONS))
        self.assertTrue(needed <= rust_operations())
        self.assertTrue(needed <= frontend_operations())

    def test_the_two_halves_of_the_python_allowlist_do_not_overlap(self):
        """조기 반환 명령과 Agent 명령이 겹치면 어느 쪽 경로를 타는지 읽을 수 없다."""
        self.assertEqual(DIRECT_OPERATIONS & AGENT_OPERATIONS, set())
        self.assertEqual(DIRECT_OPERATIONS | AGENT_OPERATIONS, set(ALLOWED_OPERATIONS))

    def test_every_agent_operation_is_actually_handled(self):
        """목록에만 있고 처리기가 없으면 통과시킨 뒤 조용히 None 을 돌려준다."""
        source = (ROOT / "itx" / "runtime" / "desktop" / "controller.py").read_text(encoding="utf-8")
        body = source[source.index("def _execute"):source.index("def output_path")]
        for operation in sorted(AGENT_OPERATIONS):
            with self.subTest(operation):
                self.assertIn(f'"{operation}"', body, f"{operation} 을 처리하는 분기가 없다")


if __name__ == "__main__":
    unittest.main()
