# UART 통신 규격 (ADuCM355 펌웨어 V.0.03.305)

> 출처: `refer/ADuCM355_FW/SRC/DRV/uart_cli.c`, `bia_meas.c`, `calibration.c` 소스에서 직접 확인한 내용.
> 펌웨어가 참조하는 `data_output.md` / `setting.md`는 제공되지 않아, **소스에 없는 규칙은 적지 않았다.**
> 관련 문서: [firmware_overview.md](firmware_overview.md), [measurement_and_diagnosis.md](measurement_and_diagnosis.md)

> ⚠️ **기존 설계 변경 필요**: `DESIGN.md` 단계 3에서 가정했던 바이너리 프레임(`STX | LEN | CMD | PAYLOAD | CRC16 | ETX`)은 **실제 펌웨어와 다르다.** 실제는 **줄 단위 ASCII 텍스트**다. `comm/protocol.py`, `comm/mock_device.py`, 관련 테스트를 이 문서 기준으로 다시 만들어야 한다 (§8).

## 1. 물리/링크 계층

| 항목 | 값 |
|---|---|
| 포트 | UART0 (MCU P0.10 / P0.11) |
| 속도 | **115200 bps, 8 data, no parity, 1 stop (8N1)**, 흐름 제어 없음 |
| 레벨 | MCU 로직 레벨(3.3V 추정) — Pi와 직결 여부/레벨 변환은 **미확인** |
| 줄 끝 | 입력: `CR`, `LF`, `CRLF` 모두 허용, 빈 줄은 무시. 출력: 항상 `\r\n` |
| 대소문자 | 명령은 **대소문자 무시** (펌웨어가 전체를 대문자로 변환) |
| 토큰 | 공백/탭 구분, 최대 6개 토큰 |
| 최대 줄 길이 | **63자** (버퍼 64바이트, 종단 문자 포함). 초과 시 줄을 버리고 `ERR,command too long` |
| 수신 방식 | 폴링. 측정 중에도 폴링되지만 일부 구간(아래 §6)에서는 지연된다 |

## 2. 출력 레코드 (펌웨어 → 호스트)

모든 출력은 `#`로 시작하는 한 줄이다. 첫 필드가 레코드 종류, 둘째 필드가 **타임스탬프(ms, 부팅 후)** 다.
`#` 로 시작하지 않는 줄은 무시한다.

### 2.1 공통 규칙
- 구분자는 쉼표 `,`. (`#H`의 `COLUMNS=`와 `STATUS` 줄의 `SWEEP=a:b:n`은 `|`, `:`, 공백으로 따로 구분)
- 타임스탬프는 `%06lu` — **6자리로 0 채움이지만 999999ms(≈16.7분)를 넘으면 자릿수가 늘어난다.** 고정 폭으로 자르지 말고 정수로 파싱한다. 약 49.7일 후 0으로 되돌아간다.
- 소수는 `BIA_PrintFloat` 방식의 고정 소수점이며 **음수는 `-` 접두**가 붙는다. 값이 NaN이면 `nan`, 4.0e9를 넘으면 4000000000으로 포화된다. (지수 표기는 쓰지 않는다.)
- 채널 이름은 `CH0`~`CH3`.

### 2.2 `#I` — 정보/상태/오류
```
#I,<TS>,<LEVEL>,<메시지>
```
| LEVEL | 의미 |
|---|---|
| `INFO` | 일반 정보, 명령 확인(echo) |
| `WARN` | 경고(측정은 계속 가능) |
| `ERR` | 오류. **측정 중이면 반드시 `STOP`을 보낸다** (firmware_overview §6-1) |
| `STATUS` | `STATUS` / `CALSTATUS` 명령의 응답 전용 |

메시지 자체에 쉼표가 들어 있을 수 있으므로 `#I`는 **앞 3개 쉼표까지만** 자르고 나머지는 메시지로 취급한다 (`split(",", 3)`).

호스트가 의미를 해석해야 하는 메시지:

| 메시지(접두/전체) | 의미 |
|---|---|
| `ADuCM355 3-wire bio-impedance, V.0.03.305` | 부팅 배너 (모듈 시작/재시작) |
| `System ready - send START to begin` | 명령 수신 준비 완료 |
| `AFE self test failed - halted` / `AFE ADIID mismatch 0x…` | **치명적**: AFE 응답 없음. 이후 측정 불가 |
| `HDC2010 ready …` / `WARN HDC2010 not responding …` | 온습도 센서 상태 (미응답 시 TEMP/HUM=0.0) |
| `measurement started, <N> cycle(s)` / `…, continuous` | `START` 수락 |
| `CYCLE=<n> done` | **사이클 n 완료** (활성 채널 전체가 한 번씩 끝남) |
| `measurement stopped` | 측정 종료 (지정 사이클을 모두 마쳤거나 `STOP`) |
| `RANGE CHx RTIA=<min>..<max> RETRY=<n> SAT=<n>` | 채널별 자동 레인지 요약 |
| `measurement timeout` (ERR) | 한 점이 120초 안에 안 끝남 → **STOP 필요** |
| `AppIMPInit failed` (ERR) | AFE 시퀀스 초기화 실패 → **STOP 필요** |
| `CHRONO: …` | 크로노암페로메트리 진행(§2.7) |
| `CALSHORT: …` | SHORT 보정 진행(서비스 모드) |

### 2.3 `#H` — 측정 헤더 (`START`마다 1회)
```
#H,FW=V.0.03.305,RCAL=1000.0,MODE=SEQ,COLUMNS=TIMESTAMP|CH|FREQ_HZ|Z_REAL|Z_IMAG|MAG_OHM|PHASE_DEG|R_OHM|X_OHM|TEMP_C|HUM_RH|STATUS
```
`COLUMNS`는 `VERB` 설정과 **무관하게 항상 FULL 열 목록**이다. 실제 `#M` 열은 §2.4를 따른다.

### 2.4 `#M` — 임피던스 측정점 (스윕 한 점당 1줄)
`VERB` 설정에 따라 세 가지 형식이다.

| VERB | 형식 | 필드 수(`#M` 포함) |
|---|---|---|
| **FULL** (기본) | `#M,TS,CH,FREQ_HZ,Z_REAL,Z_IMAG,MAG_OHM,PHASE_DEG,R_OHM,X_OHM,TEMP_C,HUM_RH,STATUS` | 13 |
| COMPACT | `#M,TS,CH,FREQ_HZ,MAG_OHM,PHASE_DEG,TEMP_C,HUM_RH,STATUS` | 9 |
| RAW | `#M,TS,CH,FREQ_HZ,Z_REAL,Z_IMAG,STATUS` | 7 |

| 필드 | 형식 | 설명 |
|---|---|---|
| TS | 정수 ms | 그 점이 수집된 시각 |
| CH | `CH0`~`CH3` | |
| FREQ_HZ | 소수 2자리 | **실제 측정 주파수** (요청값이 아니라 펌웨어가 돌려준 값) |
| Z_REAL / Z_IMAG | 정수 | DUT 쪽 **원시 DFT 값**. **보정되지 않음** |
| MAG_OHM / PHASE_DEG | 소수 2자리 | 임피던스 크기(Ω)와 위상(도). **SHORT 보정 후** 값 |
| R_OHM / X_OHM | 소수 2자리 | 저항/리액턴스 성분(Ω). **보정 후**. (`MAG·cosφ`, `MAG·sinφ`) |
| TEMP_C / HUM_RH | 소수 1자리 | 센서 최신값. 센서 미응답 시 `0.0` |
| STATUS | `OK` \| `SAT` | `SAT` = RTIA 자동 레인지가 끝까지 가도 ADC가 포화. **신뢰 불가** |

**GUI는 `VERB FULL`을 사용한다** (진단에 R/X가 필요할 수 있고 원시 DFT도 로그로 남길 수 있다). 한 줄 길이는 약 90바이트, 81점×3채널 ≈ 22KB/사이클이라 115200bps에서 전송 시간은 약 2초로 측정 시간 대비 무시할 수준이다.

### 2.5 `#C` — RCAL 참조 (AFE별 첫 점 직전, `START`마다 AFE당 1회)
```
#C,<TS>,AFE0,<RCAL_OHM>,<RCAL_REAL>,<RCAL_IMAG>,OK
```
`CAL` 명령 이후 다음 사이클에서 다시 출력된다. 진단 계산에는 `#M`만으로 충분하며 `#C`는 로그용이다.

### 2.6 `#D` — DC 전류 (`DCEN ON`일 때 채널당 1줄)
```
#D,<TS>,<CH>,<BIAS_MV>,<CURRENT_UA>,<RTIA_OHM>,OK|ERR
```
### 2.7 `#T` — 시간-전류 (`CHRONO` 명령 전용)
```
#T,<TS>,<CH>,<T_MS>,<CURRENT_UA>,<RTIA_OHM>,OK|SAT
```
`T_MS`는 **채널별 CHRONO 시작 후 경과 시간**(부팅 타임스탬프가 아님). 이 문서의 3회 반복 임피던스 측정에는 사용하지 않지만, 진단에 크로노암페로메트리가 필요한지는 미확인이다.

### 2.8 `#B` — 보정 블록 (`CALSHOW` 응답, 서비스용)
```
#B,<TS>,HDR,BOARD_ID=<id|UNSET>,VALID=<0|1>,ENABLED=<0|1>,POINTS=81
#B,<TS>,PT,<CH>,<idx>,<FREQ_HZ>,<SHORT_R>,<SHORT_X>
```
(채널 4개 × 81점 = 324줄)

## 3. 명령 (호스트 → 펌웨어)

한 줄에 하나, `\r\n` 종료. 설정 명령은 **BIA_Config_t만 갱신**하며 *다음 채널 arm 시점*에 적용된다. 모든 명령은 응답으로 `#I` 줄을 돌려준다 (확인된 예외는 표에 표시).

### 3.1 GUI 측정에서 사용하는 명령

| 명령 | 인자 | 정상 응답(`#I,TS,INFO,…`) | 비고 |
|---|---|---|---|
| `SWEEP` | `<START_HZ> <STOP_HZ> <POINTS>` | `SWEEP set <start> <stop> <points>` | 범위 밖은 **보정된 값으로 응답**. `POINTS=1`이면 STOP 무시(단일 주파수). 로그 간격 고정 |
| `CHAN` | `CH0,CH2` \| `CH0 CH2` \| `0x5` \| `ALL` \| `DEFAULT` | `CHMASK=0x<hex>` | 실행 순서는 항상 번호 오름차순. 오류: `unknown channel`, `channel mask out of range`, `no channel selected` |
| `VERB` | `FULL` \| `COMPACT` \| `RAW` | `VERB=<값>` | |
| `SIGNAL` | `<mVpp> <X1\|X0P2> <X2\|X0P25>` | `SIGNAL set <mVpp> <HSDAC> <EXCITBUF>` | 0~800mVpp로 제한 |
| `RCAL` | `<OHM>` | `RCAL set <ohm>` | **실장 저항을 바꿨을 때만.** 모든 임피던스에 비례 영향 |
| `START` | `[CYCLES]` (기본 1, `0`=STOP까지 무한) | `#H,…` 먼저, 이어서 `measurement started, N cycle(s)` | 아래 §4 |
| `STOP` | — | `measurement stopped` | **실행 중일 때만 응답** |
| `STATUS` | — | `#I,TS,STATUS,RUN=<0\|1> SWEEP=<a>:<b>:<n> CHMASK=0x<h> MODE=… VERB=… SIGNAL=<mV>:<g1>:<g2> RCAL=<ohm> RTIA=… PWRMODE=… CYCLES=<남은> DONE=<완료> DCEN=<0\|1> DCBIAS=<mV>` | 현재 설정 전체 + 진행 상태 |
| `ENV` | — | `ENV TEMP_C=<t> HUM_RH=<h>` 또는 `WARN,ENV not available …` | 온습도 즉시 조회 |
| `CALSTATUS` | — | `#I,TS,STATUS,CAL VALID=<0\|1> ENABLED=<0\|1> BOARD_ID=<n\|UNSET>` | **측정 전 보정 여부 확인용** |
| `CAL` | — | `calibration will be reported on next cycle` | RCAL 재보고 + 레인지 테이블 초기화. 시료를 바꿨을 때 |

### 3.2 GUI에서 쓰지 않는 명령 (개발·서비스용)

| 명령 | 용도 | 비고 |
|---|---|---|
| `MODE <SEQ\|PAR>` | 측정 모드 | `PAR`은 SEQ로 낮춰지고 `WARN` |
| `RTIA <OHM\|AUTO>` | HSTIA 이득 고정 | 브링업용. 기본 AUTO 유지 |
| `PWRMODE <AUTO\|LOW\|HIGH>` | AFE 전력 모드 강제 | 브링업용. HIGH를 20kHz 미만에서 쓰면 데이터가 손상될 수 있다고 코드에 명시 |
| `DCEN`, `DCBIAS` | DC 전류 측정 | 진단에 필요한지 미확인 |
| `CHRONO [SEC] [PERIOD_MS] [RTIA\|AUTO]` | 시간-전류 | 블로킹, 채널당 SEC초 |
| `CALSHORT`, `CALSHOW`, `CALAPPLY`, `CALCLR`, `BOARDID` | SHORT 보정 관리 | 전극 단락이 필요 — **서비스 모드 전용** |
| `BOOT <코드>` | 부트로더 진입(펌웨어 업데이트) | GUI에 **노출하지 않는다**. 응답 없이 리셋됨 |

잘못된 명령은 `ERR,unknown command`, 인자 부족은 `ERR,usage: …`.

## 4. 측정 세션 시퀀스

### 4.1 연결 직후 (호스트가 먼저 한 번)
```
(포트 열기) → (입력 버퍼 비우기) → 빈 줄 전송 → STATUS
   └ 응답 #I,…,STATUS,RUN=0 …  → 모듈 정상, 유휴
   └ 무응답(1초 ×N회)           → 모듈 없음/배선/보드 리셋 중
→ CALSTATUS → VALID=1 확인 (아니면 경고, 서비스 보정 필요)
→ ENV       → 온습도 유효 확인
```
모듈이 방금 재시작했다면 부팅 배너와 `System ready…`가 먼저 올 수 있으므로 **`#I` 줄은 종류별로 처리하고 순서에 의존하지 않는다.**

### 4.2 측정 전 설정 (매번 전부 보낸다 — 펌웨어 기본값에 의존하지 않는다)
```
SWEEP <start> <stop> <points>     ← 기본값은 1000Hz 단일점이라 반드시 필요
CHAN  <채널 목록>
VERB  FULL
SIGNAL … / RCAL …                 ← 기본값을 바꿀 때만
```
각 명령은 **응답(`#I` echo)을 받은 뒤** 다음 명령을 보낸다. echo의 값이 요청과 다르면(클램프됨) 사용자에게 알린다.

### 4.3 측정
```
START 1
 ← #H,FW=…
 ← #I,…,INFO,measurement started, 1 cycle(s)
 ← #C,…,AFE0,…            (AFE별 첫 점 직전)
 ← #M,…,CH0,…  ×points
 ← #I,…,INFO,RANGE CH0 RTIA=…
 ← #C,…,AFE1,…            (CH2가 활성이면)
 ← #M,…,CH1,… …  (채널 오름차순 반복)
 ← #I,…,INFO,CYCLE=1 done
 ← #I,…,INFO,measurement stopped
```
- 사이클 완료 판정은 **`CYCLE=n done`**. 레코드 개수에 의존하지 않는다.
- `START N`은 사이클을 쉬는 시간 없이 이어서 실행한다. 반복 사이에 **호스트가 개입**(예: 대기 시간, 중간 검증, 진행 표시)하려면 `START 1`을 반복하는 쪽이 낫다 → [measurement_and_diagnosis.md](measurement_and_diagnosis.md) §3.
- **오류 처리**: `#I,…,ERR,…`를 받으면 즉시 `STOP`. 이후 `STATUS`로 `RUN=0`을 확인한다.

## 5. 타임아웃 권고값 (호스트)

| 상황 | 값(권고) | 근거 |
|---|---|---|
| 설정 명령 응답 | 1초 | 폴링이지만 유휴 시 즉시 응답 |
| `START` 후 첫 `#M`까지 | 15초 | 채널 안정화 10ms + AFE 초기화 + 첫 점 시간. **실기 측정 후 조정** |
| 측정 중 **무수신 허용 시간** | 130초 | 펌웨어 점당 가드 120초 + 여유. 초과 시 `STOP` 후 오류 처리 |
| 전체 측정 최대 시간 | 스윕 크기에서 산정 | §firmware_overview 4.5 (채널당 20~60초 추정) — 실기 확인 필요 |

## 6. 지연이 생기는 구간 (명령을 보내면 안 되는 때)
- `CHRONO` 시작 시 LPDAC 안정화 약 1.6초, `Amperometry_Measure`(DC 측정)
- `CALSHORT` 전체(채널당 수십 초) — 실행 중 `STOP`만 처리됨
- `BOOT` 이후(리셋)

측정 중에 보낼 수 있는 명령은 사실상 `STOP`과 `STATUS`다. 그 외 설정 명령은 다음 채널부터 적용되어 **결과가 섞일 수 있으므로** 측정 중에는 보내지 않는다.

## 7. 파싱 예시 (파이썬)

```python
def parse_line(line: str):
    line = line.strip()
    if not line.startswith("#"):
        return None
    kind = line[1:2]
    if kind == "I":
        _, ts, level, msg = line.split(",", 3)
        return ("I", int(ts), level, msg)
    f = line.split(",")
    if kind == "M":
        ts, ch, freq = int(f[1]), f[2], float(f[3])
        if len(f) == 13:      # FULL
            return ("M", ts, ch, freq, int(f[4]), int(f[5]), float(f[6]), float(f[7]),
                    float(f[8]), float(f[9]), float(f[10]), float(f[11]), f[12])
        ...                   # 9: COMPACT, 7: RAW
```
`float("nan")`은 파이썬에서 그대로 파싱된다. 숫자 변환 실패는 줄 하나를 버리고 로그만 남긴다 (UART 노이즈 대비).

## 8. 구현 현황 (3-R 완료, 2026-10-24)

기존 바이너리 프레임 설계를 아래와 같이 **텍스트 줄 프로토콜로 교체했다.** PC에서 Mock 펌웨어 기준 전체 테스트 82개 통과, **Pi 실기·실제 모듈 연동은 아직 미확인.**

| 모듈 | 내용 |
|---|---|
| `comm/protocol.py` | 레코드 파서(`#I/#H/#M/#C/#D/#T/#B`), `LineBuffer`(CR/LF/CRLF, 긴 줄 폐기), 명령 생성/검증(63자) |
| `comm/mock_device.py` | `MockFirmware`: 센서 0→1→2 순차 전체 스윕, AFE별 `#C`, 오류 후 사이클 재시도 등 펌웨어 동작 재현, 결함 주입 |
| `comm/uart_worker.py` | QThread 수신 루프, `lineReceived`, `send_line`, 자동 재연결(끊긴 동안의 명령은 폐기) |
| `comm/firmware_client.py` | 명령 직렬화·echo 대기, `ERR` 시 자동 `STOP`, watchdog, 모듈 재시작/연결 끊김 처리 |
| `tools/uart_demo.py` | `--probe`, `--send`, `--listen`, `--measure`, `--mock` |

### 8.1 Pi + PC(시리얼 터미널 프로그램) 검증 방법

> 터미널 프로그램은 **무엇을 써도 된다** (Tera Term, PuTTY, RealTerm 등 — 사용자는 Tera Term이 아닌 다른 프로그램 사용). 조건은 **115200 8N1, 흐름 제어 없음**, 그리고 보내는 줄 끝이 **CR, LF, CRLF 중 아무거나**(펌웨어/파서가 모두 허용)이면 된다.
```bash
python3 tools/uart_demo.py --port /dev/serial0 --listen 60                 # PC 가 보낸 줄을 원문+파싱 결과로 출력
python3 tools/uart_demo.py --port /dev/serial0 --send STATUS --listen 5    # PC 터미널에 STATUS 가 보이는지
```
Tera Term 에서 `#I,000001,STATUS,RUN=0 SWEEP=1000.00:1000.00:1 CHMASK=0x7 ...` 같은 줄을 입력하면 Pi 가 레코드로 파싱한다.
실제 모듈이 아니므로 `--probe` 는 Tera Term 이 직접 응답해야 `CMD ... OK` 가 된다 (응답이 없으면 `응답 시간 초과`).

### 8.2 이전 계획 (참고)


| 모듈 | 현재(가정) | 재작업 |
|---|---|---|
| `comm/protocol.py` | 바이너리 프레임, CRC16 | **줄 버퍼 + 레코드 파서** (`#I/#H/#M/#C/#D/#T/#B`)로 교체 |
| `comm/mock_device.py` | 프레임 기반 가상 장치 | **CLI를 흉내 내는 가상 펌웨어** (명령→echo, `START`→`#H/#C/#M…/CYCLE`, 오류/타임아웃 주입 가능) |
| `comm/transport.py` | `read()`→바이트 | 유지 가능 (줄 조립은 상위에서) |
| `comm/uart_worker.py` | 프레임 시그널 | `recordReceived(record)`로 변경, `send_line(text)` 추가, 줄 조립 포함 |
| `tests/test_protocol.py` | CRC/프레임 | 줄 파서·레코드 파서·재동기화(깨진 줄) 테스트로 교체 |
| `tools/uart_demo.py` | CMD_START 전송 | `STATUS`/`START 1` 데모 |

체크섬이 없으므로 **줄 단위 파싱 실패 시 해당 줄만 폐기**하고, 한 사이클의 정합성은 §4.3의 `CYCLE=n done`과 점 개수(`채널 수 × points`) 검사로 확인한다.
