#!/bin/bash
# 부팅 스플래시 진단 테마를 켜고 끈다 (스플래시가 뒤집히거나 한쪽으로 쏠릴 때 원인을 찾는 용도).
#
#   sudo bash deploy/splash_debug.sh on     # 진단 테마 설치 (initramfs 다시 만듦, 1~2분) → sudo reboot
#   sudo bash deploy/splash_debug.sh off    # 원래 nformare 테마로 되돌림 → sudo reboot
#
# 진단 테마는 Plymouth 가 보고하는 화면 크기(W, H), 크기가 바뀐 횟수(N), 화면 가장자리 빨간 테두리, 가운데 십자,
# TOP-LEFT / BOTTOM-RIGHT 모서리 표시, 로고를 보여 준다. 부팅 중 두 번(무지개 대체 화면, 로고 화면) 사진을 찍어 보내 주세요.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/plymouth/nformare-debug"
THEMES="${NFORMARE_PLYMOUTH_DIR:-/usr/share/plymouth/themes}"
DEST="$THEMES/nformare-debug"

if [ "$(id -u)" -ne 0 ] && [ -z "${NFORMARE_TEST:-}" ]; then
  exec sudo -E bash "$0" "$@"
fi

case "${1:-}" in
  on)
    for f in nformare-debug.plymouth nformare-debug.script px.png logo.png tl.png br.png w.png h.png n.png \
             d0.png d1.png d2.png d3.png d4.png d5.png d6.png d7.png d8.png d9.png; do
      [ -f "$SRC/$f" ] || { echo "진단 테마 파일이 없습니다: $SRC/$f (deploy/ 폴더를 통째로 올렸나요?)" >&2; exit 1; }
    done
    install -d -m 0755 "$DEST"
    install -m 0644 "$SRC"/* "$DEST/"
    plymouth-set-default-theme -R nformare-debug
    echo "진단 테마를 켰습니다. 재부팅하세요:  sudo reboot"
    echo "끄기:  sudo bash $0 off"
    ;;
  off)
    plymouth-set-default-theme -R nformare
    rm -rf "$DEST"
    echo "nformare 테마로 되돌렸습니다. 재부팅하세요:  sudo reboot"
    ;;
  *)
    sed -n '2,9p' "$0"
    exit 1
    ;;
esac
