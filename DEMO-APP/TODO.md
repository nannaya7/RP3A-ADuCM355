# DEMO-APP 할 일 목록

## 라즈베리파이 화면 끄기/켜기 (나중에 적용)
- 환경: DSI 패널, Debian 13 (trixie), Raspberry Pi OS 기본 Wayland(labwc) 로 추정
- 방법 (Pi 에서 아직 확인 안 함)
  - 백라이트(권장): `echo 1 | sudo tee /sys/class/backlight/*/bl_power` (끄기), `0` (켜기). 터치 입력은 계속 앱에 전달됨
    - 기본은 root 만 쓸 수 있음 → 앱에서 쓰려면 udev 규칙으로 일반 사용자 쓰기 권한 필요
  - 출력 끄기(대안): `wlr-randr --output DSI-1 --off` / `--on` (터치 장치도 같이 꺼질 수 있어 터치로 깨우기에는 부적합)
- 앱 안에 넣을 동작 (선택 필요)
  1. 입력이 없으면 N분 뒤 화면 끄기, 터치하면 켜기 (N분은 config.ini 에서 설정)
  2. 설정 화면에 "화면 끄기" 버튼
  3. 둘 다
