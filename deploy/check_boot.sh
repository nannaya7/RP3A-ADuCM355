#!/bin/bash
# 부팅 스플래시 설정 점검 (읽기 전용 — 아무것도 바꾸지 않는다)
#
#   bash deploy/check_boot.sh
#
# "무지개 화면이 아직 나온다" 같은 문제를 찾을 때 쓴다. 가장 중요한 줄은 [3] 의 vcgencmd 결과다:
#   disable_splash=1 이 보이면 펌웨어가 설정을 실제로 읽었다는 뜻이다.
# 환경 변수 NFORMARE_BOOT_DIR 로 부팅 폴더를 바꿀 수 있다 (시험용, 기본 /boot/firmware).
BOOT="${NFORMARE_BOOT_DIR:-/boot/firmware}"
CFG="$BOOT/config.txt"
CMD="$BOOT/cmdline.txt"
problems=0

echo "[1] config.txt ($CFG)"
if [ ! -f "$CFG" ]; then
  echo "    파일이 없습니다. /boot/config.txt 를 쓰는 이전 OS 이면 NFORMARE_BOOT_DIR=/boot bash $0"
  problems=$((problems + 1))
else
  line="$(grep -n -i -E '^[[:space:]]*disable_splash[[:space:]]*=' "$CFG" | tail -1)"
  if [ -z "$line" ]; then
    echo "    disable_splash 줄이 없습니다 → sudo bash deploy/install_splash.sh (또는 pi_setup.sh)"
    problems=$((problems + 1))
  else
    n="${line%%:*}"
    # 그 줄이 속한 [섹션] (섹션 표시가 없으면 맨 앞이므로 모든 모델에 적용)
    section="$(awk -v n="$n" 'NR<=n && /^[[:space:]]*\[.*\][[:space:]]*$/ {s=$0} END {print s}' "$CFG")"
    echo "    $line   (섹션: ${section:-없음 = 모든 모델})"
    case "$line" in
      *=*1*) : ;;
      *) echo "    값이 1 이 아닙니다 → disable_splash=1 이어야 합니다"; problems=$((problems + 1)) ;;
    esac
    case "${section,,}" in
      ""|"[all]") : ;;
      *) echo "    이 줄이 특정 모델용 섹션 $section 안에 있어 이 Pi 에는 적용되지 않을 수 있습니다 → [all] 아래로 옮기세요"
         problems=$((problems + 1)) ;;
    esac
  fi
fi

echo "[2] cmdline.txt ($CMD)"
if [ ! -f "$CMD" ]; then
  echo "    파일이 없습니다"
  problems=$((problems + 1))
else
  lines="$(wc -l < "$CMD")"
  [ "$lines" -gt 1 ] && { echo "    한 줄이 아닙니다 ($lines 줄) — 부팅이 안 될 수 있습니다"; problems=$((problems + 1)); }
  for t in quiet splash logo.nologo loglevel=3 vt.global_cursor_default=0; do
    if tr ' ' '\n' < "$CMD" | grep -qx -- "$t"; then echo "    있음: $t"; else echo "    없음: $t"; problems=$((problems + 1)); fi
  done
fi

echo "[3] 펌웨어가 실제로 읽은 값"
if command -v vcgencmd >/dev/null 2>&1; then
  v="$(vcgencmd get_config disable_splash 2>&1)"
  echo "    vcgencmd get_config disable_splash → ${v:-(출력 없음)}"
  case "$v" in
    *disable_splash=1*) echo "    → 펌웨어는 무지개 화면을 끄도록 읽었습니다. 그래도 화면에 나오면 아래 [안내]를 보세요." ;;
    *) echo "    → 펌웨어가 값을 읽지 못했습니다 (설정 줄이 없거나 다른 섹션이거나, 수정 후 재부팅을 안 했습니다)."
       problems=$((problems + 1)) ;;
  esac
else
  echo "    vcgencmd 가 없습니다 (Raspberry Pi 가 아닌 곳에서 실행 중?)"
fi

echo "[4] Plymouth 테마"
if command -v plymouth-set-default-theme >/dev/null 2>&1; then
  th="$(plymouth-set-default-theme 2>/dev/null)"
  echo "    현재 테마: ${th:-알 수 없음}"
  [ "$th" = "nformare" ] || { echo "    nformare 가 아닙니다 → sudo bash deploy/install_splash.sh"; problems=$((problems + 1)); }
else
  echo "    plymouth 가 설치되어 있지 않습니다 → sudo apt install plymouth plymouth-themes"
  problems=$((problems + 1))
fi

echo
if [ "$problems" -eq 0 ]; then
  echo "설정은 모두 정상입니다."
else
  echo "고칠 항목 $problems 개를 위에서 확인하세요."
fi
cat <<'EOF'

[안내]
- 무지개 화면은 GPU 펌웨어가 그리는 화면이라 **다른 이미지로 바꿀 수 없고 끌 수만 있습니다** (disable_splash=1).
  끄면 커널/Plymouth 가 시작될 때까지(Pi 3A+ 는 보통 수 초) 화면이 검게 보입니다.
- [3] 이 disable_splash=1 인데도 무지개가 보이면 설정 문제가 아니라 다른 원인입니다. 이 출력 전체와
  config.txt 전체(`cat /boot/firmware/config.txt`)를 보내 주세요.
- 수정한 뒤에는 반드시 재부팅해야 적용됩니다 (`sudo reboot`).
EOF
exit 0
