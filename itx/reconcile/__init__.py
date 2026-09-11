"""대조 엔진: 진술 집합을 받아 등식을 평가하고 판정 페이로드를 만든다.

이 패키지는 등록(ts/)을 호출하지 않는다. 등록과 판정은 분리한다.
같은 입력에 대해 항상 같은 출력을 내므로 독립 감사자가 재실행할 수 있다.
"""
from .evidence import EvidenceSet, PrivateEvidence, StatementRef
from .equations import evaluate_equations, EqResult, EQUATION_DOCS
from .discrepancy import classify, Discrepancy
from .completeness import assess_completeness
from .engine import ReconciliationEngine, THREAT_MODEL_TM1

__all__ = [
    "EvidenceSet", "PrivateEvidence", "StatementRef",
    "evaluate_equations", "EqResult", "EQUATION_DOCS",
    "classify", "Discrepancy", "assess_completeness",
    "ReconciliationEngine", "THREAT_MODEL_TM1",
]
