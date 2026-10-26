# Raspi3A+ 진단키트 GUI — 단계별 구현 설계서

> Claude Code 작업용 설계서. 각 단계는 독립적으로 실행·검증 가능하며, 순서대로 진행한다.
> 단계 시작 시 해당 단계의 **작업 / 산출물 / 완료 기준**만 읽고 구현한다.

## 0. 개요

| 항목 | 내용 |
|---|---|
| 대상 HW | Raspberry Pi 3A+ (RAM 512MB, 경량 구성 필수), **DSI 디스플레이 + 터치 입력** |
| 디스플레이 | 2종: **가로 1280x800** / **세로 480x800**. **현재 범위는 가로만.** 세로는 디자인 시안 수령 후 별도 진행(🕒 보류) |
| 언어/GUI | Python 3, **PyQt5** (참고 코드 `refer/Vital_LogIn`이 PyQt5 5.15.11) |
| 통신 | UART (pyserial) — 진단키트 MCU와 송수신 |
| 서버 | 로그인 API (향후). 현재는 **스킵 버튼**으로 우회 |
| 화면 흐름 | 로그인 → (스킵 or 인증 성공) → 진단키트 측정 화면 |

### 0.1 참고 코드 분석 (`refer/Vital_LogIn`)

- `main.py`: QApplication, Fusion 스타일, 폰트·QSS 로딩 후 `LoginWindow` 표시
- `ui/login_window.py`: `LoginWindow(QWidget)` — 1280x800 고정, 역할 탭(일반/의료진/기관), ID/PW, 로그인 유지, 검증 후 `loginRequested(role, email, password, remember)` 시그널 발생 (서버 통신 없음)
- `ui/widgets.py`: `BrandLockup`, `RoleTabs`, `Field`
- `ui/theme.py`: 경로 상수(`ASSETS`는 `ui`의 상위 기준), 폰트·QSS 로더
- `assets/`(로고·배경·svg), `fonts/`(Pretendard) — 그대로 재사용
- 주의: 참고 폴더의 `.venv`, `.DS_Store`는 복사하지 않는다.
- **터치/세로 대응 시 수정이 필요한 부분**
  - `setFixedSize(1280x800)` → 프로파일 기반 크기로 변경 (세로는 480x800)
  - `CARD_WIDTH = 500` → 세로에서는 480px 화면을 넘으므로 화면폭 − 좌우 여백으로 축소
  - 카드 내부 여백 30, 입력/버튼 높이(44px)는 터치 기준(최소 48~56px)에 미달 → 프로파일 값으로 상향
  - 배경 `login-bg.jpg`: 세로 비율에서 cover 크롭이 심하므로 세로용 배경 별도 준비 또는 단색/그라디언트 대체
  - `Qt.PointingHandCursor`, 링크 hover 스타일은 터치에서 무의미 → 제거해도 무방, 대신 `:pressed` 스타일 추가
  - `QLabel` 링크("회원가입")·체크박스("로그인 유지")·"비밀번호 찾기"는 터치 영역이 작음 → 최소 48px 높이의 히트 영역 확보

### 0.2 설계 원칙

1. **UI와 통신 분리**: UART/서버 로직은 Qt 위젯을 import하지 않는다. 연결은 시그널/슬롯으로만 한다.
2. **UART는 별도 스레드**: GUI 스레드에서 `serial.read()` 블로킹 금지.
3. **화면 전환은 `QStackedWidget`** 한 곳에서 관리 (창 여러 개 생성 금지, 메모리 절약).
4. **서버 인증은 인터페이스 뒤에 숨김**: 지금은 Mock/스킵, 나중에 구현체만 교체.
5. **터치 우선(Touch-first)**: 마우스 hover/우클릭/더블클릭/툴팁에 의존하지 않는다. 모든 입력은 손가락으로 가능해야 한다.
6. **레이아웃은 프로파일로 분기**: 해상도를 코드에 하드코딩하지 않고 `DisplayProfile`에서 크기·간격·배치를 읽는다. 지금은 `landscape`만 구현하고, 세로는 나중에 프로파일만 추가하면 되도록 구조만 열어둔다.
7. **PC에서도 실행 가능**: UART 포트가 없으면 가상 장치(Mock)로 폴백해 Windows에서 개발·테스트.

### 0.3 확정이 필요한 항목 (가정값 → 구현 전 확인)

| # | 항목 | 가정값 (설계에 사용) |
|---|---|---|
| Q1 | UART 포트/속도 | `/dev/serial0`, 115200 8N1 (설정 파일로 변경 가능) |
| Q2 | UART 프로토콜 | ~~바이너리 프레임 가정~~ → **확정: 줄 단위 ASCII 텍스트** (`docs/uart_protocol.md`). 단계 3 재작업(3-R) 필요 |
| Q3 | 측정 항목/명령 | **확정**: `SWEEP/CHAN/VERB/START/STOP/STATUS/ENV/CALSTATUS` 등 (`docs/uart_protocol.md` §3). 진단 알고리즘·프리셋은 미정 (`docs/measurement_and_diagnosis.md` §9) |
| Q4 | 서버 로그인 API | URL, 메서드, 요청/응답 JSON, 토큰 방식 — 미정 (5단계에서 확정) |
| Q5 | Pi OS | **확정: Raspberry Pi OS Trixie (Debian 13), Python 3.13.5**. 64-bit 여부는 `uname -m`(aarch64)로 확인. PyQt5는 `apt install python3-pyqt5` 사용 |
| Q10 | 패키지 환경 | **venv 사용 안 함.** PC와 Pi를 같은 Python/패키지 버전으로 맞춤 (아래 0.4절) |
| Q6 | 디스플레이 선택 방식 | `config.ini [display] profile = auto/landscape/portrait`. auto는 화면 크기로 판별 |
| Q7 | 세로(480x800) 디자인 | **보류** — 사용자가 시안을 추후 제공. 시안 수령 전에는 세로 레이아웃을 구현하지 않음 |
| Q8 | 물리 키보드 유무 | 없다고 가정 → 앱 내장 가상 키보드 필요 (단계 2-B) |
| Q9 | 터치 컨트롤러/DSI 패널 모델 | 미정 → 6단계에서 회전·터치 보정 값 확정 |

---

### 0.4 환경 정책 (venv 없음)

- 가상환경을 만들지 않는다. PC·Pi 모두 시스템 Python에 패키지를 설치하고, **버전을 동일하게 맞춘다.**
- 기준 버전은 **Pi에서 먼저 확인**해 PC를 맞춘다:
  ```bash
  python3 --version
  python3 -c "from PyQt5.QtCore import PYQT_VERSION_STR as v; print(v)"
  python3 -c "import serial; print(serial.VERSION)"
  ```
- **확정 기준: Pi = Trixie, Python 3.13.5.** PC(Windows)는 현재 **Python 3.11.6**(사용자 확인)으로, Pi(3.13.5)와 마이너 버전이 다르지만 **그대로 사용한다.**
  - 대신 코드는 **Python 3.11 문법·표준 라이브러리 범위**로만 작성한다 (3.12/3.13 전용 기능 금지, 예: `type X = ...`, PEP 695 제네릭).
  - Pi(3.13)에서 제거된 표준 모듈(`cgi`, `telnetlib`, `imghdr` 등 PEP 594 대상)은 사용하지 않는다.
  - 두 환경에서 같은 코드가 돌아가는지 확인하는 것이 목적이므로, Pi 실기 확인(단계 3~6)을 생략하지 않는다.
- **Pi 실측 확정 버전**: Python 3.13.5 / PyQt5 **5.15.11** (`5.15.11+dfsg-2`) / pyserial **3.5**. 참고 프로젝트의 PyQt5 5.15.11과 동일하므로 UI 코드는 그대로 이식 가능하다. PC는 `pip install PyQt5==5.15.11 pyserial==3.5`로 맞춘다.
- 참고 프로젝트의 `.venv`는 Python 3.10이므로 사용하지 않는다.
- PC(Windows)에는 Pi와 같은 Python 마이너 버전을 설치하고 `pip install PyQt5==<Pi 버전> pyserial==<Pi 버전>`으로 맞춘다.
- `requirements.txt`는 위에서 확인한 버전으로 **정확히 고정(==)** 한다. Pi에는 pip가 아닌 apt로 설치하므로 이 파일은 PC용 기준표 역할이다.
- Pi에서 pip를 꼭 써야 하면 Trixie의 PEP 668 제한 때문에 `--break-system-packages`가 필요하다. 가능하면 apt 패키지만 사용하고 pip 추가 설치는 피한다.
- 의존성은 최소로 유지한다(PyQt5, pyserial, 표준 라이브러리). 서버 통신도 `QNetworkAccessManager`를 우선 검토해 추가 패키지를 줄인다.

### 0.5 펌웨어 분석 결과 (2026-10 반영)

`refer/ADuCM355_FW` 소스를 분석해 아래 문서를 작성했다. **구현 전에 반드시 읽는다.**

| 문서 | 내용 |
|---|---|
| [docs/firmware_overview.md](docs/firmware_overview.md) | 펌웨어 구조, 채널/설정 기본값, 보정, GUI 통합 시 주의할 동작(오류 시 STOP 필요 등) |
| [docs/uart_protocol.md](docs/uart_protocol.md) | UART 규격: 명령, `#I/#H/#M/#C/#D/#T/#B` 레코드 형식, 세션 시퀀스, 타임아웃 |
| [docs/measurement_and_diagnosis.md](docs/measurement_and_diagnosis.md) | **3회 반복 측정**, 집계/검증, 진단 인터페이스, 저장 형식, 열린 질문 |
| [docs/models_overview.md](docs/models_overview.md) | **진단 모델 2종(NT-proBNP, Troponin) 비교**, 단계 실행기 제안, Pi 실행 전략, 구현 단계(M-1~M-6) |
| [docs/model_troponin_eis.md](docs/model_troponin_eis.md) | Troponin 정량 코드 분석: T1/T2/T3+c0 프로토콜, 알고리즘, QC, 실행 확인 |
| [docs/pi_setup.md](docs/pi_setup.md) | **Raspberry Pi 초기 설정 한 번에**: 패키지, 시리얼, SSH/VNC, 화면 꺼짐, 부팅 스플래시, 점검 (`deploy/pi_setup.sh`) |
| [docs/boot_splash.md](docs/boot_splash.md) | **부팅 스플래시**: 무지개 화면 끄기, 라즈베리 로고를 nformare 로고로 교체(Plymouth), 설치/제거 스크립트, 확인 목록 |
| [docs/display_profiles.md](docs/display_profiles.md) | **가로/세로 자동 선택, 세로 로그인·키보드·측정(임시) 구현 현황**, 화면 여러 개일 때 지정 방법 |
| [docs/worklog_2026-10-24.md](docs/worklog_2026-10-24.md) | **2026-10-24 작업 기록**: 오늘 변경 사항, 파일 목록, Pi 업로드 대상, 미결 사항, 다음 작업 |
| [docs/worklog_2026-10-25.md](docs/worklog_2026-10-25.md) | **2026-10-25 작업 기록**: 설정(Wi-Fi/블루투스), UART 모니터링, 콘솔 정리, 단계 이름, 가로/세로 측정 화면, Pi 업로드 목록·실기 확인 현황·미결 사항 |
| [docs/worklog_2026-10-26.md](docs/worklog_2026-10-26.md) | **2026-10-26 작업 기록**: 부팅 로고(세로 270°), 자동 업데이트 끄기, **세로 화면 아래 잘림 원인(창이 화면보다 커짐)과 해결**, 설정 화면 필터/신호순 정렬, Troponin c0 = 첫 측정, 로그 영문화 |
| [docs/measure_dashboard.md](docs/measure_dashboard.md) | **가로 측정 화면(시안 반영)**: 환자 프로필·검사 결과·단계 카드·장비 상태·이력, 단위/참고 범위 설정, 시안과 다른 점 |
| [docs/uart_monitor.md](docs/uart_monitor.md) | **UART 모니터링 화면**: 측정 화면의 [모니터링] 버튼, 보냄/받음 실시간 표시, 필터·일시정지·저장, 읽는 법 |
| [docs/settings_network.md](docs/settings_network.md) | **설정 버튼 + 설정 화면(Wi-Fi / 블루투스 검색·등록)**: 동작, 구조, 명령, 한계, Pi 확인 목록 |
| [docs/measure_flow.md](docs/measure_flow.md) | **M-1 단계 실행기 + M-2 Troponin 포팅 구현 현황**, 설정, 저장, 화면 수정 안내 |
| [docs/model_nt_probnp_v18.md](docs/model_nt_probnp_v18.md) | NT-proBNP V18 분석: 6개 특징량, GBR+NN 게이트 구조, **특징 추출 코드 부재** |

핵심 영향:
- 펌웨어 통신은 **텍스트 줄 프로토콜**이다 → 단계 3(바이너리 프레임/CRC)은 **3-R로 재작업**.
- 진단 로직은 펌웨어에 없다 → GUI 쪽에서 구현. **모델은 NT-proBNP / Troponin 2종**이며 Troponin은 포팅 가능, NT-proBNP는 특징 추출 정의가 있어야 연동 가능. 측정은 모델별 **다단계 프로토콜**(Troponin: T1→T2(15분)→T3 + c0, 단계마다 3회)이다.
- 측정 화면(단계 4)은 4-a(오케스트레이터) → 4-b(UI) → 4-c(저장) → 4-d(진단)로 세분한다.

## 1. 목표 디렉터리 구조

```
Raspi3A+/
├─ main.py                  # 진입점
├─ requirements.txt
├─ config.ini               # 포트, baud, 서버 URL, SKIP_LOGIN 등
├─ DESIGN.md
├─ app/
│  ├─ app_window.py         # QStackedWidget 호스트, 화면 전환
│  ├─ display.py            # DisplayProfile (가로/세로 치수 토큰), 프로파일 선택
│  ├─ config.py             # config.ini 로더
│  └─ state.py              # 세션 정보(role, user, token)
├─ ui/                      # ← refer/Vital_LogIn/ui 이식
│  ├─ theme.py  theme.qss  widgets.py   # QSS는 프로파일 값을 치환해 로드
│  ├─ virtual_keyboard.py   # 앱 내장 터치 키보드 (영문/숫자/기호, 한글은 Q 참조)
│  ├─ login_window.py       # → LoginPage 로 수정 (스킵 버튼 추가)
│  └─ measure_page.py       # 측정 화면
├─ comm/
│  ├─ protocol.py           # 프레임 인코딩/디코딩, CRC (순수 파이썬)
│  ├─ uart_worker.py        # QThread/QObject: 수신 루프, 송신 큐
│  └─ mock_device.py        # 가상 진단키트 (테스트·PC 개발용)
├─ auth/
│  ├─ base.py               # AuthBackend 인터페이스
│  ├─ skip_auth.py          # 현재: 항상 성공
│  └─ server_auth.py        # 향후: 서버 로그인
├─ assets/  fonts/          # ← refer/Vital_LogIn 에서 복사
└─ tests/
   ├─ test_protocol.py
   └─ test_auth.py
```

---

## 2. 구현 단계

### 단계 1 — 프로젝트 골격 및 로그인 UI 이식

**작업**
0. (공통) `app/display.py` 작성 (**지금은 `landscape` 프로파일만 정의**, `portrait`는 보류 — `select_profile`이 portrait 요청 시 가로로 폴백하고 경고 로그):
   ```python
   @dataclass(frozen=True)
   class DisplayProfile:
       name: str            # "landscape" | "portrait"
       size: QSize          # 1280x800 | 480x800
       margin: int; spacing: int
       touch_min: int       # 최소 터치 높이 (예: 56)
       font_pt: dict        # 제목/본문/캡션 크기
   ```
   `select_profile(config, screen)`: `auto`이면 `screen.size()`의 가로>세로 여부로 판별.
1. 위 디렉터리 구조 생성. `refer/Vital_LogIn`의 `ui/`, `assets/`, `fonts/`를 복사 (`.venv`, `.DS_Store` 제외).
2. `ui/theme.py`의 `BASE` 경로가 새 구조(프로젝트 루트)를 가리키는지 확인·수정.
3. `main.py` 작성: 참고 `main.py`와 동일한 초기화(Fusion, 폰트, QSS) 후 `AppWindow` 표시.
4. `requirements.txt`: `PyQt5==5.15.11`, `pyserial==3.5` (Pi 실측값, 0.4절). venv는 만들지 않는다.
5. `config.ini` / `app/config.py`: `[app] skip_login=true`, `[uart] port, baudrate`, `[server] base_url`.

**산출물**: `python main.py` 실행 시 기존과 동일한 로그인 화면이 1280x800으로 표시.
**완료 기준**: 가로 프로파일에서 참고 프로젝트와 시각적으로 동일, 폰트(Pretendard) 정상 적용. `profile=portrait`는 아직 미지원(가로로 폴백).

---

### 단계 2 — 화면 전환 구조 + 스킵 버튼

**작업**
1. `app/app_window.py`: `AppWindow(QStackedWidget)` — `LoginPage`(index 0), `MeasurePage`(index 1) 등록. 페이지 이동은 `go_to(page)` 메서드 하나로 통일.
2. `LoginWindow` → `LoginPage`로 이름 변경, 최상위 창 속성(`setFixedSize`, `setWindowTitle`)은 `AppWindow`로 이동.
3. 로그인 카드 하단(회원가입 안내 아래)에 **「건너뛰기 (개발용)」 버튼** 추가 (`objectName="skipBtn"`, 보조 버튼 스타일을 `theme.qss`에 추가).
   - `LoginPage.skipRequested` 시그널 신설 → `AppWindow`가 받아 `MeasurePage`로 전환.
   - `config.ini`의 `skip_login=false`이면 버튼 숨김 (배포 시 제거 용이).
4. `auth/base.py`에 인터페이스 정의, `auth/skip_auth.py` 구현:
   ```python
   class AuthBackend(Protocol):
       def login(self, role: str, user_id: str, password: str) -> "AuthResult": ...
   @dataclass
   class AuthResult: ok: bool; token: str = ""; message: str = ""
   ```
5. `MeasurePage`는 이 단계에서 **빈 껍데기**(제목 + "← 로그인으로" 버튼)만 둔다.

6. **프로파일별 로그인 레이아웃** (`LoginPage`가 `DisplayProfile`을 받아 구성):
   - 가로 1280x800: 현 디자인(중앙 카드 500px). **← 이번 범위**
   - 🕒 세로 480x800 **(보류, 시안 수령 후 진행; 아래는 구현 시 참고용 초안)**: 카드 폭 = 480 − 좌우 여백(16~20px), 로고 → 역할 탭 → ID → PW → 옵션 → 로그인 → 스킵 순으로 세로 스택. 상단 로고 영역을 줄이고 하단 여백 확보.
   - 같은 위젯 트리를 쓰고 **크기/간격/폰트만 프로파일에서 주입**. 위젯 클래스를 둘로 복제하지 않는다.
7. 창 설정: 프로파일 해상도로 고정 (`setFixedSize`), Pi 실기에서는 `showFullScreen()`.

**산출물**: 스킵 클릭 → 측정 화면(빈 페이지) 전환, 돌아가기 동작. 가로 로그인 화면이 잘림 없이 표시.
**완료 기준**: 전환을 반복해도 메모리가 증가하지 않음(페이지 재생성 없음). PC에서 1280x800 확인. (`--profile portrait`는 보류)

---

### 단계 2-B — 터치 입력 대응 (가상 키보드 포함)

**작업**
1. 전역 설정: `QApplication.setAttribute(Qt.AA_SynthesizeMouseForUnhandledTouchEvents)` 확인, 커서 숨김(`Qt.BlankCursor`) 옵션.
2. 터치 타깃: 모든 버튼·탭·체크박스·링크의 최소 높이/폭 `profile.touch_min`(56px 권장, 최저 48px), 인접 타깃 간격 8px 이상.
3. 스타일: hover 의존 제거, `:pressed` 상태(색 변화)로 터치 피드백 제공. `Qt.PointingHandCursor` 제거.
4. **가상 키보드** (`ui/virtual_keyboard.py`) — 물리 키보드가 없으므로 ID/PW 입력에 필수:
   - `Field` 입력란 탭 시 화면 하단에 키보드 오버레이 표시, 외부 탭/완료 키로 닫기. 입력란이 키보드에 가려지면 카드를 위로 스크롤/이동.
   - 레이아웃: 영문 소문자/대문자(Shift), 숫자·기호 전환, 백스페이스, 이메일용 `@` `.` 상시 노출, 완료(Enter).
   - (세로 지원 시) 480px에서는 키 폭이 좁으므로 키 최소 폭 ≈ 40px, 높이 56px 확보.
   - 비밀번호 필드는 보기 토글과 무관하게 키 입력 팝업 미리보기 비활성화.
   - 구현 방식은 Qt Virtual Keyboard 모듈(Pi에서 패키지 유무 불확실)이 아닌 **직접 구현한 `QWidget` 키보드**를 기본안으로 한다 (의존성·플랫폼 독립).
   - 한글(두벌식) 구현 완료: `ui/hangul.py`(조합기) + `ui/virtual_keyboard.py`의 `ko` 레이어, `한/영` 키로 전환. 한글 입력 중 커서를 옮기거나 숫자·기호를 입력하면 조합이 끝난다.
5. 제스처: 스와이프·핀치 등은 사용하지 않는다. 길게 누르기 의존 기능 금지.

**산출물**: 마우스 없이 터치만으로 로그인 폼 입력 가능 (PC에서는 마우스 클릭으로 시뮬레이션).
**완료 기준**: 실기(DSI 터치)에서 ID/PW 입력, 키보드 열림/닫힘, 가려짐 없음. 오터치 없이 모든 버튼 동작.

---

### 단계 3 — UART 통신 계층 (UI 없이)

> ✅ **3-R 완료 (2026-10-24)**: 아래 본문의 바이너리 프레임 설계는 **폐기**되었고, 실제 펌웨어에 맞는 **텍스트 줄 프로토콜**로 교체 구현했다. 현황은 `docs/uart_protocol.md` §8. (PC/Mock 검증 완료, Pi 실기 확인 대기)

**작업**
1. `comm/protocol.py` (Qt 의존 없음)
   - `encode(cmd, payload) -> bytes`, `FrameParser.feed(bytes) -> list[Frame]`
   - 수신 바이트 스트림에서 STX/ETX·길이·CRC 검증, 잘린/깨진 프레임 재동기화
2. `comm/uart_worker.py`: `UartWorker(QObject)` + `QThread`
   - 시그널: `frameReceived(Frame)`, `connectionChanged(bool)`, `errorOccurred(str)`
   - 슬롯: `send(cmd, payload)` — 내부 큐에 넣고 쓰기 스레드에서 전송
   - 수신 루프: `serial.Serial(timeout=0.05)` 폴링, 포트 끊김 시 자동 재연결(1초 간격 백오프)
   - 종료: `stop()`에서 루프 종료 후 포트 close, `aboutToQuit`에 연결
3. `comm/mock_device.py`: 동일 인터페이스의 가상 장치 — 시작 명령을 받으면 일정 주기로 측정 진행/결과 프레임 생성. 포트 열기 실패 또는 `--mock` 옵션 시 사용.
4. `tests/test_protocol.py`: 정상 프레임, CRC 오류, 프레임 분할 수신, 노이즈 뒤 재동기화 케이스.

**산출물**: 콘솔 스크립트로 Mock과 송수신 왕복 확인.
**완료 기준**: `pytest tests/test_protocol.py` 통과. 실장비 연결 시 `/dev/serial0`에서 수신 프레임 로그 확인.

---

### 단계 4 — 진단키트 측정 화면

> ✅ **구현됨 (M-1, M-2, 2026-10-24)**: 단계 실행기와 측정 화면, Troponin numpy 포팅이 구현되어 가상 펌웨어로 PC에서 전체 흐름이 동작한다 → `docs/measure_flow.md`. 아래 본문은 초기 가정이다.

> ⚠️ **개정**: 측정은 **3회 반복 후 집계·진단** 흐름이다. 상태 머신, 데이터 모델, 세분 단계(4-a~4-d)는 `docs/measurement_and_diagnosis.md` §4, §8을 따른다. 아래 본문은 초기 가정이며 충돌 시 해당 문서가 우선한다.

**작업** (`ui/measure_page.py`, 로그인과 동일한 디자인 토큰 사용)
1. 레이아웃 — 프로파일별 배치 (같은 위젯, 컨테이너 방향만 다름):
   - **가로 1280x800**: 상단 헤더(사용자/역할, 장치 연결 LED, 로그아웃) · 좌측 측정 상태 패널 · 우측 결과 패널 · 하단 제어 버튼.
   - 🕒 **세로 480x800 (보류, 시안 수령 후 확정)**: 상단 헤더 · 측정 상태 패널 · 결과 패널이 **위→아래 한 열**로 스택 · 하단 고정 제어 버튼(전폭). 결과가 길면 `QScrollArea`(터치 드래그 스크롤, `QScroller` 사용).
   - 구현: `QBoxLayout` 방향을 프로파일에 따라 `LeftToRight`/`TopToBottom`으로 지정하고 패널 위젯 자체는 공유.
2. 상태 머신 `IDLE → READY → MEASURING → DONE / ERROR`:
   - 상태별로 버튼 활성/비활성 (시작/중지/재측정/저장).
   - 장치 미연결 시 시작 버튼 비활성 + 안내 문구.
3. `UartWorker`와 연결:
   - [시작] → `send(CMD_START, …)`; [중지] → `send(CMD_STOP)`
   - `frameReceived` → 진행률 바, 실시간 값, 최종 결과 표시
   - 응답 타임아웃(예: 3초) 시 ERROR 상태 + 재시도 버튼
4. 결과 표시 후 로컬 저장(CSV/JSON, `results/YYYYMMDD_HHMMSS.json`) — 서버 업로드는 후속 과제.
5. 터치: 제어 버튼 최소 높이 56px 이상(주요 버튼 72px 권장), 중요 동작(중지·삭제)은 오터치 방지를 위해 다른 버튼과 간격 확보. 확인 대화상자는 `QMessageBox` 대신 커스텀 오버레이(큰 버튼 2개) 사용. 숫자 입력이 필요하면 숫자 키패드 재사용.

**산출물**: Mock 장치로 시작→진행→결과 전체 플로우 동작.
**완료 기준**: 가로 화면 잘림·겹침 없이 표시, 측정 중 GUI 멈춤 없음, 케이블 분리/재연결 시 상태 표시 정상 복구.

---

### 단계 5 — 서버 로그인 연동

**작업**
1. Q4 확정 후 `auth/server_auth.py` 구현 (`requests` 또는 `QNetworkAccessManager`; 의존성 최소화를 위해 후자 검토).
2. 로그인은 **비동기**로 수행 (스레드 또는 Qt 네트워크). 진행 중에는 로그인 버튼 비활성 + 스피너, 타임아웃 10초.
3. `LoginPage.loginRequested` → `AppWindow`가 `AuthBackend.login()` 호출 →
   성공: `state`에 토큰·사용자 저장 후 `MeasurePage`로 전환 / 실패: `errorBanner`에 메시지 표시.
4. 오류 분류: 네트워크 불가, 401(자격 증명 오류), 5xx. 메시지는 사용자용 한글 문구로 변환.
5. "로그인 유지": 토큰을 파일에 저장 시 권한 `0600`. 평문 비밀번호는 저장 금지.
6. `config.ini`에서 `skip_login=false`로 두면 스킵 버튼 제거 → 정식 경로만 사용.

**산출물**: 테스트 서버(또는 Mock 서버)로 실제 로그인 성공/실패 흐름.
**완료 기준**: `tests/test_auth.py`(Mock 응답) 통과, 서버 오프라인에서도 앱이 멈추지 않음.

---

### 단계 6 — 라즈베리파이 배포 및 안정화

**작업**
0. **DSI 디스플레이/터치 설정**
   - DSI 패널 활성화는 `/boot/firmware/config.txt`의 `dtoverlay=`(패널 모델별, Q9) 또는 `display_auto_detect=1`.
   - **화면 회전**: 480x800은 패널 네이티브가 세로인 경우가 많고 1280x800은 가로다. 앱이 아닌 **OS/드라이버 레벨**에서 회전하고, 앱은 결과 해상도만 보고 프로파일을 선택한다 (`auto`). 방법: `cmdline.txt`의 `video=DSI-1:...,rotate=90`, 또는 Wayland/X 출력 회전 설정. 앱 내부 회전 코드는 넣지 않는다.
   - **터치 좌표 보정**: 화면을 회전하면 터치 축이 어긋난다. libinput 변환 행렬(`LIBINPUT_CALIBRATION_MATRIX`, udev 규칙)로 회전과 터치를 일치시킨다.
   - 실행 환경별 플랫폼 플러그인: 데스크톱(Wayland/X11) 위에서 실행 시 기본값, 데스크톱 없이 단독 실행(키오스크) 시 `QT_QPA_PLATFORM=eglfs` + `QT_QPA_EGLFS_ROTATION` 등 검토. 어느 쪽인지 정한 뒤 문서화.
   - 터치 확인: `libinput debug-events`로 이벤트 수신, 모서리 4곳 탭 정확도 검증.
1. Pi 설정: `raspi-config`에서 시리얼 콘솔 **비활성화**, 시리얼 하드웨어 **활성화**. `Bluetooth`와 UART 충돌 시 `dtoverlay=disable-bt` 검토. 사용자를 `dialout` 그룹에 추가.
2. 설치: `sudo apt install python3-pyqt5 python3-serial`, venv 없이 시스템 Python으로 `python3 main.py` 실행 (0.4절 버전 일치 확인).
3. (Trixie 데스크톱은 Wayland/labwc 기본 — Qt는 `QT_QPA_PLATFORM=wayland`/`xcb` 중 동작하는 쪽으로 확인.) 전체화면/키오스크: `showFullScreen()`, 커서 숨김, 화면 보호기·절전(DPMS) 비활성화 또는 터치 시 복귀. 1280x800 가로 실기 확인. 480x800 세로 확인과 `auto` 판별 검증은 세로 지원 시 수행.
4. 자동 시작: `systemd` 서비스(`Environment=QT_QPA_PLATFORM=...`는 환경에 맞게) 또는 autostart 항목.
5. 성능: 3A+는 RAM 512MB — 배경 이미지를 목표 해상도로 미리 축소, `paintEvent`마다 스케일링하지 않도록 캐시(현재 참고 코드는 매 repaint마다 `scaled` 수행).
6. 로깅: `logging` + 회전 파일 로그(UART 송수신 hex, 오류), 예외 훅으로 미처리 예외 기록.

**산출물**: 부팅 → 자동 실행 → 로그인(또는 스킵) → 측정까지 터치만으로 동작 (가로 디스플레이 기준).
**완료 기준**: 24시간 연속 구동에서 메모리 누수·UART 끊김 복구 확인.

---

## 3. 단계별 Claude Code 지시 예시

```
DESIGN.md 의 "단계 N" 만 구현해줘. 다른 단계는 건드리지 말고,
완료 기준을 직접 실행해서 확인한 결과를 알려줘.
```

권장 순서: 1 → 2 → 2-B → 3 → 4 → 5 → 6. (2-B는 서버 로그인 입력 전에 반드시 필요)
단계 1~2만 끝나도(스킵 사용 시 키보드 불필요) "시작 시 로그인 화면 → 스킵 → 측정 화면" 요구사항은 충족된다.

## 3.1 세로(480x800) 지원 — 로그인 구현 완료, 측정 화면은 임시 배치

> ✅ 2026-10-24: 프로파일 자동 선택, 세로 로그인(시안 기준), 세로 터치 키보드, 측정 화면 **임시** 배치를 구현했다 → `docs/display_profiles.md`. 아래는 당초 보류 계획(참고)이다.

0. (준비됨) 세로 로그인 위쪽 이미지 `assets/login-hero-photo.png` — 가로 화면 사진(`login-bg.jpg`)을 두 사람·장비 중심으로 크롭해 480x420 @2x(960x840)로 만들고 아래쪽을 투명하게 페이드한 것 (`tools/make_login_photo_portrait.py`로 재생성, 화면 맨 위에 붙여 표시). 일러스트 버전은 `tools/make_login_hero.py`로 다시 만들 수 있다. 시안: 위쪽 빈 공간 → 헤드라인 문구 → 역할 탭 → ID/PW → 로그인 → 로고
1. `DisplayProfile`에 `portrait` 추가, `select_profile` 폴백 제거
2. 로그인 페이지 세로 배치 (카드 폭, 여백, 배경)
3. 측정 화면 세로 배치 (단일 열 + 스크롤)
4. 가상 키보드 세로 키 크기 조정
5. DSI 세로 패널 회전·터치 보정 실기 확인

## 4. 리스크

| 리스크 | 대응 |
|---|---|
| UART 프로토콜 사양 미확정 | `protocol.py`를 격리하고 Mock으로 UI 먼저 개발 |
| Pi 3A+ 메모리 부족 | 페이지 단일 생성, 이미지 캐시/축소, 불필요한 폰트 제외 (Bold/Medium만 등) |
| PyQt5의 Pi 설치 난이도 | pip 대신 apt 패키지 사용 |
| PC·Pi 버전 불일치 | Pi 버전을 기준으로 PC를 맞추고 `requirements.txt`에 `==` 고정 |
| (보류) 세로 480px UI 공간 부족 | 시안 수령 후 프로파일 추가, 지금은 구조(프로파일 분리)만 확보 |
| 물리 키보드 없음 → 입력 불가 | 앱 내장 가상 키보드(단계 2-B) |
| 회전 후 터치 축 어긋남 | OS 레벨 회전 + libinput 보정 행렬, 앱은 회전하지 않음 |
| 세로 시안 미수령 | 세로 구현 보류, 가로 우선 완성 |
| 서버 API 변경 | `AuthBackend` 인터페이스로 UI 영향 차단 |
