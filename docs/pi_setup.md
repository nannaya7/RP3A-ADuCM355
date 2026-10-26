# Raspberry Pi 초기 설정 (스크립트 한 번으로)

> 대상: Raspberry Pi 3A+ (RAM 512MB), Raspberry Pi OS **Trixie** (Debian 13, 64-bit), Python 3.13.5, DSI 터치 패널
> 스크립트: [`deploy/pi_setup.sh`](../deploy/pi_setup.sh) — 이 문서의 모든 설정을 한 번에 한다.
> 하는 일: 패키지 설치, 시리얼(UART), SSH/VNC, 화면 꺼짐 방지, 부팅 스플래시(무지개 화면 끄기 + nformare 로고), 앱 폴더 점검, 설치 확인.

> **검증 상태**: 스크립트는 PC에서 **가짜 명령(apt-get, raspi-config …)과 임시 부팅 폴더로 처음부터 끝까지 실행해** 명령 순서, 부팅 파일 변경, 반복 실행 결과, 되돌리기를 테스트했다(`tests/test_pi_setup_script.py` 10개, `tests/test_boot_patch.py` 24개). **실제 Pi에서는 아직 실행하지 않았다.** 처음에는 반드시 `--dry-run`부터 하고, 아래 §9 확인 목록으로 검증한다.

## 1. 한눈에 보기

```bash
# ① 프로젝트 폴더를 Pi에 올린 뒤 (FileZilla), Pi에서
cd ~/PyNFor
bash deploy/pi_setup.sh --dry-run                    # ② 할 일만 출력 (아무것도 안 바꿈)
sudo bash deploy/pi_setup.sh --timezone Asia/Seoul   # ③ 실제 설정
sudo reboot                                          # ④ 재부팅 (UART, 스플래시 적용)
# (선택) 설치 확인만 다시:  sudo bash deploy/pi_setup.sh --skip apt --skip serial --skip interfaces --skip display --skip time --skip bootfiles --skip splash --skip app
```
- **여러 번 실행해도 안전**하다(멱등). 이미 있는 항목은 중복하지 않고, 부팅 파일 원본은 처음 한 번만 백업한다.
- 한 단계가 실패해도 **나머지는 계속 진행**하고, 마지막에 단계별 결과(OK/실패/건너뜀)를 요약한다.

## 2. 시작 전: SD카드 준비 (Raspberry Pi Imager)

스크립트가 하지 않는 부분이다. 이미지를 쓸 때 정한다.

| 항목 | 권장 |
|---|---|
| OS | Raspberry Pi OS **(64-bit)**, Trixie 기반 데스크톱 |
| 호스트 이름 | 장비를 구분할 이름 (예: `nf-001`) — 나중에 `--hostname`으로도 바꿀 수 있다 |
| 사용자 | 앱을 실행할 계정 (현재 `huni`). **이 계정이 dialout 그룹에 추가된다** |
| 네트워크 | Wi-Fi(또는 유선). 처음 `apt` 설치에 인터넷이 필요하다 |
| SSH | 켜기 (스크립트도 켠다) |
| 시간대/로캘 | Asia/Seoul. Pi에는 **배터리 시계(RTC)가 없다** — 네트워크가 없으면 측정 결과의 시각이 틀릴 수 있다 |

## 3. 파일 올리기 (FileZilla)

올릴 것: `main.py`, `config.ini`(처음 한 번만), `app/`, `ui/`, `comm/`, `measure/`, `models/`, `auth/`, `assets/`, `fonts/`, `tools/`, **`deploy/`**
올리지 말 것: `refer/`, `tests/`(Pi에서 `--run-tests`를 쓰려면 올림), `docs/`, `results/`, `__pycache__/`
- Pi의 `config.ini`는 **덮어쓰지 않는다** (Pi 전용 값이 들어 있다). 자동 선택을 쓰려면 `[display] profile = auto`로 직접 바꾼다.
- 스크립트 파일은 **LF 줄바꿈**이어야 Pi에서 실행된다 (이 프로젝트의 파일은 이미 LF).

## 4. 실행 옵션

```
bash deploy/pi_setup.sh [옵션]
```
| 옵션 | 설명 |
|---|---|
| `--dry-run` | 아무것도 바꾸지 않고 할 일만 출력 (**먼저 이것부터**) |
| `--skip STEP` | 단계를 건너뜀 (여러 번 가능): `apt serial interfaces display time bootfiles splash app check` |
| `--upgrade` | `apt upgrade`까지 수행 (오래 걸림) |
| `--disable-bt` | 블루투스를 꺼서 안정적인 UART를 `/dev/serial0`에 쓴다 (글자가 깨질 때) |
| `--dsi-overlay LINE` | `config.txt`에 넣을 DSI 패널 overlay 줄 (여러 번 가능) |
| `--disable-hdmi` | `cmdline.txt`에 `video=HDMI-A-1:d` 추가 — HDMI를 끈다 (DSI만 쓸 때) |
| `--config-line LINE` | `config.txt`에 줄 추가 (여러 번 가능) |
| `--cmdline-token TOKEN` | `cmdline.txt`에 항목 추가 (여러 번 가능) — 예: `video=DSI-1:800x1280@60,rotate=90` |
| `--timezone TZ` | 시간대 (예: `Asia/Seoul`) |
| `--hostname NAME` | 호스트 이름 |
| `--splash-for KIND` | **부팅 로고 방향을 장비 종류에 맞춘다**: `landscape`(가로 1280x800, 90도 돌린 로고) \| `portrait`(세로 480x800, 270도). 안 쓰면 테마 폴더의 `logo.png`(세로용)가 설치되어 **가로 장비에서는 옆으로 눕는다** → 가로 장비는 꼭 지정 (§4-1) |
| `--keep-blanking` | 화면 꺼짐 설정을 건드리지 않음 |
| `--run-tests` | `check` 단계에서 전체 테스트(pytest)도 실행 (`python3-pytest` 설치, `tests/` 필요) |
| `--uninstall-splash` | 부팅 스플래시만 원래대로 |

### 패널별 예시
```bash
# 10.1인치 Waveshare DSI (가로 1280x800로 사용): 이미 확인된 overlay + 가로용 부팅 로고
sudo bash deploy/pi_setup.sh --timezone Asia/Seoul --disable-hdmi --splash-for landscape \
     --dsi-overlay "dtoverlay=vc4-kms-dsi-waveshare-panel-v2,10_1_inch_a"

# 480x800 세로 패널: 별도 DSI 설정(overlay)이 필요 없는 것으로 확인됨 → --dsi-overlay 를 주지 않는다
# (사용자가 다른 보드에서 확인한 사항. 이 Pi 에서는 아직 확인하지 않았다) + 세로용 부팅 로고
sudo bash deploy/pi_setup.sh --timezone Asia/Seoul --disable-hdmi --splash-for portrait
```
- 이미 `config.txt`에 같은 overlay 줄이 있으면 중복 추가하지 않는다(똑같은 줄 기준).
- **화면 회전**(세로 기본 패널을 가로로 쓰는 경우 등)은 OS 설정(Screen Configuration, `wlr-randr`)에서 하거나 `--cmdline-token "video=DSI-1:...,rotate=90"`를 쓴다. 어느 쪽이 맞는지는 패널별로 실기 확인이 필요하다.

## 4-1. 부팅 스플래시(로고) 설치 — 가로/세로 장비별 (2026-10-26)
부팅 스플래시 스크립트(`nformare.script`)는 **하나**이고 화면 크기에 맞춰 로고 크기·위치를 알아서 정한다(세로 82%, 가로 50%, 최대 640px, 화면 크기가 바뀌면 다시 배치). **장비마다 다른 것은 로고 이미지의 회전**뿐이다.

| 장비 | 설치 | 로고 파일 |
|---|---|---|
| 가로 (1280x800) | `--for landscape` (`pi_setup.sh` 에서는 `--splash-for landscape`) | `deploy/boot_logo_landscape_90.png` (시계 방향 90도 — **Pi 실기에서 맞는 것으로 확인**) |
| 세로 (480x800) | `--for portrait` (`--splash-for portrait`) | `deploy/boot_logo_rot270.png` (270도) |
| 직접 고른 이미지 | `--logo 파일.png` (`--for` 보다 우선) | 임의의 PNG |
| **각도를 직접 지정** | `--rotate 0\|90\|180\|270` (`pi_setup.sh` 에서는 `--splash-rotate`). `--for` 보다 우선 | 돌리지 않은 `deploy/boot_logo_centered.png` 를 **시계 방향**으로 Pi 에서 바로 돌려 설치 (PC 에서 로고를 다시 만들어 올릴 필요 없음) |

```bash
cd ~/PyNFor
sudo bash deploy/install_splash.sh --for landscape    # 스플래시만 (이미 pi_setup 을 끝낸 장비)
sudo reboot
# 확인: bash deploy/check_boot.sh      (disable_splash=1, Plymouth 테마 nformare)
```
- **방향 맞추기 (`--rotate`)**: 각도는 항상 돌리지 않은 원본 기준의 **시계 방향 절대값**이다. `--for landscape` 는 `--rotate 90`, `--for portrait` 는 `--rotate 270` 과 같은 결과다 (둘 다 Pi 실기에서 맞는 방향으로 확인했다). 다른 패널이라 방향이 안 맞으면 각도를 바꿔 다시 설치한다.
  ```bash
  sudo bash deploy/install_splash.sh --rotate 90 && sudo reboot      # 안 맞으면 270 → 180 → 0 순으로 시험
  ```
  Pi 에 `python3-pyqt5`(앱과 같은 것)가 있어야 한다. 90/270 으로 돌린 로고는 세로로 서므로 스크립트가 **화면의 짧은 변의 82%**(최대 640px)에 긴 변을 맞춘다 (가로 1280x800 이면 높이 800 의 82% ≈ 640px).- 로고만 바꿔 다시 설치해도 된다 (여러 번 실행해도 안전, 원본 백업은 처음 한 번만). 되돌리기: `sudo bash deploy/pi_setup.sh --uninstall-splash`.
- **올릴 파일**: `deploy/` 폴더 통째로 (`plymouth/`, `boot_logo_*.png` 포함).
- 뒤집힘/쏠림이 남으면 진단 테마: `sudo bash deploy/splash_debug.sh on` → 재부팅 → 두 단계 사진 → `... off`. 자세한 내용과 원인은 [boot_splash.md](boot_splash.md) §9.
- Plymouth 스크립트는 PC 에서 실행해 볼 수 없어 **Pi 실기에서만 확인된다**. 새 스크립트에 문제가 있으면 `deploy/plymouth/nformare_static.script.bak` 의 내용을 `nformare.script` 로 되돌리고 다시 설치한다.

## 5. 단계별로 하는 일

| 단계 | 하는 일 | 실제 명령 |
|---|---|---|
| **apt** | 패키지 설치 (§6) | `apt-get update`, `apt-get install -y …` (패키지 하나씩, 실패해도 계속) |
| **serial** | UART 켜기, **시리얼 콘솔 끄기**, `enable_uart=1`, dialout 그룹, (선택) 블루투스 끄기 | `raspi-config nonint do_serial_hw 0`, `do_serial_cons 1`, `usermod -aG dialout <사용자>` |
| **interfaces** | SSH, VNC 켜기 | `raspi-config nonint do_ssh 0`, `do_vnc 0` |
| **display** | 화면 꺼짐(블랭킹) 방지, (선택) HDMI 끄기 | `raspi-config nonint do_blanking 1` |
| **time** | (선택) 시간대/호스트 이름, **시간 동기화 상태 확인** | `timedatectl set-timezone`, `hostnamectl set-hostname` |
| **bootfiles** | 위 단계에서 모인 `config.txt`/`cmdline.txt` 변경을 **한 번에, 백업 후** 적용 | `deploy/patch_boot_files.py` |
| **splash** | `disable_splash=1`, `quiet splash logo.nologo loglevel=3 …`, nformare Plymouth 테마 | `deploy/install_splash.sh` ([boot_splash.md](boot_splash.md)) |
| **app** | `results/` 폴더 만들고 권한, `config.ini` 핵심 값 출력, `profile = auto` 아니면 경고 | |
| **check** | 설치 확인 (§7) | |

### 부팅 파일을 고치는 방식 (안전장치)
- `cmdline.txt`는 **반드시 한 줄**이어야 한다. 여러 줄이거나 비어 있으면 **아무것도 쓰지 않고 그 단계를 실패 처리**한다.
- 기존 항목의 **순서와 내용은 그대로** 두고 없는 것만 뒤에 붙인다. `video=HDMI-A-1:d`와 `video=DSI-1:…`처럼 여러 번 나올 수 있는 항목은 서로 덮어쓰지 않는다. 값을 바꾸는 항목은 `loglevel`, `vt.global_cursor_default`뿐이다.
- `config.txt`는 맨 끝에 덧붙이되, 마지막 섹션이 특정 모델용(`[pi5]` 등)이면 `[all]`을 먼저 붙여 모든 모델에 적용되게 한다.
- 원본은 `/var/lib/nformare-setup/`(부팅 파일)와 `/var/lib/nformare-splash/`(스플래시)에 **처음 한 번만** 백업된다.

## 6. 설치하는 패키지와 이유

| 패키지 | 이유 |
|---|---|
| `python3-pyqt5` | GUI (Pi 실측 5.15.11) |
| `python3-pyqt5.qtsvg`, `libqt5svg5` | 아이콘·체크 표시(SVG)를 그리는 Qt 플러그인 |
| `qtwayland5` | **Wayland(labwc) 데스크톱에서 Qt 앱이 뜨는 플랫폼 플러그인** (`QT_QPA_PLATFORM=wayland`) |
| `python3-serial` | UART 통신 (pyserial 3.5) |
| `python3-numpy` | **Troponin 계산**(`models/troponin.py`). *이전 설치 목록에 없던 것을 추가* |
| `picocom` | 시리얼 송수신 확인 |
| `network-manager`, `bluez`, `rfkill` | **설정 화면**의 Wi-Fi(`nmcli`) / 블루투스(`bluetoothctl`) 관리. 사용자를 `bluetooth` 그룹에 추가한다 (다시 로그인 후 적용) |
| `wlr-randr` | 화면 이름/해상도/회전 확인 (`screen = DSI-1` 지정에 필요) |
| `python3-pytest` | `--run-tests`일 때만 |

- **pandas, torch, scikit-learn은 설치하지 않는다.** 메모리(512MB)가 부족하고 앱이 쓰지 않는다(NT-proBNP는 가중치를 추출해 numpy로 실행할 계획). 테스트의 원본 대조(pandas)는 PC에서만 한다.
- `pip`는 쓰지 않는다 (Trixie는 시스템 파이썬에 pip 설치를 막는다 — PEP 668). venv도 쓰지 않는다 (PC와 버전을 맞추는 방침).

## 7. 설치 확인 (`check` 단계)과 수동 확인

`check`는 아래를 출력한다.
```
  python 3.13.5
  PyQt5    5.15.11
  serial   3.5
  numpy    <버전>
  /dev/serial0 → /dev/ttyS0
  serial hw=0 (0=켜짐)  console=1 (1=꺼짐)
  huni: dialout 그룹 ✔
  앱 자체 시험(가상 펌웨어): ✔ 점 수: {'CH0': 4, 'CH1': 4, 'CH2': 4}
```
- 마지막 줄은 **화면 없이** 가상 펌웨어로 센서 0→1→2를 측정하는 시험이다. SSH에서도 돌아간다.
- `--run-tests`를 주면 전체 테스트도 실행한다.
- **numpy 버전은 PC(2.4.5)와 다를 수 있다.** 출력된 값을 `requirements.txt`/문서에 기록해 두면 PC와 맞출 수 있다.

설정 후 수동으로 볼 것:
```bash
sudo raspi-config nonint get_serial_hw      # 0
sudo raspi-config nonint get_serial_cons    # 1
ls -l /dev/serial0
groups | tr ' ' '\n' | grep dialout         # (재로그인 후)
timedatectl                                  # System clock synchronized: yes
cat /boot/firmware/cmdline.txt               # 한 줄, quiet splash logo.nologo …
```

## 8. 되돌리기와 복구
| 상황 | 방법 |
|---|---|
| 스플래시만 되돌리기 | `sudo bash deploy/pi_setup.sh --uninstall-splash` 후 재부팅 |
| 부팅 파일을 설정 이전으로 | `/var/lib/nformare-setup/config.txt.orig`, `cmdline.txt.orig`를 `/boot/firmware/`로 복사 |
| **부팅이 안 됨** | SD카드를 PC에 꽂아 `cmdline.txt`를 백업 내용(**한 줄**)으로 되돌린다. 로그가 필요하면 `quiet`, `loglevel=3`을 임시로 뺀다 |
| 시리얼 콘솔을 다시 켜고 싶음 | `sudo raspi-config nonint do_serial_cons 0` |

## 9. 실기 확인 목록 (처음 실행 후)
1. `--dry-run` 출력에서 `cmdline.txt 이후`가 **한 줄**이고 기존 값(`root=PARTUUID=…`)이 보존되는가
2. 실제 실행 후 요약에 **실패** 단계가 없는가 (경고는 내용 확인)
3. 재부팅 후: 무지개 화면과 열매 로고가 안 나오는가, nformare 스플래시가 나오는가 ([boot_splash.md](boot_splash.md) §6). **로고가 뒤집히거나 눕거나 한쪽으로 쏠리면 §4-1 의 `--for landscape|portrait` 로 다시 설치**
4. `/dev/serial0`로 PC와 송수신 되는가 ([pi_uart_setup.md](pi_uart_setup.md))
5. VNC/SSH 접속, 화면이 꺼지지 않는가
6. `check` 단계가 모두 ✔인가

## 10. 이 스크립트가 하지 않는 것 (수동 또는 후속)
| 항목 | 상태 |
|---|---|
| **앱 자동 시작** (부팅 후 전체화면으로 바로 실행, 바탕화면/작업표시줄 숨김) | **다음 작업(6단계)** |
| 자동 업데이트·알림 끄기 | 별도 스크립트 [`deploy/disable_updates.sh`](../deploy/disable_updates.sh) — §12 |
| 시스템 가상 키보드(Squeekboard) 끄기 | 설정 앱에서 수동 (앱 내장 키보드를 쓰므로 끄는 것이 맞다). 끄는 정확한 명령은 이 Pi에서 확인하지 못해 스크립트에 넣지 않았다 |
| DSI 패널 overlay | **10.1인치 가로 패널만** `--dsi-overlay`가 필요하다. **480x800 세로 패널은 별도 설정이 필요 없다** (다른 보드에서 확인, 이 Pi는 미확인) |
| 화면 회전·터치 보정 | OS 설정에서 수동 (`Screen Configuration`, 필요하면 libinput 보정 행렬) |
| `config.ini` 값 변경 | 직접 편집 (스크립트는 값을 출력하고 경고만 한다) |
| SSH 키/비밀번호 정책, VNC 비밀번호, 방화벽 | 보안 정책에 맞춰 별도 설정 (현재 스크립트는 **켜기만** 한다) |
| 결과 파일(`results/`) 보관/삭제, 로그 정리, 디스크 용량 관리 | 미구현. 환자 데이터가 쌓이므로 정책이 필요하다 |
| 읽기 전용 파일시스템, 하드웨어 워치독 | 미구현 (장비 배포 단계에서 검토) |
| 서버 로그인용 인증서/네트워크 | 5단계(서버 연동)에서 |

## 11. 문제 해결
| 증상 | 확인 |
|---|---|
| `필요한 명령이 없습니다: plymouth-set-default-theme` | `sudo apt install plymouth plymouth-themes` 후 다시 실행 (`--skip apt`는 풀어도 된다) |
| `bootfiles` 단계 실패: "한 줄이어야…" | `cmdline.txt`가 여러 줄이다. 한 줄로 고친 뒤 다시 실행 (스크립트는 건드리지 않았다) |
| `check`: dialout 경고 | 정상이다. **다시 로그인(또는 재부팅)해야** 그룹이 적용된다 |
| `check`: 앱 자체 시험 실패 | 출력된 마지막 줄 오류를 본다. 보통 PyQt5/numpy 설치 문제 |
| `qt.qpa.xcb: could not connect to display` | SSH에서 실행한 것. [display_profiles.md](display_profiles.md) §7 (`QT_QPA_PLATFORM=wayland` 등) |
| `경고: 시간이 네트워크와 동기화되지 않았습니다` | 네트워크 연결 확인. 연결이 불가능한 환경이면 결과 시각을 신뢰할 수 없다 |
| `Trixie 기준입니다` 경고 | 다른 Debian 계열이면 `raspi-config` 항목이나 경로가 다를 수 있다 |

## 13. SD 카드를 이미지로 만들어 복제하기 (2026-10-26)
한 대를 끝까지 설정(`pi_setup.sh`, 앱, `config.ini`, 부팅 로고)한 뒤 그 SD 카드를 이미지(`.img`)로 만들어 다른 SD 카드에 굽는 방식이다. **그대로 복제하면 안 되는 정보**가 있어서 이미지를 만들기 직전에 `deploy/prepare_image.sh` 로 정리한다.

### 왜 정리해야 하나
| 그대로 복제하면 | 정리 방법 |
|---|---|
| 모든 장비가 **같은 SSH 호스트 키**를 가진다 (보안상 나쁨, 접속 시 경고) | 키를 지우고 복제본의 **첫 부팅에서 새로 만든다** |
| **환자 프로필·검사 결과**(개인정보)가 모든 복제본에 들어간다 | `data/`, `results/` 비움 |
| **Wi-Fi 비밀번호**가 모든 복제본에 들어간다 | 저장된 Wi-Fi 삭제 (`--keep-wifi` 로 남길 수 있음) |
| 블루투스 **페어링**이 복제된다 (패치 센서 하나에 여러 장비가 붙으려 함) | 페어링 삭제 (`--keep-bluetooth`) |
| 같은 `machine-id`, 터미널 기록, 로그 | 비움 / 삭제 |
| 호스트 이름이 모두 같다 | 부팅 파티션의 `nformare-device.txt` 로 장비마다 지정 (아래) |

`config.ini` 는 그대로 남는다 (두 가지 설정은 이미 장비 종류별 기본값을 가진다: `[display] profile = auto`, `[sensor] default`).

### 순서
1. **기준 Pi 를 끝까지 설정**하고 앱을 실제로 돌려 본다. `config.ini` 에는 장비마다 다른 값을 넣지 않는다 (`fullscreen = true`, `bottom_margin` 등 모든 장비 공통 값만). Pi 의 SD 카드는 **쓸 카드 중 가장 작은 용량**으로 만든다 (이미지를 더 작은 카드에 구울 수 없다).
2. **정리 (기준 Pi 에서 마지막에)**:
   ```bash
   cd ~/PyNFor
   bash deploy/prepare_image.sh --dry-run      # 무엇을 지울지 먼저 확인
   sudo bash deploy/prepare_image.sh           # 확인 질문에 yes
   sudo shutdown -h now
   ```
   `deploy/` 폴더를 통째로 올려야 한다 (`firstboot.sh`, `nformare-firstboot.service` 포함). 이 스크립트는 첫 부팅 서비스(`nformare-firstboot`)도 설치한다.
3. **이미지 만들기 (PC)**: SD 카드를 PC 에 꽂아 `.img` 로 읽는다 — Windows 는 Win32 Disk Imager 의 *Read*, Linux/Mac 은 `sudo dd if=/dev/sdX of=nformare-landscape-2026-10-26.img bs=4M status=progress`. 파일 이름에 **장비 종류(가로/세로)와 날짜**를 넣는다.
   - 카드 용량이 크면 이미지도 크다. Linux/WSL 에서 **PiShrink**(`pishrink.sh -a 이미지.img`)로 줄이면 더 작은 카드에도 굽히고, 첫 부팅 때 카드 크기에 맞게 파일 시스템이 자동으로 늘어난다.
4. **굽기**: Raspberry Pi Imager 의 *OS 선택 → 사용자 지정 이미지*, 또는 balenaEtcher 로 복제본 SD 카드에 쓴다.
5. **장비마다 마무리**:
   - (선택) 굽고 난 SD 카드의 **부팅 파티션**(PC 에서 `bootfs` 드라이브로 보인다)에 `nformare-device.txt` 파일을 만들고 `hostname=nf-001` 한 줄을 적는다. 첫 부팅에서 호스트 이름이 정해진다 (영문/숫자/하이픈, 63자 이하).
   - 켜서 설정 화면에서 **Wi-Fi 연결**, 패치 센서를 쓰면 **블루투스 등록**, 시간(인터넷으로 자동 맞춤)을 확인한다.
   - PC 에서 SSH 로 접속하면 호스트 키가 바뀌었다는 경고가 나온다 (정상). `ssh-keygen -R 장비주소` 로 이전 기록을 지우고 다시 접속한다.

### 주의
- **가로/세로 이미지는 따로 만든다.** 패널 overlay(`config.txt`), 부팅 로고 방향(`--for landscape|portrait`/`--rotate`), 화면 회전이 장비 종류마다 달라서, 기준 Pi 도 종류별로 한 대씩 설정해 이미지를 만든다. 앱 코드와 `config.ini` 의 나머지는 같다.
- `prepare_image.sh` 를 실행한 기준 Pi 는 SSH 키와 Wi-Fi 가 지워져 **원격 접속이 안 될 수 있다.** 다시 개발할 때는 이미지로 만든 뒤 그 카드로 부팅하거나, 이미지를 다시 구워 쓰고 수정이 끝나면 다시 `prepare_image.sh` 를 실행한다. **정리하기 전에 이미지를 따로 백업**해 두면 안전하다.
- 앱을 고친 뒤에는 **이미지를 새로 만들어야** 새 장비에 반영된다 (이미 나간 장비는 FileZilla 로 `app/ ui/ …` 를 올려 갱신). 이미지에 날짜/앱 버전을 이름으로 남긴다.
- 같은 PC 에 복제 SD 카드를 두 개 동시에 꽂아 두지 않는다 (PARTUUID 가 같아 PC 가 헷갈릴 수 있다).
- 검사 결과를 장비에서 PC 로 꺼낸 뒤에는 개인정보 관리 지침에 따라 보관/삭제한다 (이미지에는 들어가지 않는다).
- **시험**: 처음에는 만든 이미지를 **다른 SD 카드 한 장에 구워 부팅**해 확인한다 — 앱이 뜨는가, 호스트 이름, SSH 접속(새 호스트 키), `results/`·`data/` 가 비어 있는가, Wi-Fi 설정이 비어 있는가, 부팅 로고 방향. (이 절차는 PC 에서 스크립트 동작만 시험했고 **실제 Pi 와 이미지 구워 보기는 아직 하지 않았다.**)

## 12. 자동 업데이트·알림 끄기 (`deploy/disable_updates.sh`, 2026-10-26)

키오스크로 쓸 때 업데이트가 갑자기 돌거나 알림이 화면에 뜨지 않게 하는 **별도 스크립트**다. `pi_setup.sh` 에 포함되지 않으며 따로 실행한다.

```bash
sudo bash deploy/disable_updates.sh          # 끄기
sudo reboot
sudo bash deploy/disable_updates.sh --undo   # 되돌리기
```

| 하는 일 | 방법 |
|---|---|
| apt 자동 갱신/업그레이드 끄기 | `apt-daily`, `apt-daily-upgrade` 타이머, `unattended-upgrades`, `packagekit` 를 중지 + mask. `/etc/apt/apt.conf.d/99-nformare-no-auto` 로 주기 설정을 0 으로 |
| 업데이트·알림 자동 시작 끄기 | `/etc/xdg/autostart/` 에서 이름에 update / notif / packagekit / pkgcheck 가 들어간 항목을 사용자 `~/.config/autostart/` 에 `Hidden=true` 로 덮어 숨김 (패키지는 지우지 않음) |
| 화면 꺼짐 끄기 | `raspi-config nonint do_blanking 1` (`pi_setup.sh` 의 display 단계와 같음) |

- 여러 번 실행해도 안전하다. 수동 업데이트(`sudo apt update && sudo apt upgrade`)는 그대로 쓸 수 있다.
- 끄면 **보안 패치가 자동으로 들어오지 않는다.** 정기적으로 수동 업데이트를 하거나, 배포 전에 한 번 업데이트한 뒤 끈다.
- **실기 미확인**: PC 에서 실행해 보지 못했고, Trixie 데스크톱의 알림이 어느 autostart 항목/패널 플러그인인지 확인하지 못해 이름 패턴으로 찾는다. 재부팅 후에도 알림이 뜨면 화면 사진을 보고 대상을 추가한다.
- 확인: `systemctl list-timers | grep apt` 에 아무것도 안 나오면 정상.
