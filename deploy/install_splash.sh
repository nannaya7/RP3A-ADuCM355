#!/bin/bash
# nformare 부팅 스플래시 설치 / 제거 (Raspberry Pi OS Trixie, Plymouth)
#
#   sudo bash deploy/install_splash.sh --dry-run     # 무엇을 할지만 보여 준다 (아무것도 바꾸지 않음)
#   sudo bash deploy/install_splash.sh               # 설치 (그 뒤 재부팅)
#   sudo bash deploy/install_splash.sh --uninstall   # 원래대로 되돌리기
#   sudo bash deploy/install_splash.sh --for landscape   # 가로 장비(1280x800): 시계 방향 90도 돌린 로고 deploy/boot_logo_landscape_90.png (Pi 실기 확인)
#   sudo bash deploy/install_splash.sh --for portrait    # 세로 장비(480x800): 270도 돌린 로고 deploy/boot_logo_rot270.png
#   sudo bash deploy/install_splash.sh --logo FILE.png   # 직접 고른 PNG 를 로고로 (--for 보다 우선)
#   sudo bash deploy/install_splash.sh --rotate 90       # 돌리지 않은 로고(deploy/boot_logo_centered.png, 또는 --logo FILE)를
#                                                        # 시계 방향 0/90/180/270 도 돌려 설치 (--for 보다 우선). 방향이 안 맞으면 270 으로
#       스크립트(nformare.script)는 하나이고 화면 크기에 맞춰 알아서 배치한다. 장비마다 다른 것은 로고 이미지의 회전뿐이다.
#       --for / --logo 를 안 쓰면 테마 폴더의 logo.png(현재 세로용)를 쓴다.
#
# 하는 일: ① Plymouth 테마 설치 ② config.txt 에 disable_splash=1 (무지개 화면 끄기)
#          ③ cmdline.txt 에 quiet splash logo.nologo loglevel=3 ... 추가 ④ 기본 테마를 nformare 로
# 원본은 /var/lib/nformare-splash/ 에 한 번만 백업한다 (--uninstall 이 여기서 복원).
set -euo pipefail

THEME=nformare
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/plymouth/$THEME"
# 경로는 시험용으로 환경 변수로 바꿀 수 있다 (tests/test_pi_setup_script.py)
DEST="${NFORMARE_PLYMOUTH_DIR:-/usr/share/plymouth/themes}/$THEME"
BOOT="${NFORMARE_BOOT_DIR:-/boot/firmware}"
CMDLINE="$BOOT/cmdline.txt"
CONFIG="$BOOT/config.txt"
STATE="${NFORMARE_SPLASH_STATE:-/var/lib/nformare-splash}"
DRY=0
ACTION=install

LOGO=""      # 비우면 테마 폴더의 logo.png
ORIG_ARGS=("$@")   # sudo 로 다시 실행할 때 그대로 넘긴다

FOR=""       # landscape | portrait
ROTATE=""    # 0|90|180|270
usage() { sed -n '2,19p' "$0"; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --uninstall) ACTION=uninstall ;;
    --logo) shift; LOGO="${1:-}"; [ -n "$LOGO" ] || { echo "--logo 뒤에 PNG 파일을 적어 주세요" >&2; usage 1; } ;;
    --for) shift; FOR="${1:-}"
           case "$FOR" in landscape|portrait) ;; *) echo "--for 는 landscape 또는 portrait 만 쓸 수 있습니다" >&2; usage 1 ;; esac ;;
    --rotate) shift; ROTATE="${1:-}"
              case "$ROTATE" in 0|90|180|270) ;; *) echo "--rotate 는 0, 90, 180, 270 만 쓸 수 있습니다 (시계 방향)" >&2; usage 1 ;; esac ;;
    -h|--help) usage 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; usage 1 ;;
  esac
  shift
done
if [ -z "$LOGO" ] && [ -z "$ROTATE" ] && [ -n "$FOR" ]; then            # --for: 장비 종류에 맞는 로고 (--logo 가 있으면 그쪽이 우선)
  case "$FOR" in
    landscape) LOGO="$HERE/boot_logo_landscape_90.png" ;;
    portrait)  LOGO="$HERE/boot_logo_rot270.png" ;;
  esac
fi
if [ -n "$LOGO" ] && [ ! -f "$LOGO" ]; then
  echo "로고 파일이 없습니다: $LOGO" >&2
  exit 1
fi

run() { if [ "$DRY" -eq 1 ]; then echo "[dry-run] $*"; else "$@"; fi; }

if [ "$DRY" -eq 0 ] && [ "$(id -u)" -ne 0 ] && [ -z "${NFORMARE_TEST:-}" ]; then
  exec sudo -E bash "$0" "${ORIG_ARGS[@]}"
fi

need() { command -v "$1" >/dev/null 2>&1 || { echo "필요한 명령이 없습니다: $1" >&2; [ "$DRY" -eq 1 ] || exit 1; }; }
need plymouth-set-default-theme
need python3
for f in "$CMDLINE" "$CONFIG"; do
  [ -f "$f" ] || { echo "파일이 없습니다: $f (Raspberry Pi OS 가 맞나요?)" >&2; [ "$DRY" -eq 1 ] || exit 1; }
done

if [ -n "$ROTATE" ]; then                           # --rotate: 돌리지 않은 로고를 지금 돌려서 쓴다 (--for 보다 우선)
  BASE_LOGO="${LOGO:-$HERE/boot_logo_centered.png}"
  [ -f "$BASE_LOGO" ] || { echo "로고 파일이 없습니다: $BASE_LOGO" >&2; exit 1; }
  ROT_TMP="$(mktemp --suffix=.png)"
  trap 'rm -f "$ROT_TMP"' EXIT
  python3 "$HERE/rotate_logo.py" "$BASE_LOGO" "$ROTATE" "$ROT_TMP" \
    || { echo "로고를 돌리지 못했습니다 (python3-pyqt5 가 설치되어 있나요?)" >&2; exit 1; }
  LOGO="$ROT_TMP"
fi

if [ "$ACTION" = "install" ]; then
  for f in nformare.plymouth nformare.script logo.png; do
    [ -f "$SRC/$f" ] || { echo "테마 파일이 없습니다: $SRC/$f" >&2; exit 1; }
  done
  [ -n "$LOGO" ] && echo "로고: $LOGO (테마 폴더의 logo.png 대신 사용)"

  echo "== 1) 백업 (이미 있으면 덮어쓰지 않는다) =="
  run mkdir -p "$STATE"
  run cp -n "$CMDLINE" "$STATE/cmdline.txt.orig"
  run cp -n "$CONFIG"  "$STATE/config.txt.orig"
  if [ ! -f "$STATE/prev-theme" ]; then
    prev="$(plymouth-set-default-theme 2>/dev/null || echo pix)"
    [ "$DRY" -eq 1 ] && echo "[dry-run] 현재 테마(${prev:-pix}) 기록" || echo "${prev:-pix}" > "$STATE/prev-theme"
  fi

  echo "== 2) 테마 설치: $DEST =="
  run install -d -m 0755 "$DEST"
  run install -m 0644 "$SRC/nformare.plymouth" "$SRC/nformare.script" "$SRC/logo.png" "$DEST/"
  [ -z "$LOGO" ] || run install -m 0644 "$LOGO" "$DEST/logo.png"      # --logo: 지정한 파일을 로고로 덮어쓴다

  echo "== 3) 부팅 설정 파일 수정 =="
  if [ "$DRY" -eq 1 ]; then
    python3 "$HERE/patch_boot_files.py" --cmdline "$CMDLINE" --config "$CONFIG" --dry-run || true
  else
    python3 "$HERE/patch_boot_files.py" --cmdline "$CMDLINE" --config "$CONFIG"
  fi

  echo "== 4) 기본 테마를 $THEME 로 (initramfs 다시 만듭니다. 1~2분 걸릴 수 있음) =="
  run plymouth-set-default-theme -R "$THEME"

  echo
  echo "완료. 재부팅하면 적용됩니다:  sudo reboot"
  echo "재부팅 후에도 무지개 화면이 보이면:  bash $HERE/check_boot.sh"
  echo "되돌리기:  sudo bash $0 --uninstall"
else
  echo "== 되돌리기 =="
  [ -d "$STATE" ] || { echo "백업이 없습니다($STATE). 되돌릴 내용이 없습니다." >&2; exit 1; }
  [ -f "$STATE/cmdline.txt.orig" ] && run cp "$STATE/cmdline.txt.orig" "$CMDLINE"
  [ -f "$STATE/config.txt.orig" ]  && run cp "$STATE/config.txt.orig"  "$CONFIG"
  prev=pix
  [ -f "$STATE/prev-theme" ] && prev="$(cat "$STATE/prev-theme")"
  run plymouth-set-default-theme -R "${prev:-pix}"
  run rm -rf "$DEST"
  echo "완료. 재부팅하면 원래대로 돌아옵니다:  sudo reboot"
fi
