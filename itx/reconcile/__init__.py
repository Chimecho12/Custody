"""대조 엔진: 진술 집합을 받아 등식을 평가하고 판정 페이로드를 만든다.

이 패키지는 등록(ts/)을 호출하지 않는다. 등록과 판정은 분리한다.
같은 입력에 대해 항상 같은 출력을 내므로 독립 감사자가 재실행할 수 있다.
"""
from .completeness import assess_completeness
from .discrepancy import Discrepancy, classify
from .engine import THREAT_MODEL_TM1, ReconciliationEngine
from .equations import EQUATION_DOCS, EqResult, evaluate_equations
from .evidence import EvidenceSet, PrivateEvidence, StatementRef

__all__ = [
    "EQUATION_DOCS",
    "THREAT_MODEL_TM1",
    "Discrepancy",
    "EqResult",
    "EvidenceSet",
    "PrivateEvidence",
    "ReconciliationEngine",
    "StatementRef",
    "assess_completeness",
    "classify",
    "evaluate_equations",
]
