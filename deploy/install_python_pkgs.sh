#!/bin/bash
# nformare 진단 장비 — 앱이 쓰는 패키지만 설치 (apt)  [Raspberry Pi OS Trixie 기준]
#
#   sudo bash deploy/install_python_pkgs.sh             # 설치
#   bash deploy/install_python_pkgs.sh --dry-run        # 설치할 목록만 출력 (아무것도 바꾸지 않음)
#   sudo bash deploy/install_python_pkgs.sh --pytest    # 테스트용 python3-pytest 도 설치
#
# Trixie 의 파이썬은 pip 전역 설치가 막혀 있어(PEP 668) apt 의 python3-* 패키지로 설치한다.
# 시스템 설정(UART, 부팅 로고 등)은 건드리지 않는다. 그건 deploy/pi_setup.sh.
# 패키지 목록은 pi_setup.sh 의 apt 단계와 같다.
set -uo pipefail

DRY=0; PYTEST=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --pytest)  PYTEST=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "알 수 없는 옵션: $a" >&2; exit 2 ;;
  esac
done

# 앱에 필요한 것: 화면(PyQt5 + svg 아이콘/체크 표시 + wayland), UART(pyserial), 계산(numpy),
# NT-proBNP 피팅(scipy), 패치 센서 BLE(bleak), 업데이트 서명 확인(cryptography)
# 도구: picocom(시리얼 확인), wlr-randr(화면 정보)
# 설정 화면: network-manager(nmcli, Wi-Fi), bluez(bluetoothctl, 블루투스), rfkill(차단 해제)
PKGS=(python3-pyqt5 python3-pyqt5.qtsvg libqt5svg5 qtwayland5 python3-serial python3-numpy python3-scipy python3-bleak python3-cryptography
      picocom wlr-randr network-manager bluez rfkill)
[ "$PYTEST" -eq 1 ] && PKGS+=(python3-pytest)

echo "설치할 패키지: ${PKGS[*]}"
[ "$DRY" -eq 1 ] && { echo "(--dry-run: 설치하지 않음)"; exit 0; }

if [ "$(id -u)" -ne 0 ]; then
  exec sudo bash "$0" "$@"
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update || { echo "apt-get update 실패" >&2; exit 1; }
failed=0
for p in "${PKGS[@]}"; do
  apt-get install -y "$p" || { echo "패키지 설치 실패: $p" >&2; failed=1; }
done

# 블루투스 장치를 앱(일반 사용자)이 다루려면 bluetooth 그룹이 필요하다 (다시 로그인해야 적용)
if [ -n "${SUDO_USER:-}" ] && getent group bluetooth >/dev/null 2>&1; then
  usermod -aG bluetooth "$SUDO_USER" || echo "bluetooth 그룹 추가 실패($SUDO_USER)" >&2
fi

echo "---- 설치 확인 ----"
python3 - <<'PY'
import importlib
for name in ("PyQt5.QtCore", "PyQt5.QtSvg", "serial", "numpy", "scipy", "bleak", "cryptography"):
    try:
        m = importlib.import_module(name)
        print(f"  OK   {name:14s} {getattr(m, 'PYQT_VERSION_STR', getattr(m, '__version__', ''))}")
    except Exception as e:
        print(f"  없음 {name:14s} ({e.__class__.__name__})")
PY
exit "$failed"
