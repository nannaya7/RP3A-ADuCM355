# ADuCM355 임피던스 측정 펌웨어 — 구조 분석

> 분석 대상: `refer/ADuCM355_FW/SRC` (FW 버전 **V.0.03.305**, `bia_meas.h:113`)
> 목적: Raspberry Pi GUI가 이 모듈과 UART로 통신하기 위해 알아야 할 동작을 정리한다.
> 상세 통신 규격은 [uart_protocol.md](uart_protocol.md), 측정·진단 흐름은 [measurement_and_diagnosis.md](measurement_and_diagnosis.md).

## 1. 한눈에 보기

| 항목 | 내용 |
|---|---|
| MCU | Analog Devices **ADuCM355** (Cortex-M3 디지털 다이 + AD5940 계열 아날로그 다이/AFE) |
| 기능 | 3선식(CE/RE/WE) **바이오 임피던스** 측정, 4채널(기본 3채널 사용) |
| 측정 방식 | AC 주파수 스윕(로그 간격) → DFT → RCAL 대비 임피던스 계산. 선택적으로 DC 전류(`#D`), 시간-전류(`#T`, CHRONO) |
| 통신 | **UART0, 115200 8N1** (P0.10 / P0.11), 텍스트 명령 입력 / 텍스트 레코드 출력 |
| 환경 센서 | HDC2010 (온도/습도, I2C0, 1Hz 자동 측정) — 레코드에 `TEMP_C`, `HUM_RH`로 포함 |
| 보정 | 보드별 SHORT 오프셋을 플래시에 저장, 측정값에서 자동 차감 |
| 상태 표시 | RGB LED (흰색=대기, 파랑=CH0/1 측정, 초록=CH2/3 측정, 노랑=보정, 빨강=오류) |
| 펌웨어 업데이트 | 부트로더(앱은 0x2000부터), `BOOT <코드>` 명령으로 진입 (GUI 일반 기능에서는 사용 안 함) |

> 펌웨어 주석이 참조하는 `setting.md`, `data_output.md`, `chrono.md`, `calibration.md`, `bootloader.md`, `Folder.md`, `GUI/core/presets.py`는 **제공된 폴더에 없다.** 이 문서는 소스 코드만으로 확인한 내용이며, 원 문서가 있으면 대조가 필요하다.

## 2. 소스 구성 (`SRC/`)

| 파일 | 역할 |
|---|---|
| `main.c` | 진입점. 26MHz 코어 클럭, UART0 초기화, WAKE_SW(P1.0) 풀업, AFE 인터럽트 초기화 후 `AD5940_Main()` 호출 |
| `AD5940Main.c` | AFE 플랫폼 설정, ADIID 자체 점검, 메인 루프 (`UartCli_Poll` → `Led_Process` → `BIA_Process`) |
| `bia_meas.c/h` | **측정 시퀀서.** 채널 순회, 설정(`BIA_Config_t`), 레코드 출력(`#H/#M/#C/#D/#T/#I`), 1ms 틱(TMR2) |
| `DRV/uart_cli.c/h` | **명령 파서.** 줄 단위, 대소문자 무시, 테이블 기반 디스패치 |
| `Impedance.c/h` | AD5940 임피던스 응용 계층 (시퀀서 + DFT, RTIA 자동 레인지, 20kHz 이상 고전력 모드) |
| `Amperometry.c/h` | DC 전류 / 크로노암페로메트리 (LPTIA) |
| `calibration.c/h` | SHORT 보정 (채널당 81점, 플래시 0x1E800, 2페이지) |
| `DRV/adg849.c/h` | ADG849 ×6 전극 멀티플렉서 (채널 선택) |
| `DRV/hdc2010/` | 온습도 센서 드라이버 |
| `DRV/led.c/h` | RGB LED 상태 표시 (active-low) |
| `DRV/RTT/` | SEGGER RTT 디버그 로그 (`BN_RTT` 정의 시에만) — **측정 데이터 경로가 아님** |

## 3. 부팅과 메인 루프

1. 클럭/UART/WAKE_SW/AFE 인터럽트 초기화 (`main.c`)
2. `AD5940PlatformCfg()`: AFE 클럭(내장 HFOSC 16MHz), FIFO(4KB, 임계 4워드), 인터럽트 설정
3. `UartCli_Init`, `Led_Init`, `BIA_Init`(틱 타이머, ADG849, 보정 블록 로드)
4. `#I,…,INFO,ADuCM355 3-wire bio-impedance, V.0.03.305` 출력
5. **ADIID 자체 점검** 실패 → `#I,000000,ERR,AFE ADIID mismatch …` + `AFE self test failed - halted`, 빨간 LED, 명령 폴링만 계속
6. HDC2010 초기화 → `INFO`(정상) 또는 `WARN`(응답 없음/설정 불일치). **센서가 없어도 측정은 계속**되며 온습도는 0.0으로 출력
7. `#I,…,INFO,System ready - send START to begin`, 흰색 LED
8. 무한 루프: 명령 폴링 → LED → `BIA_Process()`(실행 중일 때만 측정)

> GUI는 부팅 배너(`ADuCM355 3-wire bio-impedance`)와 `System ready` 줄을 **모듈 재시작 감지**에 사용할 수 있다.

## 4. 측정 동작 (`bia_meas.c`)

### 4.1 한 사이클
`BIA_Process()`는 `START`가 걸린 동안 **한 사이클 = 활성 채널 전체를 한 번씩 스윕**한다. 채널은 항상 번호 오름차순이다.

채널 하나의 처리 순서 (`BIA_MeasureChannel`):
1. HDC2010 최신값 갱신 (`BIA_UpdateEnv`)
2. LED 색 변경, ADG849로 채널 선택, **10ms 안정화** (`ADG849_SETTLE_MS`)
3. `BIA_ArmAfe()` — 현재 `BIA_Config_t`를 AFE에 반영(시퀀스 재생성). **설정 변경은 다음 채널 arm 시점에 적용**되며 스윕 도중에는 적용되지 않는다.
4. 점마다 DFT 완료를 기다려 `#M` 레코드 1줄 출력 (점당 가드 120초, 초과 시 `ERR measurement timeout`)
5. 스윕이 끝나면 `#I,…,INFO,RANGE CHx RTIA=…` 출력(자동 레인지 사용 시)
6. `DCEN ON`이면 `#D` 1줄 추가

사이클이 끝나면 `#I,…,INFO,CYCLE=<n> done`을 출력한다. **호스트는 이 줄로 한 사이클의 끝을 판단**하면 된다(레코드 개수를 셀 필요 없음).

### 4.2 채널 구성
| 채널 | AFE | ADG849 그룹 | 비고 |
|---|---|---|---|
| CH0 | AFE0 (CE0/RE0/SE0) | ASW_CH01 = High | 기본 활성 |
| CH1 | AFE0 | ASW_CH01 = Low | 기본 활성 |
| CH2 | AFE1 (CE1/RE1/SE1) | ASW_CH23 = High | 기본 활성 |
| CH3 | AFE1 | ASW_CH23 = Low | **기본 비활성** (기본 마스크 = CH0\|CH1\|CH2 = 0x7) |

- ADG849 극성은 직관과 반대다 (`adg849.h` 경고 참조).
- AFE는 하나의 고속 루프를 공유하므로 **병렬 측정은 불가**하다. `MODE PAR`는 SEQ로 낮춰지고 `WARN`이 출력된다.

### 4.3 기본 설정 (`g_cfg` 초기값, `bia_meas.c:73`)
| 항목 | 기본값 | 의미 |
|---|---|---|
| 스윕 | 1000Hz 단일점 (start=stop=1000, points=1) | **GUI가 반드시 `SWEEP`로 덮어써야 한다** |
| 채널 마스크 | 0x7 (CH0, CH1, CH2) | |
| 출력 상세도(VERB) | FULL | |
| 여기 신호 | 300 mVpp, HSDAC ×0.2, EXCITBUF ×0.25 | `SIGNAL` |
| RCAL | 1000 Ω | 보드에 실장된 R2(0.1%). `RCAL` 명령으로 바꾸면 모든 임피던스 값에 비례해 영향 |
| RTIA | AUTO | 점마다 자동 레인지 (200Ω~160kΩ 8단) |
| 전력 모드 | AUTO | 20kHz 미만 저전력, 이상 고전력 (`IMP_HP_THRESHOLD_HZ`) |
| DC 측정 | OFF, 바이어스 100mV | |

### 4.4 주파수 한계
- 입력 범위 0.016Hz ~ 200kHz, 점 수 최대 500 (`BIA_FREQ_*`, `BIA_POINTS_MAX`). 범위를 벗어나면 **고정값으로 잘라낸 뒤 그 값을 `#I`로 되돌려 준다.**
- 실용 하한은 **10Hz** (`bia_meas.h:121` 주석 — 그 아래는 점당 시간이 검증되지 않음)
- `CAL_*` 기준 격자: **10Hz ~ 100kHz, 81점, 로그 간격** — 코드 주석에 "Cortisol GUI 프리셋과 동일"이라고 적혀 있다. 진단 측정이 이 프리셋을 쓰는지는 확인이 필요하다.

### 4.5 측정 시간 (코드 주석 기반 추정)
- 채널 1개 SHORT 스윕(81점): 코드 주석에 "채널당 약 20~60초" (`bia_meas.c:660`)
- 100점 로그 스윕의 고전력 구간 점당 ≈ 0.77ms 수준 (`Impedance.h` 주석, 20kHz 이상) — 저주파가 대부분의 시간을 차지한다.
- 따라서 **81점 × 3채널 × 3회 = 수 분**이 걸릴 수 있다. **실기 측정으로 확인이 필요하다.**

## 5. 보정 (`calibration.c`)
- 보드마다 직렬 오프셋(RLOAD+배선, 약 110Ω)이 있어 **SHORT 보정**을 한다 (CE=RE=WE 단락).
- 채널당 81점의 R/X 오프셋을 플래시(0x1E800, 2페이지)에 저장하고, 측정 시 **로그 주파수 보간 후 R/X에서 복소 차감**한다. 차감 후 `MAG_OHM`/`PHASE_DEG`를 다시 계산한다.
- **원시 DFT 값(`Z_REAL`, `Z_IMAG`)은 보정되지 않는다.** `R_OHM`/`X_OHM`/`MAG_OHM`/`PHASE_DEG`가 보정 후 값이다.
- 보정이 없으면(`CALSTATUS`의 `VALID=0`) 보정은 아무 일도 하지 않는다 — 측정은 되지만 값이 보드 오프셋을 포함한다.
- `CALSHORT`/`CALCLR`/`BOARDID`는 **생산·서비스 전용**이며 환자 측정 GUI에서 노출하면 안 된다 (`CALSHORT`은 전극을 물리적으로 단락시켜야 한다).

## 6. GUI 통합 시 주의해야 할 펌웨어 동작 (코드에서 확인한 것)

| # | 동작 | 근거 | GUI 대응 |
|---|---|---|---|
| 1 | **오류가 나도 측정이 멈추지 않는다.** `BIA_Process()`는 채널 오류(`measurement timeout`, `AppIMPInit failed`) 시 `g_running`을 0으로 만들지 않고 그냥 반환한다. 다음 루프에서 **같은 사이클을 처음부터 다시 시도**한다. | `bia_meas.c:1029` | `#I,…,ERR,…`를 받으면 **즉시 `STOP`을 보낸다.** |
| 2 | `STOP`은 **실행 중이 아니면 아무 응답도 하지 않는다.** | `BIA_Stop()` | 응답을 기다리지 말고 타임아웃 후 `STATUS`로 확인 |
| 3 | 설정 명령(`SWEEP` 등)은 즉시 적용되지 않고 **다음 채널 arm 때** 적용된다. | `BIA_ArmAfe` | 측정 시작 전에 설정을 모두 보낸다 |
| 4 | 타임스탬프가 `%06lu` 형식이라 **999999ms(약 16.7분)를 넘으면 7자리 이상**이 된다. | 모든 `printf` | 파서는 자릿수 고정으로 가정하지 않는다 |
| 5 | 명령 한 줄은 **63자까지**. 초과하면 줄을 버리고 `ERR command too long`. | `UART_CLI_BUF_SIZE = 64` | 명령은 짧게 |
| 6 | 명령은 폴링으로 받는다. `CHRONO`의 LPDAC 안정화(약 1.6초), `CALSHORT`, `DC` 측정 중에는 **명령이 늦게 처리된다.** | `uart_cli.c` 주석 | 한 번에 한 명령, **응답(`#I` echo)을 받은 뒤 다음 명령** |
| 7 | 시작 직후 `#H` 헤더가 먼저 나온다 (`START`마다). | `UartCli_CmdStart` | `#H`에서 FW 버전/RCAL/모드를 기록 |
| 8 | 센서(HDC2010) 미응답 시 온습도는 **0.0**으로 나온다. 정상 측정값과 구분하려면 부팅 시 `WARN` 줄을 봐야 한다. | `AD5940Main.c:103` | `ENV` 명령 응답으로 `valid` 여부 확인 |
| 9 | `STATUS=SAT`인 점은 **ADC가 모든 이득에서 포화**된 점이다. 값은 출력되지만 신뢰할 수 없다. | `bia_meas.c:445` | 진단 입력에서 제외하거나 재측정 |
| 10 | 부트로더 비밀 코드는 **고정 문자열**이다(보안이 아니라 사고 방지용). `BOOT` 명령은 GUI에서 호출하지 않는다. | `uart_cli.c:567` | 노출하지 않음 |

## 7. 이번 분석에서 확인되지 않은 것
- **진단 알고리즘/판정 기준**: 펌웨어에는 없다. "진단 결과 도출"은 호스트(GUI) 쪽 기능이며, 입력/기준은 별도 정보가 필요하다 → [measurement_and_diagnosis.md](measurement_and_diagnosis.md) §6.
- **Pi와 모듈의 물리 연결**: Pi UART(`/dev/serial0`) 직결인지 USB-UART 변환인지, 전압 레벨(3.3V), 리셋/전원 제어선 유무.
- **실제 사용 프리셋**: 스윕 범위, 점 수, 채널 매핑(어느 채널이 어느 검사 항목인지).
