"""3당사자 시뮬레이터: 사용자(U) · 적대적 중개자(R) · 모델 운영자(M) · 제3자(T).

모든 시각은 시뮬레이션 밀리초다. 모형 모델은 결정적이므로 같은 시드에서 같은 결과가 난다.
여기서 나온 수치는 `mock_result` 이며 실제 네트워크·모델 성능이 아니다.
"""
from .context import SimContext, Timeline
from .model import MockModel, DEFAULT_MODELS, reference_hashes
from .parties import User, Relay, RelayBehavior, ModelOperator, ThirdParty, EvidenceQueue
from .scenarios import Scenario, SCENARIOS, scenario_by_id, Q1_SCENARIO_IDS, COOPERATION_SETS
from .runner import run_scenario, run_all, run_q1_matrix

__all__ = [
    "SimContext", "Timeline", "MockModel", "DEFAULT_MODELS", "reference_hashes",
    "User", "Relay", "RelayBehavior", "ModelOperator", "ThirdParty", "EvidenceQueue",
    "Scenario", "SCENARIOS", "scenario_by_id", "Q1_SCENARIO_IDS", "COOPERATION_SETS",
    "run_scenario", "run_all", "run_q1_matrix",
]
