"""3당사자 시뮬레이터: 사용자(U) · 적대적 중개자(R) · 모델 운영자(M) · 제3자(T).

모든 시각은 시뮬레이션 밀리초다. 모형 모델은 결정적이므로 같은 시드에서 같은 결과가 난다.
여기서 나온 수치는 `mock_result` 이며 실제 네트워크·모델 성능이 아니다.
"""
from .context import SimContext, Timeline
from .model import DEFAULT_MODELS, MockModel, reference_hashes
from .parties import EvidenceQueue, ModelOperator, Relay, RelayBehavior, ThirdParty, User
from .incentives import IncentiveParams, ledger_for_run, summarize_ledgers
from .runner import run_all, run_q1_matrix, run_scenario, run_t_contribution, summarize_t_contribution
from .scenarios import COOPERATION_SETS, Q1_SCENARIO_IDS, SCENARIOS, Scenario, scenario_by_id

__all__ = [
    "COOPERATION_SETS",
    "DEFAULT_MODELS",
    "Q1_SCENARIO_IDS",
    "SCENARIOS",
    "EvidenceQueue",
    "MockModel",
    "ModelOperator",
    "Relay",
    "RelayBehavior",
    "Scenario",
    "SimContext",
    "ThirdParty",
    "Timeline",
    "User",
    "reference_hashes",
    "run_all",
    "IncentiveParams",
    "ledger_for_run",
    "run_q1_matrix",
    "summarize_ledgers",
    "run_t_contribution",
    "summarize_t_contribution",
    "run_scenario",
    "scenario_by_id",
]
