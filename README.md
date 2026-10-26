# RP3A-ADuCM355

Raspberry Pi 3A+ 에서 동작하는 **임피던스(EIS) 기반 진단키트 GUI**. UART(또는 BLE)로 연결된 ADuCM355 모듈에서 센서 3개 × 101점의 임피던스를 받아 Troponin 농도를 계산하고 결과를 보여 준다.

- GUI: PyQt5 (`QStackedWidget` 한 창), 터치 우선
- 통신: pyserial, 115200 bps (`/dev/serial0`), 별도 스레드(`UartWorker`)
- 화면: DSI 터치 패널 2종 — 세로 480x800 / 가로 1280x800 (자동 판별)
- 대상: Raspberry Pi OS Trixie, Python 3.13 (PC 개발은 Python 3.11 호환)

## 화면 흐름

로그인 → 측정(시료준비 → 혈액투입 → 세척 후 검증 → 결과) → 설정(Wi-Fi / 블루투스 / 센서) · 프로필 · 이력(세로)

| 화면 | 설명 |
|---|---|
| 측정 | 장비 상태(장비/키트/연결 아이콘), 단계 진행, 결과. 세로/가로 별도 레이아웃 |
| 설정 | Wi-Fi·블루투스 검색(이름 필터, 신호 세기 정렬), 센서 선택 |
| 센서 | 패치 센서(BLE) / 내장 센서(UART) 중 하나만 ON, STATUS 응답으로 연결 확인 |

## 실행

```bash
pip install -r requirements.txt   # PC. Pi 는 apt (python3-pyqt5 python3-serial python3-numpy python3-bleak)
python main.py                    # 실제 UART
python main.py --mock             # 가상 펌웨어 (모듈 없이 전체 흐름 확인)
python main.py -v                 # 진단 로그 (화면/창 크기 등)
python -m pytest tests -q         # 테스트
```

Windows 에서는 `run.bat` 메뉴로도 실행할 수 있다. 설정은 `config.ini`(`[display]`, `[measure]`, `[sensor]` 등).

## 폴더 구성

| 폴더 | 내용 |
|---|---|
| `app/` | 앱 본체. 안에 `config.py`·`display.py`·`app_window.py`(화면 전환, 센서 전환)와 아래 하위 패키지·리소스가 모두 있다 |
| `app/ui/` | 로그인·측정 대시보드·설정·센서 패널·가상 키보드·테마 |
| `app/comm/` | UART 프로토콜, 전송 계층(UART / BLE NUS), `UartWorker`, 가상 펌웨어 |
| `app/measure/` | 측정 흐름 제어(`MeasureController`), 단계, 결과 저장, 이력 |
| `app/models/` | Troponin 농도 모델 |
| `app/net/` | Wi-Fi / 블루투스 (nmcli, bluetoothctl, mock) |
| `app/auth/` | 로그인 인터페이스 (현재 스킵) |
| `app/assets/` `app/fonts/` `app/icon/` | 이미지, 폰트, 장비 상태 아이콘 |
| `app/update/` | 업데이트 확인·서명 검증·설치·되돌리기 ([docs/update.md](docs/update.md)) |
| `deploy/` | Pi 설치·부팅 로고·업데이트 끄기·이미지 복제 스크립트 |
| `tools/` | Pi 점검용(`uart_demo.py`, `net_check.py`)과 PC 에서만 쓰는 이미지·아이콘 생성 스크립트(`make_*.py`) |
| `tests/` | pytest |
| `docs/` | 상세 문서 |
| `Devices/` | 주변 장치 펌웨어 소스 (git 제외) |

## 문서

- 설계 개요: [DESIGN.md](DESIGN.md)
- Pi 설치·부팅 로고·자동 업데이트 끄기·SD 카드 복제: [docs/pi_setup.md](docs/pi_setup.md), [docs/boot_splash.md](docs/boot_splash.md)
- 측정 흐름·대시보드: [docs/measure_flow.md](docs/measure_flow.md), [docs/measure_dashboard.md](docs/measure_dashboard.md)
- 통신 프로토콜: [docs/uart_protocol.md](docs/uart_protocol.md)
- 모델: [docs/model_troponin_eis.md](docs/model_troponin_eis.md)
- 설정·네트워크·센서: [docs/settings_network.md](docs/settings_network.md)
- 배포 패키지·업데이트: [docs/update.md](docs/update.md)
- 작업 기록: `docs/worklog_*.md`

## Pi 에 올릴 때

`app/`(코드·리소스 전부), `deploy/` 와 `main.py` 를 복사한다. 예전 구조의 최상위 `ui/ comm/ …` 폴더가 Pi 에 남아 있으면 지운다. Pi 의 `config.ini`, `data/`, `results/` 는 덮어쓰지 않는다.

## 커밋 규칙

커밋 메시지는 `[V.x.xx.xxx] 내용` 형식 ([CLAUDE.md](CLAUDE.md)).
