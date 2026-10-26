#!/bin/bash
# 복제한 SD 카드의 첫 부팅에서 한 번 실행되어 장비마다 달라야 하는 것을 정한다 (deploy/prepare_image.sh 가 설치한다).
#   1) SSH 호스트 키가 없으면 새로 만든다 (이미지를 만들 때 지웠다 → 장비마다 다른 키)
#   2) 부팅 파티션의 nformare-device.txt 가 있으면 읽어 호스트 이름을 정한다 (PC 에서 SD 카드를 꽂아 편집할 수 있다)
#        hostname=nf-001
# 끝나면 /var/lib/nformare-firstboot.done 을 만들어 다시 실행되지 않는다.
set -u

SSH_DIR="${NFORMARE_SSH_DIR:-/etc/ssh}"
BOOT="${NFORMARE_BOOT_DIR:-/boot/firmware}"
DONE="${NFORMARE_FIRSTBOOT_DONE:-/var/lib/nformare-firstboot.done}"
HOSTS="${NFORMARE_HOSTS_FILE:-/etc/hosts}"
log() { echo "nformare-firstboot: $*"; }

[ -e "$DONE" ] && exit 0

# 1) SSH 호스트 키
if ! ls "$SSH_DIR"/ssh_host_*_key >/dev/null 2>&1; then
  log "SSH 호스트 키를 새로 만듭니다"
  if [ -z "${NFORMARE_TEST:-}" ]; then ssh-keygen -A || log "ssh-keygen 실패"; else : > "$SSH_DIR/ssh_host_ed25519_key"; fi
fi

# 2) 장치 이름 (선택)
DEV="$BOOT/nformare-device.txt"
if [ -f "$DEV" ]; then
  name="$(tr -d '\r' < "$DEV" | sed -n 's/^[[:space:]]*hostname[[:space:]]*=[[:space:]]*//p' | head -1 | tr -d '[:space:]')"
  if [ -n "$name" ] && echo "$name" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$'; then
    log "호스트 이름: $name"
    if [ -z "${NFORMARE_TEST:-}" ]; then
      hostnamectl set-hostname "$name" || log "hostnamectl 실패"
    fi
    if grep -q '^127\.0\.1\.1' "$HOSTS" 2>/dev/null; then
      sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$name/" "$HOSTS"
    else
      printf '127.0.1.1\t%s\n' "$name" >> "$HOSTS"
    fi
  elif [ -n "$name" ]; then
    log "호스트 이름이 올바르지 않아 건너뜁니다: $name (영문/숫자/하이픈, 63자 이하)"
  fi
fi

mkdir -p "$(dirname "$DONE")" && date -Is > "$DONE"
exit 0
