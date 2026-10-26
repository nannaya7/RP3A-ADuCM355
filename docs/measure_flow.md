# 측정 흐름 구현 (M-1 단계 실행기, M-2 Troponin 포팅)

> 구현 현황과 사용법. 설계 배경은 [models_overview.md](models_overview.md), 통신은 [uart_protocol.md](uart_protocol.md), 모델 분석은 [model_troponin_eis.md](model_troponin_eis.md).
> 검증: PC(Python 3.11.6)에서 가상 펌웨어 기준 전체 테스트 109개 통과. **Pi에서 동작하는 것은 사용자가 확인했다 (2026-10-24, 확인한 범위: 앱 동작). 실제 ADuCM355 모듈 연동과 실측 데이터로는 아직 확인하지 않았다.**

## 1. 구조

```
UartWorker (QThread) ─줄─▶ FirmwareClient ─레코드/이벤트─▶ MeasureController ─ViewState─▶ DashboardPage / PortraitDashboard (화면)
   comm/uart_worker.py       comm/firmware_client.py          measure/controller.py            ui/dashboard_page.py · dashboard_portrait.py
                                                                  │   └ models/troponin.py  (농도 계산)
                                                                  └ measure/store.py        (raw.log, result.json)
```

- **화면은 그리기만 한다.** `MeasureController.viewChanged(ViewState)`를 받아 위젯을 갱신하고, 버튼은 `primary()`, `stop()`, `restart()` 세 메서드만 호출한다. 그래서 **화면 디자인을 바꿔도 로직은 영향받지 않는다.**
- `ViewState`에 화면에 필요한 모든 값이 들어 있다: 상태, 단계 칩, 안내 문구, 주 버튼 라벨/활성, 타이머 텍스트, 진행률, 센서별 상태, 알림 배너, 결과.

## 2. 사용자 흐름 (확정 요구사항 반영)

| 단계 | UI 이름 | 모델 코드 이름 | 동작 |
|---|---|---|---|
| 시작 전 | | | 모듈 확인(`STATUS`, `CALSTATUS`, `ENV`) → 준비 |
| 1 | **T0** | T1 | 사용자가 **[T0 시작]** → 센서 0 → 1 → 2 순서로 각각 10Hz~200kHz 101점 측정(`START 1` 한 번) |
| 2 | **T1** | T2 | T0 완료 후 **반응 대기 타이머**(기본 15:00) 시작 → **타이머가 끝나야 [T1 시작] 버튼 활성화** → 사용자가 클릭하면 측정 |
| 3 | **T2** | T3 | T1 완료 후 **[T2 시작]** 활성 (사용자 수락 후 시작). 자동 진행은 담당자 협의 후 `auto_start_last = true`로 켠다 |
| 끝 | | | 계산 → 결과 화면 (예측 농도 숫자 + QC) |

- 모든 단계에 **타이머와 프로그레스 바**(측정 중에는 경과 시간과 점 수, 반응 대기에는 남은 시간)가 표시된다.
- 단계 사이에는 사용자 수락 없이 다음 `START`가 나가지 않는다 (테스트로 확인).
- 타이머가 끝나도 **자동으로 시작하지 않는다.** 사용자가 눌러야 한다.

### 상태
`disconnected → checking → ready ⇄ configuring → measuring → ready(다음 단계) … → computing → done`, 오류는 `error`, 모듈 무응답은 `no_module`, 중지 중은 `stopping`.

### 오류와 재시도
| 상황 | 동작 | 재시도(주 버튼) |
|---|---|---|
| 펌웨어 `ERR` | 클라이언트가 자동 `STOP` → 오류 표시, 부분 데이터 폐기 | 같은 단계를 바로 다시 측정 |
| 모듈에서 130초 무수신 | watchdog → 자동 `STOP` → 오류 | 같은 단계 다시 측정 |
| 점 수 부족 | 오류 | 같은 단계 다시 측정 |
| 연결 끊김 / 모듈 재시작 | 오류(통신 문제) | **모듈 확인부터** 다시 |
| `STATUS` 무응답 | `no_module` | [모듈 다시 확인] |
| 모델 QC 거부(예: T1 센서 2개가 어긋남) | 오류, 마지막 단계 재측정 안내 | 마지막 단계 다시 측정 |
| 사용자 [중지] | 부분 데이터 폐기, 같은 단계에서 대기 | 단계를 다시 시작 |

## 3. 설정 (`config.ini`)

```ini
[uart]
mock = false                    ; true 이면 가상 펌웨어 (python main.py --mock 과 같음)

[measure]
reaction_wait_s = 900           ; T1 시작 전 반응 대기(초). 화면 시험 시 10 정도로 줄여도 된다
reaction_timer_start = auto     ; auto: T0 완료 시 타이머 시작 / manual: 사용자가 [혈액 투입 완료]를 누르면 시작
auto_start_last = false         ; true: T2 자동 시작
sweep_start_hz = 10
sweep_stop_hz = 200000
sweep_points = 101
channels = 0,1,2
rtia_ohm = 1000
elapsed_min =                   ; 비우면 모델이 Day-1 중앙값을 가정하고 경고를 낸다
results_dir = results
```
- ⚠️ `reaction_timer_start = auto`는 **T0가 끝나는 순간 타이머가 시작**한다. 사용자가 혈액을 늦게 넣으면 실제 반응 시간이 15분보다 짧아질 수 있다. 정확히 하려면 `manual`로 바꿔 혈액 투입 시점에 버튼으로 시작하게 할 수 있다. **어느 쪽으로 할지는 담당자와 확인이 필요하다** (현재 기본 `auto`, 요구사항 문구 그대로).
- Pi의 `config.ini`는 덮어쓰지 말고 위 항목을 직접 추가한다.

## 4. 저장 (`results/<날짜_시각>_troponin/`)
| 파일 | 내용 |
|---|---|
| `raw.log` | 펌웨어에서 받은 **원문 줄**(수신 시각 포함) + 단계 시작/완료/오류 메모 |
| `result.json` | 모델 이름·버전, 설정, 단계별 점 수, 결과(값, **단위 null**, QC, D, B, score, 경고, 세부), **센서별 곡선 전체**(주파수, 크기, 위상, R, X, 상태) |
- 결과는 **마지막 단계가 끝나고 계산이 성공한 뒤** `result.json`이 쓰인다. 중간에 앱이 꺼지면 `raw.log`까지만 남는다 (단계별 중간 저장·복구는 아직 없음).
- 저장 실패(디스크 등)는 경고만 남기고 **측정은 계속**한다.

## 5. Troponin 모델 포팅 (`models/troponin.py`)
- 원본 `eis_concentration_predictor.py`의 계산을 **numpy만으로** 옮겼다 (pandas·파일 입출력 제거). 보정 계수는 `models/troponin_day1_calibration.json`(원본 복사, 버전 `261014-v1`).
- 입력: T1/T2/T3(+선택 c0)마다 센서 3개의 `(freq, z)` 곡선. 센서 3개를 원본의 "3회 반복"으로 취급한다.
- **c0 = 첫 측정(1단계, 센서 0·1·2)의 결과** (모델 담당자 피드백, 2026-10-26; `config.ini [measure] c0_source = first`, 기본). 컨트롤러가 1단계 곡선을 T1 과 c0 로 함께 넘긴다. `c0_source = none` 이면 c0 없이 과거 Day-1 앵커(240.16Ω)를 쓰고 경고한다(이전 동작). **실측으로 B 가 정상 범위인지 확인 필요**([model_troponin_eis.md](model_troponin_eis.md) §10).
- **c0가 없으면** 과거 Day-1 앵커(240.16Ω)를 쓰고 경고한다. `elapsed_min`이 없으면 Day-1 중앙값을 가정하고 경고한다 (원본과 같은 동작).
- 출력 `TroponinResult.value`는 **QC를 통과했을 때만** 있다. **단위는 `None`(미확정)이며 숫자만 표시한다.** 화면에 "연구용 · 임상 검증 전 · 단위 확인 중"을 함께 표시한다.

### 검증 결과
- 원본 CLI를 **같은 입력으로 실행해 비교**: 6개 시나리오(정상+c0, c0·경과시간 없음, RTIA·경과시간 다름, D 작은 변화, QC 실패, T2 스파이크+이상 반복)에서 D, B, score, 농도, QC 여부, T2 QC 조치 목록이 일치(상대 오차 1e-7 이내).
- 포팅에 일부러 오류를 넣어 보면(D 구간 10–50Hz → 10–60Hz) 테스트 5개가 실패한다.
- **한계**: 입력은 합성 데이터다. **실측 EIS 파일이 없어** 실제 데이터로는 검증하지 못했다. QC 임계값(RMS 0.08 등) 자체는 원본 값을 그대로 복사했고, 테스트 데이터가 그 경계 근처까지는 건드리지 않는다.
- 펌웨어는 주파수를 소수 2자리로 출력한다(예: 10.02Hz). 모델은 로그 주파수로 보간하므로 영향이 작다고 보이나 **실측 데이터로 확인이 필요하다.**

## 6. 실행 방법
```bat
run.bat mock                 :: 가상 펌웨어로 앱 실행 (모듈 없이 전체 흐름 시험)
python main.py --mock        :: 같은 동작
python main.py               :: 실제 UART(/dev/serial0 또는 config 포트)
```
- 가상 펌웨어 데모는 단계마다 약 3초이며, 반응 대기는 `reaction_wait_s`(기본 900초)를 기다려야 하므로 **시험할 때는 `config.ini`에서 10 정도로 줄인다.**
- Windows에서 `config.ini`의 포트를 열 수 없으면 자동으로 가상 펌웨어로 대체된다 (개발 편의). Pi에서는 대체하지 않고 `모듈이 응답하지 않습니다` 배너가 뜬다.

## 7. 화면을 손볼 때 (다음 작업을 위한 안내)
- **배치**: 가로 `ui/dashboard_page.py`, 세로 `ui/dashboard_portrait.py` (표시 로직은 `ui/dashboard_logic.py`). 위젯은 `objectName`으로 구분된다 (`dashCard`, `stepCard`, `resultPanel`, `profileCard` …). 자세한 내용은 `docs/measure_dashboard.md`.
- **모양**: `ui/theme.qss`의 "측정 화면" 블록. 상태에 따른 색은 property로 바뀐다: `stageChip[status=…]`, `sensorState[status=…]`, `banner[level=…]`, `timerText[waiting=…]`.
- **표시 내용**: 바꾸고 싶은 문구/값은 `measure/controller.py`의 `snapshot()`에서 만든다 (UI는 받은 값을 그대로 표시).
- **로직은 건드릴 필요 없다.** 새 정보가 화면에 필요하면 `ViewState`에 필드를 추가한다.
- 아직 없는 것: 터치 최적화 점검, 가상 키보드가 필요한 입력(키트 ID 등), 결과 상세 화면, 센서별 곡선 그래프, 단계별 중간 저장·복구, **세로(480x800) 레이아웃**.

## 8. 남은 확인 사항
1. 실제 Pi + 모듈 연동 (UART 배선, 한 사이클 소요 시간, 점당 시간)
2. **실측 EIS 데이터**로 포팅 검증, 모델 QC가 실제 센서 편차에서 어떻게 동작하는지
3. 반응 타이머 시작 시점(auto / manual) — 담당자 확인
4. c0 = 첫 측정 결과로 구현함 — 실측 B 범위 확인 ([model_troponin_eis.md](model_troponin_eis.md) §10), 농도 단위
5. T2 자동/수동 진행 — 담당자 협의 후 결정
6. NT-proBNP 연동 (특징 추출 코드 대기 — [request_nt_probnp.md](request_nt_probnp.md))
