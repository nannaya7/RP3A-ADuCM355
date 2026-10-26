#!/bin/bash
# 자동 업데이트 / 업데이트 알림 / 화면 꺼짐을 끈다 (키오스크용). 여러 번 실행해도 안전하다.
#
#   sudo bash deploy/disable_updates.sh
#
# 되돌리려면: sudo bash deploy/disable_updates.sh --undo
# 끄는 것: apt 자동 갱신/업그레이드 타이머, unattended-upgrades, PackageKit(업데이트 알림),
#          데스크톱 알림 데몬 자동 시작, 화면 절전(blanking).
# 수동 업데이트(`sudo apt update && sudo apt upgrade`)는 그대로 쓸 수 있다.
set -u
[ "$(id -u)" -eq 0 ] || { echo "sudo 로 실행하세요: sudo bash $0"; exit 1; }

UNITS="apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service unattended-upgrades.service packagekit.service packagekit-offline-update.service"

if [ "${1:-}" = "--undo" ]; then
  for u in $UNITS; do systemctl unmask "$u" 2>/dev/null; done
  systemctl enable --now apt-daily.timer apt-daily-upgrade.timer 2>/dev/null
  rm -f /etc/apt/apt.conf.d/99-nformare-no-auto
  echo "자동 업데이트를 다시 켰습니다."
  exit 0
fi

echo "[1] apt 자동 갱신/업그레이드 끄기"
for u in $UNITS; do
  systemctl disable --now "$u" 2>/dev/null
  systemctl mask "$u" 2>/dev/null
done
cat > /etc/apt/apt.conf.d/99-nformare-no-auto <<'EOF'
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
APT::Periodic::Download-Upgradeable-Packages "0";
APT::Periodic::AutocleanInterval "0";
EOF

echo "[2] 사용자 알림/업데이트 확인 자동 시작 끄기"
# 시스템 전체 autostart 항목을 사용자 폴더에서 숨김 처리한다 (패키지를 지우지 않는다).
for home in /home/*; do
  [ -d "$home" ] || continue
  owner="$(stat -c %U "$home")"
  dir="$home/.config/autostart"
  sudo -u "$owner" mkdir -p "$dir"
  for f in /etc/xdg/autostart/*update* /etc/xdg/autostart/*notif* /etc/xdg/autostart/*packagekit* /etc/xdg/autostart/*pkgcheck*; do
    [ -f "$f" ] || continue
    name="$(basename "$f")"
    printf '[Desktop Entry]\nType=Application\nName=%s\nHidden=true\n' "$name" | sudo -u "$owner" tee "$dir/$name" >/dev/null
    echo "    숨김: $name ($owner)"
  done
done

echo "[3] 화면 꺼짐(절전) 끄기"
if command -v raspi-config >/dev/null 2>&1; then
  raspi-config nonint do_blanking 1 2>/dev/null && echo "    raspi-config: 화면 꺼짐 해제"
fi

echo
echo "완료. 적용하려면 재부팅하세요: sudo reboot"
echo "확인: systemctl list-timers | grep apt   (아무것도 안 나오면 정상)"
