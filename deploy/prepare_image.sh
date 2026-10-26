#!/bin/bash
# SD 카드를 이미지로 만들어 복제하기 전에, 이 장비에만 있어야 하는 정보를 지운다 (기준이 되는 Pi 에서 마지막에 한 번 실행).
#
#   bash deploy/prepare_image.sh --dry-run     # 무엇을 지울지만 보여 준다 (아무것도 바꾸지 않음) ← 먼저 이것부터
#   sudo bash deploy/prepare_image.sh          # 지우고 첫 부팅 설정을 설치한다 (확인 질문에 yes)
#   sudo bash deploy/prepare_image.sh --yes    # 확인 질문 없이
#
# 지우는 것 (복제하면 모든 장비가 같은 값을 갖게 되거나, 개인정보가 들어 있는 것):
#   - 검사 결과 results/, 환자 프로필·센서 선택 data/            (config.ini 는 그대로 둔다)
#   - 저장된 Wi-Fi 접속 정보(비밀번호 포함)                        --keep-wifi 로 남길 수 있다
#   - 블루투스 페어링 정보                                         --keep-bluetooth 로 남길 수 있다
#   - SSH 호스트 키 (복제본마다 첫 부팅에서 새로 만든다), machine-id (부팅 때 새로 만들어진다)
#   - 터미널 명령 기록(.bash_history), 로그(journal), apt 캐시
# 설치하는 것: 첫 부팅 서비스 nformare-firstboot (SSH 키 재생성, 부팅 파티션의 nformare-device.txt 로 호스트 이름 설정)
#
# 끝나면 `sudo shutdown -h now` 로 끄고, SD 카드를 PC 에 꽂아 이미지로 만든다 (docs/pi_setup.md §13).
# ⚠️ 이 스크립트를 실행한 Pi 는 SSH 키·Wi-Fi 가 지워져 다음 부팅에서 접속 방법이 달라진다. 이미지를 만든 뒤에는 바로 쓰지 말고
#    복제본으로 시험한다.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 경로는 시험용으로 환경 변수로 바꿀 수 있다 (tests/test_pi_setup_script.py). 평소에는 건드릴 필요 없다.
ROOT="${NFORMARE_ROOT:-$(cd "$HERE/.." && pwd)}"
NM_DIR="${NFORMARE_NM_DIR:-/etc/NetworkManager/system-connections}"
BT_DIR="${NFORMARE_BT_DIR:-/var/lib/bluetooth}"
SSH_DIR="${NFORMARE_SSH_DIR:-/etc/ssh}"
MACHINE_ID="${NFORMARE_MACHINE_ID:-/etc/machine-id}"
SYSTEMD_DIR="${NFORMARE_SYSTEMD_DIR:-/etc/systemd/system}"
SBIN_DIR="${NFORMARE_SBIN_DIR:-/usr/local/sbin}"
DONE="${NFORMARE_FIRSTBOOT_DONE:-/var/lib/nformare-firstboot.done}"
HOMES="${NFORMARE_HOMES:-/home/* /root}"
DRY=0; YES=0; KEEP_WIFI=0; KEEP_BT=0

usage() { sed -n '2,22p' "$0"; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --yes) YES=1 ;;
    --keep-wifi) KEEP_WIFI=1 ;;
    --keep-bluetooth) KEEP_BT=1 ;;
    -h|--help) usage 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; usage 1 ;;
  esac
  shift
done

if [ "$DRY" -eq 0 ] && [ "$(id -u)" -ne 0 ] && [ -z "${NFORMARE_TEST:-}" ]; then
  exec sudo -E bash "$0" "$@"
fi

say() { echo "$*"; }
run() { if [ "$DRY" -eq 1 ]; then echo "  [dry-run] $*"; else echo "  \$ $*"; "$@"; fi; }
live() { [ -z "${NFORMARE_TEST:-}" ]; }          # 시험 중에는 systemctl / apt / journalctl 같은 시스템 명령을 부르지 않는다
have() { command -v "$1" >/dev/null 2>&1; }

[ -f "$ROOT/main.py" ] || { echo "프로젝트 폴더로 보이지 않습니다: $ROOT (main.py 없음)" >&2; exit 1; }
for f in firstboot.sh nformare-firstboot.service; do
  [ -f "$HERE/$f" ] || { echo "파일이 없습니다: $HERE/$f (deploy/ 폴더를 통째로 올렸나요?)" >&2; exit 1; }
done

if [ "$DRY" -eq 0 ] && [ "$YES" -eq 0 ]; then
  echo "이 Pi 의 검사 결과, 환자 프로필, Wi-Fi/블루투스 정보, SSH 키를 지우고 복제용으로 정리합니다."
  echo "되돌릴 수 없습니다. 계속하려면 yes 를 입력하세요."
  read -r ans < /dev/tty || ans=""
  [ "$ans" = "yes" ] || { echo "취소했습니다."; exit 1; }
fi

say "== 1) 앱 데이터 (results/, data/) — config.ini 는 그대로 =="
for d in "$ROOT/results" "$ROOT/data"; do
  if [ -d "$d" ]; then
    n=$(find "$d" -mindepth 1 2>/dev/null | wc -l)
    say "  $d : $n 개 항목"
    [ "$n" -gt 0 ] && run find "$d" -mindepth 1 -delete
  fi
done

say "== 2) 저장된 Wi-Fi 접속 정보 =="
if [ "$KEEP_WIFI" -eq 1 ]; then
  say "  (--keep-wifi: 남겨 둔다)"
elif [ -d "$NM_DIR" ]; then
  found=0
  for f in "$NM_DIR"/*.nmconnection; do
    [ -f "$f" ] || continue
    if grep -q '^type=wifi' "$f" 2>/dev/null; then found=1; run rm -f "$f"; fi
  done
  [ "$found" -eq 0 ] && say "  (저장된 Wi-Fi 없음)"
else
  say "  ($NM_DIR 없음)"
fi

say "== 3) 블루투스 페어링 정보 =="
if [ "$KEEP_BT" -eq 1 ]; then
  say "  (--keep-bluetooth: 남겨 둔다)"
elif [ -d "$BT_DIR" ]; then
  live && have systemctl && run systemctl stop bluetooth
  find "$BT_DIR" -mindepth 1 2>/dev/null | grep -q . && run find "$BT_DIR" -mindepth 1 -delete || say "  (페어링 정보 없음)"
else
  say "  ($BT_DIR 없음)"
fi

say "== 4) SSH 호스트 키 / machine-id (복제본마다 새로 만들어진다) =="
ls "$SSH_DIR"/ssh_host_* >/dev/null 2>&1 && run rm -f "$SSH_DIR"/ssh_host_* || say "  (SSH 호스트 키 없음)"
if [ -e "$MACHINE_ID" ]; then
  if [ "$DRY" -eq 1 ]; then say "  [dry-run] machine-id 비우기: $MACHINE_ID"; else : > "$MACHINE_ID"; say "  machine-id 를 비웠습니다 (다음 부팅에서 새로 만들어짐)"; fi
fi

say "== 5) 첫 부팅 서비스 설치 =="
run install -d -m 0755 "$SBIN_DIR" "$SYSTEMD_DIR"
run install -m 0755 "$HERE/firstboot.sh" "$SBIN_DIR/nformare-firstboot.sh"
run install -m 0644 "$HERE/nformare-firstboot.service" "$SYSTEMD_DIR/nformare-firstboot.service"
if live && have systemctl; then
  run systemctl daemon-reload
  run systemctl enable nformare-firstboot.service
else
  say "  (systemctl enable 은 실제 Pi 에서만 실행)"
fi
[ -e "$DONE" ] && run rm -f "$DONE"                 # 복제본의 첫 부팅에서 다시 실행되도록

say "== 6) 터미널 기록 / 로그 / 캐시 =="
for h in $HOMES; do
  [ -d "$h" ] || continue
  for hf in "$h/.bash_history" "$h/.python_history" "$h/.lesshst"; do
    [ -e "$hf" ] && run rm -f "$hf"
  done
done
if live; then
  have apt-get && run apt-get clean
  have journalctl && { run journalctl --rotate; run journalctl --vacuum-time=1s; }
fi
[ "$DRY" -eq 1 ] || sync

echo
if [ "$DRY" -eq 1 ]; then
  echo "dry-run 이었습니다. 아무것도 바꾸지 않았습니다."
else
  echo "정리했습니다. 이제 끄고 SD 카드를 이미지로 만드세요:  sudo shutdown -h now"
  echo "(이 Pi 는 SSH 키가 없는 상태입니다. 다시 켜면 첫 부팅 서비스가 새 키를 만듭니다.)"
fi
