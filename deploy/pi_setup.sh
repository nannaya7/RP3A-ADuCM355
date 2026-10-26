#!/bin/bash
# nformare 진단 장비 — Raspberry Pi 초기 설정 (한 번에)  [Raspberry Pi OS Trixie 기준]
#
#   bash deploy/pi_setup.sh --dry-run          # 무엇을 할지만 출력 (아무것도 바꾸지 않음) ← 먼저 이것부터
#   sudo bash deploy/pi_setup.sh               # 설정 실행 (필요하면 스스로 sudo 로 다시 실행)
#   sudo bash deploy/pi_setup.sh --uninstall-splash   # 스플래시만 원래대로
#
# 단계(이름): apt, serial, interfaces, display, time, bootfiles, splash, app, check
#   apt         필요한 패키지 설치 (PyQt5, pyserial, numpy, 터치/한글 표시용 Qt 플러그인, picocom …)
#   serial      UART 켜기(시리얼 콘솔은 끄기), dialout 그룹, (선택) 블루투스 끄기
#   interfaces  SSH, VNC 켜기
#   display     화면 꺼짐(블랭킹) 방지, (선택) DSI overlay / HDMI 끄기
#   time        (선택) 시간대, 호스트 이름, 시간 동기화 확인
#   bootfiles   위에서 모인 config.txt / cmdline.txt 변경을 한 번에 안전하게 적용 (백업 포함)
#   splash      무지개 화면 끄기 + nformare 부팅 스플래시 (deploy/install_splash.sh)
#   app         results 폴더, config.ini 점검
#   check       설치 확인: 패키지 버전, 시리얼 포트, 가상 펌웨어로 앱 자체 시험
#
# 옵션:
#   --dry-run                 아무것도 바꾸지 않고 할 일만 출력
#   --skip STEP               그 단계를 건너뜀 (여러 번 가능)  예: --skip splash --skip apt
#   --upgrade                 apt upgrade 까지 수행 (오래 걸림)
#   --disable-bt              블루투스를 꺼서 안정적인 UART(PL011)를 /dev/serial0 로 쓴다 (글자가 깨질 때)
#   --dsi-overlay LINE        config.txt 에 넣을 DSI 패널 overlay 줄 (여러 번 가능)
#                             예: --dsi-overlay "dtoverlay=vc4-kms-dsi-waveshare-panel-v2,10_1_inch_a"
#   --disable-hdmi            cmdline.txt 에 video=HDMI-A-1:d 추가 (HDMI 출력 끄기, DSI 만 쓸 때)
#   --config-line LINE        config.txt 에 줄 추가 (여러 번 가능)
#   --cmdline-token TOKEN     cmdline.txt 에 항목 추가 (여러 번 가능). 예: "video=DSI-1:800x1280@60,rotate=90"
#   --timezone TZ             시간대 설정. 예: Asia/Seoul
#   --hostname NAME           호스트 이름 설정
#   --splash-for KIND         부팅 로고 방향을 장비 종류에 맞춘다: landscape (가로, 90도 돌린 로고) | portrait (세로, 270도)
#                             안 쓰면 테마 폴더의 logo.png(세로용). 가로 장비는 꼭 landscape 로 지정한다
#   --splash-rotate DEG       부팅 로고를 돌리지 않은 원본에서 시계 방향 0/90/180/270 도 돌려 설치 (--splash-for 보다 우선).
#                             방향이 안 맞으면 다른 각도로 다시 실행 (예: 90 → 270)
#   --keep-blanking           화면 꺼짐 설정을 건드리지 않음
#   --run-tests               check 단계에서 전체 테스트(pytest)도 실행 (python3-pytest 설치)
#   -h, --help
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
# 경로는 시험용으로 환경 변수로 바꿀 수 있다 (tests/test_pi_setup_script.py). 평소에는 건드릴 필요 없다.
BOOT="${NFORMARE_BOOT_DIR:-/boot/firmware}"
CMDLINE="$BOOT/cmdline.txt"
CONFIG="$BOOT/config.txt"
STATE="${NFORMARE_STATE_DIR:-/var/lib/nformare-setup}"
ALL_STEPS=(apt serial interfaces display time bootfiles splash app check)

DRY=0; UPGRADE=0; DISABLE_BT=0; DISABLE_HDMI=0; KEEP_BLANKING=0; RUN_TESTS=0; UNINSTALL_SPLASH=0
TIMEZONE=""; HOSTNAME_NEW=""; SPLASH_FOR=""; SPLASH_ROTATE=""
SKIP=(); CFG_LINES=(); CMD_TOKENS=()
NEED_REBOOT=0; WARNS=0; FAILED=0
declare -A RESULT

usage() { sed -n '2,38p' "$0"; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --skip) shift; [ $# -gt 0 ] || usage 1; SKIP+=("$1") ;;
    --upgrade) UPGRADE=1 ;;
    --disable-bt) DISABLE_BT=1 ;;
    --dsi-overlay) shift; [ $# -gt 0 ] || usage 1; CFG_LINES+=("$1") ;;
    --disable-hdmi) DISABLE_HDMI=1 ;;
    --config-line) shift; [ $# -gt 0 ] || usage 1; CFG_LINES+=("$1") ;;
    --cmdline-token) shift; [ $# -gt 0 ] || usage 1; CMD_TOKENS+=("$1") ;;
    --timezone) shift; [ $# -gt 0 ] || usage 1; TIMEZONE="$1" ;;
    --hostname) shift; [ $# -gt 0 ] || usage 1; HOSTNAME_NEW="$1" ;;
    --splash-for) shift; [ $# -gt 0 ] || usage 1; SPLASH_FOR="$1"
                  case "$SPLASH_FOR" in landscape|portrait) ;; *) echo "--splash-for 는 landscape 또는 portrait 만 쓸 수 있습니다" >&2; usage 1 ;; esac ;;
    --splash-rotate) shift; [ $# -gt 0 ] || usage 1; SPLASH_ROTATE="$1"
                     case "$SPLASH_ROTATE" in 0|90|180|270) ;; *) echo "--splash-rotate 는 0, 90, 180, 270 만 쓸 수 있습니다" >&2; usage 1 ;; esac ;;
    --keep-blanking) KEEP_BLANKING=1 ;;
    --run-tests) RUN_TESTS=1 ;;
    --uninstall-splash) UNINSTALL_SPLASH=1 ;;
    -h|--help) usage 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; usage 1 ;;
  esac
  shift
done

# ---- 도우미 -------------------------------------------------------------------
say()  { echo "$*"; }
warn() { echo "  [경고] $*"; WARNS=$((WARNS + 1)); }
run()  { if [ "$DRY" -eq 1 ]; then echo "  [dry-run] $*"; return 0; fi; echo "  \$ $*"; "$@"; }
skipped() { local s; for s in "${SKIP[@]:-}"; do [ "$s" = "$1" ] && return 0; done; return 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# 파일을 처음 한 번만 백업한다 (이미 있으면 덮어쓰지 않는다)
backup_once() {
  local f="$1"
  [ "$DRY" -eq 1 ] && { echo "  [dry-run] 백업(처음 한 번만): $f → $STATE/"; return 0; }
  mkdir -p "$STATE" && cp -n "$f" "$STATE/$(basename "$f").orig" 2>/dev/null
  return 0
}

# 이 도구를 실행한 사용자(= 앱을 쓸 계정). sudo 로 실행했으면 원래 사용자
target_user() {
  local u="${SUDO_USER:-}"
  [ -z "$u" ] && u="$(logname 2>/dev/null || true)"
  if [ -z "$u" ] || [ "$u" = "root" ]; then u="$(getent passwd 1000 2>/dev/null | cut -d: -f1)"; fi
  echo "${u:-$(id -un)}"
}

if [ "$DRY" -eq 0 ] && [ "$(id -u)" -ne 0 ] && [ -z "${NFORMARE_TEST:-}" ]; then
  exec sudo -E bash "$0" "$@"
fi
TARGET_USER="$(target_user)"

# ---- 스플래시만 되돌리기 ---------------------------------------------------------
if [ "$UNINSTALL_SPLASH" -eq 1 ]; then
  exec bash "$HERE/install_splash.sh" --uninstall $([ "$DRY" -eq 1 ] && echo --dry-run)
fi

# ---- 단계 -------------------------------------------------------------------
step_apt() {
  export DEBIAN_FRONTEND=noninteractive
  run apt-get update || return 1
  [ "$UPGRADE" -eq 1 ] && { run apt-get -y upgrade || warn "apt upgrade 실패"; }
  # 앱 필수: PyQt5(+svg 아이콘/체크 표시용 플러그인, wayland 플랫폼), pyserial, numpy(Troponin 계산)
  # 도구: picocom(시리얼 확인), wlr-randr(화면 정보)
  # 설정 화면: network-manager(nmcli, Wi-Fi), bluez(bluetoothctl, 블루투스), rfkill(차단 해제)
  local pkgs=(python3-pyqt5 python3-pyqt5.qtsvg libqt5svg5 qtwayland5 python3-serial python3-numpy python3-bleak picocom wlr-randr
              network-manager bluez rfkill)
  [ "$RUN_TESTS" -eq 1 ] && pkgs+=(python3-pytest)
  local failed=0 p
  for p in "${pkgs[@]}"; do
    run apt-get install -y "$p" || { warn "패키지 설치 실패: $p"; failed=1; }
  done
  # 블루투스 장치를 앱(일반 사용자)이 다루려면 bluetooth 그룹이 필요하다 (다시 로그인해야 적용)
  getent group bluetooth >/dev/null 2>&1 && { run usermod -aG bluetooth "$TARGET_USER" || warn "bluetooth 그룹 추가 실패($TARGET_USER)"; }
  return "$failed"
}

step_serial() {
  run raspi-config nonint do_serial_hw 0 || warn "시리얼 하드웨어 켜기 실패"      # 0 = 켜기
  run raspi-config nonint do_serial_cons 1 || warn "시리얼 콘솔 끄기 실패"        # 1 = 콘솔 끄기
  CFG_LINES+=("enable_uart=1")                                                    # raspi-config 가 못 했을 때를 대비해 한 번 더 보장
  if [ "$DISABLE_BT" -eq 1 ]; then
    CFG_LINES+=("dtoverlay=disable-bt")
    say "  블루투스를 꺼서 /dev/serial0 이 PL011 UART 를 쓰게 합니다 (재부팅 필요)"
  fi
  run usermod -aG dialout "$TARGET_USER" || { warn "dialout 그룹 추가 실패($TARGET_USER)"; return 1; }
  say "  사용자 '$TARGET_USER' 를 dialout 그룹에 추가합니다 (다시 로그인해야 적용)"
  NEED_REBOOT=1
}

step_interfaces() {
  run raspi-config nonint do_ssh 0 || warn "SSH 켜기 실패"
  run raspi-config nonint do_vnc 0 || warn "VNC 켜기 실패"
  say "  (VNC 는 화면이 연결되어 있어야 보입니다. DSI 패널이 켜진 상태에서 접속하세요)"
}

step_display() {
  if [ "$KEEP_BLANKING" -eq 0 ]; then
    run raspi-config nonint do_blanking 1 || warn "화면 꺼짐 방지 설정 실패 (수동: Screen Configuration → Screen Blanking)"
  fi
  if [ "$DISABLE_HDMI" -eq 1 ]; then
    CMD_TOKENS+=("video=HDMI-A-1:d")
    say "  HDMI 출력을 끕니다 (video=HDMI-A-1:d). DSI 만 쓰는 장비용. 재부팅 후 적용"
  fi
  NEED_REBOOT=1
}

step_time() {
  [ -n "$TIMEZONE" ] && { run timedatectl set-timezone "$TIMEZONE" || warn "시간대 설정 실패: $TIMEZONE"; }
  [ -n "$HOSTNAME_NEW" ] && { run hostnamectl set-hostname "$HOSTNAME_NEW" || warn "호스트 이름 설정 실패"; }
  if [ "$DRY" -eq 0 ] && have timedatectl; then
    local ntp; ntp="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo unknown)"
    say "  시간대: $(timedatectl show -p Timezone --value 2>/dev/null)   시간 동기화(NTP): $ntp"
    # Pi 에는 배터리 시계(RTC)가 없다 → 네트워크가 없으면 결과 파일의 시각이 틀릴 수 있다
    [ "$ntp" = "yes" ] || warn "시간이 네트워크와 동기화되지 않았습니다. 측정 결과 시각이 틀릴 수 있습니다 (RTC 없음)"
  fi
}

step_bootfiles() {
  if [ "${#CFG_LINES[@]}" -eq 0 ] && [ "${#CMD_TOKENS[@]}" -eq 0 ]; then
    say "  config.txt / cmdline.txt 에 추가할 내용이 없습니다"; return 0
  fi
  have python3 || { [ "$DRY" -eq 1 ] || { warn "python3 가 없습니다"; return 1; }; }
  backup_once "$CONFIG"; backup_once "$CMDLINE"
  local args=(--cmdline "$CMDLINE" --config "$CONFIG" --no-splash) x
  for x in "${CFG_LINES[@]:-}"; do [ -n "$x" ] && args+=(--config-line "$x"); done
  for x in "${CMD_TOKENS[@]:-}"; do [ -n "$x" ] && args+=(--cmdline-token "$x"); done
  [ "$DRY" -eq 1 ] && args+=(--dry-run)
  python3 "$HERE/patch_boot_files.py" "${args[@]}" || return 1
  NEED_REBOOT=1
}

step_splash() {
  [ -f "$HERE/install_splash.sh" ] || { warn "install_splash.sh 가 없습니다"; return 1; }
  local args=()
  [ "$DRY" -eq 1 ] && args+=(--dry-run)
  [ -n "$SPLASH_FOR" ] && args+=(--for "$SPLASH_FOR")
  [ -n "$SPLASH_ROTATE" ] && args+=(--rotate "$SPLASH_ROTATE")
  bash "$HERE/install_splash.sh" "${args[@]}" || return 1
  NEED_REBOOT=1
}

step_app() {
  [ -f "$ROOT/main.py" ] || { warn "프로젝트 폴더로 보이지 않습니다: $ROOT (main.py 없음)"; return 1; }
  run mkdir -p "$ROOT/results"
  run chown -R "$TARGET_USER:" "$ROOT/results" || warn "results 소유자 변경 실패"      # "사용자:" = 그 사용자의 로그인 그룹
  if [ -f "$ROOT/config.ini" ]; then
    say "  config.ini 의 주요 값:"
    grep -E '^(profile|screen|fullscreen|port|baudrate|mock|reaction_wait_s|skip_login)\s*=' "$ROOT/config.ini" | sed 's/^/    /' || true
    grep -qE '^profile\s*=\s*auto' "$ROOT/config.ini" || warn "config.ini 의 [display] profile 이 auto 가 아닙니다 (자동 선택을 쓰려면 profile = auto)"
  else
    warn "config.ini 가 없습니다. 기본값으로 동작합니다 (프로젝트에서 복사해 올리세요)"
  fi
}

step_check() {
  [ "$DRY" -eq 1 ] && { echo "  [dry-run] 설치 확인(패키지 버전, 시리얼 포트, 가상 펌웨어 자체 시험)을 실행합니다"; return 0; }
  local rc=0
  python3 - <<'PYEOF' || rc=1
import sys
print("  python", sys.version.split()[0])
for name in ("PyQt5.QtCore", "serial", "numpy"):
    try:
        m = __import__(name, fromlist=["x"])
        v = getattr(m, "PYQT_VERSION_STR", None) or getattr(m, "VERSION", None) or getattr(m, "__version__", "?")
        print(f"  {name.split('.')[0]:8s} {v}")
    except Exception as e:
        print(f"  {name}: 없음 ({e})")
        sys.exit(1)
PYEOF
  say "  /dev/serial0 → $(readlink -f /dev/serial0 2>/dev/null || echo '없음')"
  if have raspi-config; then
    say "  serial hw=$(raspi-config nonint get_serial_hw 2>/dev/null) (0=켜짐)  console=$(raspi-config nonint get_serial_cons 2>/dev/null) (1=꺼짐)"
  fi
  id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx dialout && say "  $TARGET_USER: dialout 그룹 ✔" || warn "$TARGET_USER 가 dialout 그룹이 아닙니다 (재로그인/재부팅 후 다시 확인)"
  # 화면 없이도 되는 앱 자체 시험: 가상 펌웨어로 3개 센서를 측정
  if [ -f "$ROOT/tools/uart_demo.py" ]; then
    local out
    out="$(sudo -u "$TARGET_USER" env QT_QPA_PLATFORM=offscreen python3 "$ROOT/tools/uart_demo.py" --mock --measure --points 4 2>&1 | tail -3)"
    if echo "$out" | grep -q "점 수"; then say "  앱 자체 시험(가상 펌웨어): ✔ $(echo "$out" | grep '점 수')"; else warn "앱 자체 시험 실패:"; echo "$out" | sed 's/^/    /'; rc=1; fi
  fi
  if [ "$RUN_TESTS" -eq 1 ]; then
    (cd "$ROOT" && sudo -u "$TARGET_USER" env QT_QPA_PLATFORM=offscreen python3 -m pytest tests -q -p no:cacheprovider 2>&1 | tail -5) || rc=1
  fi
  return "$rc"
}

# ---- 실행 -------------------------------------------------------------------
do_step() {
  local name="$1" fn="$2" desc="$3"
  if skipped "$name"; then RESULT[$name]="건너뜀"; return; fi
  echo; echo "=== [$name] $desc ==="
  if "$fn"; then RESULT[$name]="OK"; else RESULT[$name]="실패"; FAILED=1; fi
}

echo "nformare Raspberry Pi 초기 설정 $([ "$DRY" -eq 1 ] && echo '(dry-run: 아무것도 바꾸지 않음)')"
echo "  모델 : $([ -r /proc/device-tree/model ] && tr -d '\0' < /proc/device-tree/model || echo '알 수 없음 (Pi 가 아닌 환경?)')"
echo "  OS   : $(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-?}") / $(uname -m)"
echo "  프로젝트: $ROOT   사용자: $TARGET_USER"
if [ "$DRY" -eq 0 ] && [ -z "${NFORMARE_TEST:-}" ]; then
  . /etc/os-release 2>/dev/null
  [ "${VERSION_CODENAME:-}" = "trixie" ] || echo "  [경고] 이 스크립트는 Trixie 기준입니다 (현재: ${VERSION_CODENAME:-?}). 명령이 다를 수 있습니다."
  [ -d "$BOOT" ] || { echo "$BOOT 가 없습니다. Raspberry Pi OS 가 맞나요?" >&2; exit 1; }
fi

do_step apt        step_apt        "필요한 패키지 설치"
do_step serial     step_serial     "시리얼(UART) 설정"
do_step interfaces step_interfaces "SSH / VNC"
do_step display    step_display    "디스플레이"
do_step time       step_time       "시간/호스트 이름"
do_step bootfiles  step_bootfiles  "config.txt / cmdline.txt 변경 적용"
do_step splash     step_splash     "부팅 스플래시 (무지개 화면 끄기 + nformare 로고)"
do_step app        step_app        "앱 폴더 점검"
do_step check      step_check      "설치 확인"

echo; echo "=== 요약 ==="
for s in "${ALL_STEPS[@]}"; do printf "  %-11s %s\n" "$s" "${RESULT[$s]:-?}"; done
echo "  경고 $WARNS 건"
if [ "$DRY" -eq 1 ]; then
  echo; echo "dry-run 이었습니다. 실제로 적용하려면:  sudo bash deploy/pi_setup.sh [옵션]"
else
  [ "$NEED_REBOOT" -eq 1 ] && { echo; echo "재부팅하면 모두 적용됩니다:  sudo reboot"; }
  echo "되돌리기: 스플래시는 'sudo bash deploy/pi_setup.sh --uninstall-splash', 부팅 파일 원본은 $STATE/ 에 있습니다."
fi
[ "$FAILED" -eq 0 ]
