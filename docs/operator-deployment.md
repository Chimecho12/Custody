# itx v0.3 — 운영자 배포·키 교체·외부 감사·SDK

작성: 2026-09-14. [설치·구현 범위와 검증 결과](desktop-runtime-v0.3.md).
아래는 역할별 키를 각자 생성하는 절차다. 현재 검증은 한 Windows 계정의 별도 프로세스에서 수행했다. 별도 호스트 실증과 실제 운영자의 신원 확인은 남아 있다.

## 역할별 키와 공동 합의

설치 폴더의 `itx-agent.exe`는 데스크톱 IPC와 서버/관리 CLI를 함께 포함한다. 소스에서는 `python runtime.py`로 같은 명령을 실행한다.
각 역할은 자기 Windows 계정에서 새 빈 폴더에 키를 생성한다. 아래 주소와 경로는 운영 환경에 맞게 교체한다.

```powershell
$agent = 'C:\itx\itx-agent.exe'
# U의 PC
& $agent operator-init --directory C:\itx-data\operator-U --role U
# 각각 해당 역할의 PC에서 실행
& $agent operator-init --directory C:\itx-data\operator-R --role R --endpoint https://r.example.org:8743
& $agent operator-init --directory C:\itx-data\operator-M --role M --endpoint https://m.example.org:8742
& $agent operator-init --directory C:\itx-data\operator-T --role T --endpoint https://t.example.org:8741
& $agent operator-init --directory C:\itx-data\operator-W --role W --endpoint https://w.example.org:8744
```

공유 대상은 출력된 `operator.json` 공개 카드뿐이다. 개인키·DPAPI 파일·TLS 개인키를 교환하지 않는다.
역할별 담당자, 주소, 공개 카드 지문을 기존 조직 연락 채널에서 확인한다. 한 PC에서 다섯 키를 만든 사실만으로 독립 운영자가 존재한다고 판단하지 않는다.
W를 제외한 URMT 배포도 가능하다. 각 서비스 주소는 인증서 SAN과 일치해야 하고 역할별 CA는 분리된다.
키와 TLS 인증서의 기본 유효기간은 90일이다. DNS·방화벽·클라우드 설정을 앱이 대신 변경하지 않는다.

취합자는 확인된 공개 카드로 제안을 만든다. 예시에서는 받은 카드 파일을 U.json 등으로 이름 붙였다.

```powershell
& $agent deployment-propose --cards U.json R.json M.json T.json W.json --output proposal.json
```

기본 모델은 모형이다. `--pre-exec`를 추가하면 M이 실제 입력 커밋을 U의 서명 계약과 실행 전에 비교한다.
각 운영자가 제안의 신원·키·주소·모델 기준·유효기간·지문을 검토하고 같은 제안에 서명한다.
아래 변수에는 별도 채널로 확인한 실제 64자리 지문을 넣는다. 모든 출력 파일은 새 경로여야 한다.

```powershell
$reviewedFingerprint = '확인한_제안의_SHA256_지문'
# U의 PC. R/M/T/W도 자기 로컬 operator 폴더에서 승인한다.
& $agent deployment-endorse --operator C:\itx-data\operator-U --proposal proposal.json --fingerprint $reviewedFingerprint --output approve-U.json
# 공개 승인 파일들을 모은 취합자
& $agent deployment-assemble --proposal proposal.json --endorsements approve-U.json approve-R.json approve-M.json approve-T.json approve-W.json --output bundle.json
```

한 명이 다른 역할을 대신 승인할 수 없다. 완성된 합의서를 교환한 뒤 각자 활성화한다.

```powershell
# U의 PC: listening endpoint가 없다.
& $agent deployment-activate --operator C:\itx-data\operator-U --bundle bundle.json --fingerprint $reviewedFingerprint
# T의 PC 예시. R/M/W도 각자의 로컬 폴더에서 실행한다.
& $agent deployment-activate --operator C:\itx-data\operator-T --bundle bundle.json --fingerprint $reviewedFingerprint --bind 0.0.0.0
$roleConfig = '활성화_결과의_config.json_절대경로'
& $agent service --config $roleConfig
```

서비스 CLI는 포그라운드로 실행된다. 지속 운영의 프로세스 재시작·백업·포트 접근 정책은 각 운영자가 관리한다.
Windows 서비스에 자동 등록하거나 다른 호스트에 자동 설치하는 기능은 없다.
U 앱의 `연결 설정`에는 U의 config.json을 적용한다. CLI/SDK 시험 전에는 같은 설정을 사용하는 앱을 닫는다.

```powershell
$uConfig = 'U_활성화_결과의_config.json_절대경로'
& $agent preflight --config $uConfig --output readiness.json
& $agent request --config $uConfig --prompt '연결 확인' --mode strict
```

preflight는 TLS, 고정 공개키의 서명 응답, 배포 ID, 요청 허용 상태를 검사한다. `model_execution_verified=false`는 실제 모델 실행 증명을 제공하지 않는다는 뜻이다.
합의한 공개 설정을 수동 편집하면 서명 합의서 대조에서 거부한다. 변경은 새 세대의 공동 합의로 수행한다.

## 실제 모델 연결 준비

현재 실제 LLM 서버가 없어 아래 절차는 준비된 연결 방법이며 실증 결과가 아니다.
M이 자기 환경에 Ollama를 준비한 뒤 제안에 별도 모델 ID·해시·정확한 모델명을 넣는다.

```powershell
$modelName = '실제_모델명:태그'
$modelHash = '합의한_모델_아티팩트의_64자리_SHA256'
& $agent deployment-propose --cards U.json R.json M.json T.json W.json --model-kind ollama --model-id team-model-v1 --model-name $modelName --model-hash $modelHash --output proposal.json
# 전원 승인과 취합을 마친 후 M에서 활성화
& $agent deployment-activate --operator C:\itx-data\operator-M --bundle bundle.json --fingerprint $reviewedFingerprint --model-endpoint http://127.0.0.1:11434
```

기본 모형 ID/해시를 실제 모델 기준으로 사용할 수 없다. 모델명은 서버 응답의 `model`과 정확히 일치하는 태그 포함 이름으로 지정한다.
어댑터는 `/api/generate`, `stream=false`, 완성된 텍스트만 처리한다. 중복 키·미완료·잘못된 모델명·크기 초과·리다이렉트를 거부한다.
M→모델 주소는 HTTPS 또는 명시적 루프백 HTTP만 허용하며 프롬프트에서 주소를 받지 않는다.
M 서명은 Connector의 선언에 대한 증거이며 선언한 바이너리가 실행됐다는 TEE 증명은 아니다. [Ollama 비스트리밍 응답](https://docs.ollama.com/api/streaming)

## 목격자와 오프라인 감사

W가 포함된 배포에서 U는 앱의 `감사 자료 → W 목격` 또는 아래 명령을 사용한다.

```powershell
& $agent witness --config $uConfig --output witness.json
& $agent audit-trust --config $uConfig --output trust.json
& $agent audit-export --config $uConfig --output public-audit.json
```

W는 서명 체크포인트만 받고 이전 관측과 모순되면 거부한다. `anchor_digest`는 외부 앵커에 사용할 값이며 실제 체인 게시/수수료 지불/포함 검증은 하지 않는다.
감사자에게 신뢰 파일과 지문을 패키지와 별도의 신뢰 경로로 전달한다. 둘을 같은 공격자가 바꿀 수 있는 위치에서 받기만 해서는 최초 신뢰가 성립하지 않는다.

비공개 입력까지 검사하려면 감사자가 자기 계정에서 복호화 키를 만든다.

```powershell
# 감사자의 PC: 출력된 공개 recipient.json과 지문만 U에 전달한다.
& $agent audit-recipient --directory C:\itx-audit\identity
# U의 PC
$recipientFingerprint = '별도_확인한_감사자_공개키_지문'
& $agent audit-export --config $uConfig --recipient recipient.json --recipient-fingerprint $recipientFingerprint --output encrypted-audit.json
# 감사자의 PC: 서버를 모두 중지해도 아래 검증은 가능하다.
$trustFingerprint = '별도_확인한_신뢰파일_지문'
& $agent audit-verify --package encrypted-audit.json --trust trust.json --fingerprint $trustFingerprint --recipient-directory C:\itx-audit\identity --output audit-report.json
```

공개 감사는 `--recipient-directory` 없이 실행한다. `private_scope=partial`은 비공개 입력이 필요한 검사를 완전히 재현하지 못했다는 뜻이다.
`ok`, `verdict_count`, `compared_without`, `receipt_errors`, `deployment_epochs_verified`, `witness_receipts_checked`를 함께 확인한다.
감사 불일치의 CLI 종료 코드는 2다. 정상적인 공개 부분 감사를 전체 검증으로 표시하지 않는다.
암호화는 cryptography의 X25519/HKDF/AES-GCM을 사용한다. [X25519](https://cryptography.io/en/stable/hazmat/primitives/asymmetric/x25519/), [HKDF](https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/)
원문·개인 서명 키는 패키지에 넣지 않는다. 비공개 검증 입력은 salt·해시·기대 커밋이며 지정 감사자용 암호화로만 내보낸다.

## 키 교체

1. 새 요청을 중지하고 진행 요청·증거 큐를 마친다. 기존 감사 패키지와 앱의 `체크포인트 저장` 결과를 보관한다.
2. 각 역할이 새 빈 operator 폴더에서 새 카드와 키를 만든다.
3. `deployment-propose`에 `--previous old-bundle.json --checkpoint old-checkpoint.json`을 추가한다.
4. 각 `deployment-endorse`에 `--previous-config <해당 역할의 이전 config.json>`을 추가한다. 이전/새 키가 모두 승인한다.
5. `deployment-assemble`에도 `--previous old-bundle.json`을 넣는다.
6. 각 `deployment-activate`에 같은 `--previous-config`를 넣는다. 활성화 시 그 로컬 역할의 이전 설정은 새 요청을 거부한다.
7. 기존 서비스를 종료하고 새 config.json으로 재실행한다. U도 새 설정을 적용해 preflight·strict·감사·목격을 확인한다.

앱의 `배포와 키` 화면도 같은 절차를 제공한다. 각 역할은 자기 계정에서 해당 단계를 수행한다.
로그·키·설정을 덮어쓰지 않으며 이전 체크포인트를 새 합의서에 연결한다. 이전 T는 증거 정리/감사를 제공하되 새 계약을 등록하지 않는다.
원격 동시 전환이나 무중단 교체를 자동 조율하지 않는다. 이전 키를 잃으면 이중 서명 교체를 할 수 없으므로 새 신뢰 배포를 별도로 합의해야 한다.
한 계보 안에서 W 추가/제거는 현재 지원하지 않는다. 관리자가 키·폐기 파일·전체 저장소를 되돌리는 위협은 외부 관측 없이 완전히 방어하지 못한다.

## 외부 앱 SDK

`itx/client.py`는 Python 표준 라이브러리로 동봉 Agent와 stdio 통신한다. 소비 앱은 검증 후 반환된 본문만 사용해야 한다.

```python
from itx.client import ItxClient, ResponseRejected

with ItxClient(
    r"C:\my-app\itx-state",
    config=r"C:\itx-data\operator-U\epochs\실제배포해시\config.json",
    agent_binary=r"C:\itx\itx-agent.exe",
) as client:
    try:
        result = client.request("사용자 요청", mode="strict")
        print(result.text)  # 수용된 본문만 소비한다.
    except ResponseRejected as error:
        print(error.state, error.request_id)  # 격리 본문은 없다.
```

`request()`는 protect/strict만 허용한다. 미검증 대조군은 `observe()`를 명시적으로 호출한다.
요청 토큰을 지정하면 다른 스레드에서 `cancel(token)`로 공개를 취소할 수 있다. 원격 모델 실행 취소까지 보장하지 않는다.
설정이 없을 때 실험실로 자동 전환하지 않는다. 명시적 `lab=True`가 필요하며 로컬 예제는 `python -m examples.verified-client`다.
동일 U 설정의 동시 Agent는 잠금으로 거부한다. SDK 사용 시 해당 설정의 데스크톱 앱을 닫거나 별도 U 배포를 사용한다.
