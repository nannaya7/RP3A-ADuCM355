# 3회 반복 측정 및 진단 결과 도출 설계

> 요구사항: **모듈에 연결된 진단키트를 3번 반복 측정하고, 그 결과 값으로 진단 결과를 도출한다.**
> 이 문서는 GUI(Raspberry Pi)가 펌웨어와 통신해 3회 측정을 수행하고 결과를 집계·판정·저장하는 흐름을 설계한다.
> 선행 문서: [firmware_overview.md](firmware_overview.md), [uart_protocol.md](uart_protocol.md)

> ⚠️ **갱신(모델 확인 후)**: 진단 모델이 **2개(NT-proBNP, Troponin)** 로 확인되었고, 각 모델의 측정 절차가 다르다. 특히 Troponin은 T1→T2(15분 반응)→T3 + c0 기준의 **다단계 프로토콜**이며 "3회"는 **단계마다 3회**다. 아래 §1~§5의 "3회 반복 후 진단 1개" 흐름은 **단일 단계 기준의 기본형**으로 읽고, 실제 흐름과 §6 진단 부분은 [models_overview.md](models_overview.md), [model_troponin_eis.md](model_troponin_eis.md), [model_nt_probnp_v18.md](model_nt_probnp_v18.md)를 따른다.

## 0. 먼저 알아둘 것 (확인된 사실과 미정 사항)

| 구분 | 내용 |
|---|---|
| ✅ 확인됨 | 펌웨어는 **측정만** 한다. 임피던스(|Z|, 위상, R, X), 온습도를 줄 단위로 보낸다. **진단/판정 로직은 펌웨어에 없다.** |
| ✅ 확인됨 | 펌웨어에는 "N회 반복"을 위한 `START <cycles>`가 있다. 한 사이클 = 활성 채널 전체를 한 번씩 스윕. |
| ✅ 확인됨 | **진단 모델 2개 제공**: Troponin(원시 EIS → 농도, 코드 완전), NT-proBNP(6개 특징량 → 농도, **특징 추출 코드 없음**) |
| ❓ 미정 | NT-proBNP 특징 추출 정의, 두 검사의 채널/프로토콜, Troponin 농도 단위 |
| ❓ 미정 | 측정 **프리셋**(주파수 범위·점 수), **어느 채널이 어느 검사 항목인지** |
| ❓ 미정 | 반복 사이 **대기 시간 / 키트 처리**(그대로 두는지, 교체·세척하는지) |
| ❓ 미정 | 진단에 DC 전류(`#D`)나 시간-전류(`#T`, CHRONO)가 필요한지 |

> 참고: 펌웨어 `calibration.h`가 "Cortisol GUI 프리셋(10Hz~100kHz, 81점)"과 "세 가지 assay"를 언급하는 것은 **이전 프로젝트의 흔적**으로 보인다. 실제 진단 모델은 **NT-proBNP와 Troponin**이다. Troponin 모델의 주파수 격자는 **10Hz~200kHz, 101점**으로 추정된다([model_troponin_eis.md](model_troponin_eis.md) §6).

따라서 이 문서의 §6(진단)은 **인터페이스와 자리만 정의**하고, 실제 판정식은 정보가 확정된 뒤 채운다. **임상 기준값을 임의로 만들지 않는다.**

## 1. 전체 흐름

```
[측정 시작 버튼]
   │
   ├─ 0. 사전 점검      : 연결, STATUS, CALSTATUS(VALID=1?), ENV, 키트 삽입 확인(있다면)
   ├─ 1. 설정 전송      : SWEEP / CHAN / VERB FULL (+SIGNAL/RCAL)
   ├─ 2. 반복 측정 ×3   : 반복 i = 1..3   ── START 1 → #M 수집 → CYCLE=1 done
   │       └ 각 반복 후 품질 검증 (불합격이면 재시도 정책 §3.3)
   ├─ 3. 집계           : 채널·주파수별 평균/표준편차/CV (§5)
   ├─ 4. 진단 도출      : Diagnoser.diagnose(MeasurementSet) (§6)
   └─ 5. 표시·저장      : 결과 화면, results/*.json + 원시 로그 (§7)
```

## 2. 측정 설정

GUI는 **펌웨어 기본값에 의존하지 않고** 매 측정 전에 모든 설정을 보낸다 (펌웨어 기본은 1kHz 단일점이라 진단에 쓸 수 없다).

`config.ini`에 둘 항목(제안):

```ini
[measure]
start_hz = 10          ; 확정 필요 (참고: Cortisol 프리셋 10~100000Hz, 81점)
stop_hz  = 100000
points   = 81
channels = CH0,CH1,CH2 ; 확정 필요 (펌웨어 기본 마스크 0x7)
repeats  = 3
```

| 항목 | 값 | 비고 |
|---|---|---|
| 반복 횟수 | **3** (고정 요구사항) | 설정값으로 두되 기본 3 |
| 출력 상세도 | `VERB FULL` | R/X와 원시 DFT 모두 저장 |
| 신호 | 펌웨어 기본(300mVpp, ×0.2, ×0.25) | 바꿀 근거가 생기면 `SIGNAL` |
| RCAL | 1000Ω | 보드 실장값과 같아야 함. 바꾸지 않음 |
| RTIA | AUTO | 점마다 자동 레인지 |
| 보정 | 보드에 SHORT 보정이 저장되어 있어야 함 | `CALSTATUS`의 `VALID=1` 확인 |

### 예상 측정 시간 (**추정, 실기 확인 필요**)
- 코드 주석: 채널당 81점 스윕이 대략 20~60초.
- 3채널 × 3회 ≈ **3~9분**. 이 값은 UI의 진행 표시·타임아웃·사용자 안내(예상 소요 시간)에 쓰이므로 **실제 하드웨어로 한 번 측정해 확정**한다.

## 3. 3회 반복 측정 전략

### 3.1 선택지

| 방식 | 장점 | 단점 |
|---|---|---|
| **A. `START 1`을 3번** (권장) | 반복 사이에 호스트가 개입 가능(대기, 검증, 재시도, 진행 표시, 키트 교체 안내). 실패한 반복만 다시 측정 가능 | 명령 왕복이 한 번 더 있음 |
| B. `START 3` 한 번 | 명령 1회. 사이클이 쉬는 시간 없이 연속 | 반복 사이 개입 불가. 중간 오류 시 3회 전체를 다시 해야 할 수 있음 |

**권장: A.** 펌웨어는 한 번 학습한 RTIA 테이블을 설정이 바뀔 때까지 유지하므로(`BIA_RangeSyncKey`), 반복 2·3회는 자동 레인지 재시도가 줄어 **더 빠르고 안정적**이다. (A·B 모두 해당)

### 3.2 반복 1회의 절차
```
START 1
  #H 수신                         → FW 버전/RCAL 기록
  "measurement started" 수신      → 시작 확인 (타임아웃 15초)
  #M … 수신 (채널 오름차순)       → 점 수집, 진행률 갱신
  "CYCLE=1 done" 수신             → 사이클 완료
  "measurement stopped" 수신      → 종료 확인
검증(§5.1) → 합격이면 다음 반복
```
- 진행률 = `수신한 #M 수 / (활성 채널 수 × points × repeats)`.
- 어느 시점이든 `ERR` 수신 → 즉시 `STOP` → 반복 실패 처리.

### 3.3 실패·재시도 정책 (제안, 확정 필요)
| 상황 | 처리 |
|---|---|
| `#I,ERR` (타임아웃, AppIMPInit 실패) | `STOP` → 해당 반복 1회 재시도 → 재실패 시 측정 중단, 오류 화면 |
| 응답 무수신 130초 | `STOP` 시도 → `STATUS` → 무응답이면 **연결 오류** 처리(재연결 후 처음부터) |
| 점 수 부족 / `CYCLE done` 미수신 | 반복 무효 → 재시도 |
| `STATUS=SAT`인 점이 있음 | 아래 §5.1 기준에 따라 점 제외 또는 반복 무효 |
| 사용자가 [중지] | `STOP` → 부분 결과는 **진단하지 않고** 폐기(또는 임시 저장) |
| 모듈 재시작 감지(부팅 배너 수신) | 측정 무효, 처음부터 |
| 재시도 한도 | 반복당 1회, 전체 합계 3회(제안) |

### 3.4 반복 사이 대기 (미정)
키트를 그대로 두는 연속 측정이면 대기 0이어도 되지만, 전극 안정화·시료 반응 시간이 필요하면 **설정값 `repeat_interval_s`** 로 둔다. 기본 0, 확정되면 반영.

## 4. 데이터 모델과 상태

### 4.1 파이썬 구조 (제안, `measure/` 패키지)
```python
@dataclass(frozen=True)
class Point:                     # #M 한 줄
    ts_ms: int; ch: str; freq_hz: float
    z_real: int; z_imag: int     # 원시 DFT (보정 안 됨)
    mag_ohm: float; phase_deg: float
    r_ohm: float; x_ohm: float   # SHORT 보정 후
    temp_c: float; hum_rh: float
    sat: bool                    # STATUS == "SAT"

@dataclass
class RepeatResult:              # 1회 반복(= 1 사이클)
    index: int                   # 1..3
    points: dict[str, list[Point]]   # 채널 → 주파수 순 점 목록
    started_at: datetime; finished_at: datetime
    warnings: list[str]

@dataclass
class MeasurementSet:            # 진단 입력
    kit_id: str | None; operator: str | None
    fw_version: str; board_id: int | None; rcal_ohm: float
    sweep: SweepConfig
    repeats: list[RepeatResult]  # 길이 3
    env_start: tuple[float, float] | None  # (℃, %RH)
```

### 4.2 측정 화면 상태 머신 (DESIGN.md 단계 4 개정)
```
DISCONNECTED ─연결→ CHECKING ─정상→ READY
READY ─시작→ CONFIGURING ─→ MEASURING(rep 1/3) ─→ MEASURING(rep 2/3) ─→ MEASURING(rep 3/3)
                                  │ (각 반복 사이: VALIDATING)
MEASURING 완료 ─→ ANALYZING ─→ DONE
어느 상태에서나 오류 ─→ ERROR (재시도/취소)         사용자 중지 ─→ STOPPING ─→ READY
```
- 상태별 표시: 연결 LED, "반복 n/3", 채널/주파수 진행 바, 경과 시간, 중지 버튼.
- `READY` 진입 조건: `STATUS` 응답, `CALSTATUS VALID=1`(아니면 경고 배너), 온습도 유효 여부 표시.

## 5. 집계와 품질 검증

### 5.1 반복 단위 검증 (진단 전)
| 검사 | 기준(제안) | 불합격 시 |
|---|---|---|
| 점 수 | 채널별 `points`개 모두 수신 | 반복 무효 |
| 주파수 정합 | 반복 간 같은 인덱스의 `freq_hz` 오차 < 0.1% | 경고 |
| SAT | 채널별 SAT 비율이 한도 이하 (예: 0%) | 해당 점 제외 또는 반복 무효 — **기준 확정 필요** |
| 값 유효성 | `nan`, 음수 크기, 비정상적으로 큰 값 없음 | 반복 무효 |
| 환경 | 온습도가 0.0이면 "센서 미응답" 경고 | 경고(진단은 허용) |
| 반복 간 일관성 | §5.2의 CV가 한도 이내 | 진단 결과에 신뢰도 낮음 표시 / 재측정 권고 |

### 5.2 3회 집계
채널 c, 주파수 인덱스 k, 지표 v ∈ {R, X, |Z|, 위상}에 대해
```
mean(c,k,v) = (v₁ + v₂ + v₃) / 3
std(c,k,v)  = 표본 표준편차 (n−1 = 2)
cv(c,k,v)   = std / |mean| × 100 [%]
```
- n=3은 표본이 매우 작아 표준편차가 거칠다. 중앙값/최솟·최댓값도 함께 저장해 두면 알고리즘이 정해진 뒤 선택할 수 있다.
- **평균할 값**: 위상은 각도이므로 −180/+180 경계 근처에서는 R/X로 평균한 뒤 위상을 재계산하는 편이 안전하다 (`atan2(mean X, mean R)`).
- 아웃라이어 처리(1회만 크게 어긋난 경우 제외할지 등)는 알고리즘 확정 후 정한다.

## 6. 진단 결과 도출

### 6.1 인터페이스
```python
@dataclass
class DiagnosisResult:
    status: Literal["OK", "INCONCLUSIVE", "INVALID"]   # 판정 가능 여부
    verdict: str | None            # 예: "양성/음성", 등급 등 — 알고리즘이 정의
    values: dict[str, float]       # 항목별 산출값(예: 농도·지수)
    confidence: float | None
    reasons: list[str]             # 판정 불가/주의 사유
    algorithm_version: str

class Diagnoser(Protocol):
    def diagnose(self, data: MeasurementSet) -> DiagnosisResult: ...
```
- `app`은 `Diagnoser` 인터페이스만 안다. 알고리즘이 바뀌어도 UI는 영향이 없다.
- 결과에는 항상 **`algorithm_version`과 입력 요약(펌웨어 버전, 보드 ID, 설정)** 을 남겨 재현 가능하게 한다.

### 6.2 알고리즘 확정에 필요한 정보 (**요청 목록**)
1. 판정에 쓰는 **특징량**: 특정 주파수의 |Z|/위상/R/X? 등가회로(Cole-Cole 등) 피팅 파라미터? 3회 평균 후 사용? 주파수 구간 적분?
2. 채널↔검사 항목 매핑 (CH0/CH1/CH2 각각의 의미, 기준 채널·블랭크 채널 여부)
3. **기준값/판정 임계치** 또는 보정 곡선(농도 환산식), 단위
4. 결과의 종류(정성: 양/음성, 정량: 농도, 등급 등)와 화면에 표시할 문구
5. 온습도 보정 필요 여부
6. 판정 불가(재측정) 조건
7. 규제/문구 요구(의료기기 소프트웨어라면 검증·변경 이력 관리 필요)
8. 레퍼런스 구현이나 데이터셋(있으면 테스트 기준으로 사용)

### 6.3 확정 전 임시 처리
- `DemoDiagnoser`: 집계·표시·저장 흐름을 검증하기 위한 **명확히 "DEMO"로 표시되는** 더미. 임상 판정을 흉내 내지 않고, 예를 들어 "측정 완료, 알고리즘 미적용"과 요약 통계만 반환한다.
- 결과 화면에 `알고리즘 미적용(개발 빌드)` 배너를 표시해 **오해 소지를 없앤다.**

## 7. 결과 저장

`results/<YYYYMMDD_HHMMSS>_<kit_id>/`
| 파일 | 내용 |
|---|---|
| `result.json` | 메타데이터 + 설정 + 집계(평균/표준편차/CV) + 진단 결과 + 경고 |
| `raw.log` | 펌웨어에서 받은 **원문 줄 그대로**(수신 시각 포함). 사후 재계산·문제 분석용 |
| `repeats.csv` | 반복·채널·주파수별 점 데이터 (엑셀 분석용) |

`result.json` 주요 필드:
```json
{
  "schema": 1,
  "kit_id": "...", "started_at": "...", "operator": "...",
  "firmware": {"version": "V.0.03.305", "board_id": 12, "cal_valid": true},
  "sweep": {"start_hz": 10, "stop_hz": 100000, "points": 81, "channels": ["CH0","CH1","CH2"]},
  "repeats": 3,
  "env": {"temp_c": 24.1, "hum_rh": 41.0},
  "aggregate": { "...": "채널·주파수별 mean/std/cv" },
  "diagnosis": {"status": "...", "verdict": "...", "algorithm_version": "..."},
  "warnings": []
}
```
- 환자 식별 정보가 들어갈 수 있으므로 **파일 권한과 보관/삭제 정책**을 별도로 정한다(서버 업로드는 5단계 이후).

## 8. 구현 계획 (DESIGN.md 단계 3·4 개정안)

기존 단계 3(바이너리 프로토콜)은 실제 펌웨어와 달라 **재작업**이 필요하다.

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| **3-R** | 줄 버퍼 + 레코드 파서, `FirmwareClient`(명령→echo 대기), CLI를 흉내 내는 Mock 펌웨어, UartWorker 수정 | 파서/클라이언트 단위 테스트 통과, `tools/uart_demo.py`로 Mock 왕복(설정→START 1→CYCLE done) |
| 3-R2 | **실기 UART 확인**: Pi ↔ 모듈 `STATUS`, `CALSTATUS`, `ENV`, 짧은 `START 1` | 실제 `#M` 수신, 한 사이클 소요 시간 측정 |
| **4-a** | 측정 오케스트레이터(`MeasureController`): 사전 점검 → 설정 → 3회 반복 → 검증 → 집계. UI 없이 Qt 시그널만 | Mock에서 3회 반복 자동 수행, 오류 주입 시 재시도/중단 동작 |
| 4-b | 측정 화면 UI: 상태 머신, 진행 표시, 중지, 결과 요약 | 가로 화면에서 전체 흐름 동작 |
| 4-c | 저장(`result.json`, `raw.log`, `repeats.csv`) | 재열람 가능, 원문 로그로 재계산 일치 |
| 4-d | `Diagnoser` 연동 (Demo → 실제 알고리즘) | 알고리즘 정보 확정 후 |

## 9. 열린 질문 (진행 전에 답이 필요한 순서)

1. **진단 알고리즘 정보** (§6.2) — 가장 중요. 문서·코드·논문·엑셀 어떤 형태든 좋다.
2. **프리셋**: 측정 주파수 범위·점 수, 사용 채널과 의미.
3. **Pi ↔ 모듈 연결**: 직결 UART인가 USB-UART인가? 전압 레벨? 모듈 리셋/전원 제어선이 있는가?
4. **반복 사이 처리**: 대기 시간, 키트를 그대로 두는가.
5. 사용자가 키트 삽입/제거를 알릴 방법이 있는가(센서·스위치)? 없다면 GUI에서 사용자 확인 단계가 필요하다.
6. DC 전류(`#D`) / CHRONO(`#T`)를 진단에 쓰는가.
7. 모듈에 SHORT 보정이 이미 저장되어 있는가(`CALSTATUS`)? 생산 시 보정 절차는 누가 하는가.
8. 환자/키트 식별 방식(바코드, 수동 입력 등)과 결과 서버 업로드 요구.
