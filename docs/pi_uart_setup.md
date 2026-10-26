# Raspberry Pi UART 설정 및 연결 테스트

> 대상: Raspberry Pi 3A+ (Raspberry Pi OS Trixie, Python 3.13.5)
> 목적: Pi의 UART(`/dev/serial0`)가 활성화되어 있는지 확인하고, **PC ↔ USB-TTL 어댑터 ↔ Pi** 구성으로 송수신을 검증한다.
> 이후 이 UART는 ADuCM355 측정 모듈과의 통신에 쓰인다 ([uart_protocol.md](uart_protocol.md)).

> ⚠️ 이 문서의 명령은 일반적인 Raspberry Pi OS 동작에 근거한 것이며, **이 Pi에서 실제로 실행해 확인한 결과는 아직 없다.** 결과를 §7에 기록한다.

## 1. 배선 (PC → USB-TTL → Pi)

| USB-TTL 어댑터 | Pi 40핀 헤더 | 비고 |
|---|---|---|
| **TX** | **10번 핀 (GPIO15, RXD)** | 교차 연결 |
| **RX** | **8번 핀 (GPIO14, TXD)** | 교차 연결 |
| **GND** | 6 / 9 / 14번 중 하나 (GND) | 필수 |
| VCC / 5V | **연결하지 않음** | Pi는 자체 전원 사용 |

주의:
- 어댑터는 **3.3V 로직(TTL)** 이어야 한다. CP2102 / FT232 / CH340 계열 USB-TTL 모듈은 대부분 가능하며, 전압 점퍼가 있으면 **3.3V**로 설정한다.
- **RS-232(±12V) 변환기는 연결하지 않는다.** Pi GPIO는 5V도 견디지 못한다.
- TX와 RX는 서로 **교차**한다 (어댑터 TX → Pi RX).

## 2. Pi의 UART 활성 여부 확인

### 2.1 설정 상태 확인
```bash
sudo raspi-config nonint get_serial_hw     # 0 = 시리얼 하드웨어 활성
sudo raspi-config nonint get_serial_cons   # 1 = 시리얼 로그인 콘솔 비활성 (우리는 1이어야 함)
grep -i enable_uart /boot/firmware/config.txt
ls -l /dev/serial*
dmesg | grep -i tty
```

기대 결과:

| 확인 | 정상 값 |
|---|---|
| `get_serial_hw` | `0` |
| `get_serial_cons` | `1` |
| `config.txt` | `enable_uart=1` |
| `/dev/serial0` | `ttyS0`(미니 UART) 또는 `ttyAMA0`(PL011)를 가리키는 심볼릭 링크 |

### 2.2 활성화가 안 되어 있으면
```bash
sudo raspi-config nonint do_serial_hw 0     # 시리얼 하드웨어 켜기
sudo raspi-config nonint do_serial_cons 1   # 시리얼 로그인 콘솔 끄기
sudo usermod -aG dialout $USER              # 포트 접근 권한 (재로그인 필요)
sudo reboot
```
메뉴 방식: `sudo raspi-config` → Interface Options → Serial Port → "로그인 셸을 시리얼로 사용?" **No**, "시리얼 하드웨어 활성화?" **Yes**.

### 2.3 포트 점유 확인
```bash
groups | grep dialout
sudo systemctl status serial-getty@ttyS0 serial-getty@ttyAMA0 2>/dev/null | grep -E "Loaded|Active"
```
시리얼 콘솔(getty)이 켜져 있으면 PC에서 보낸 글자에 로그인 프롬프트가 섞이거나 포트가 점유된다.

### 2.4 Pi 3A+ 참고: 미니 UART와 PL011
- Pi 3A+는 블루투스가 하드웨어 UART(PL011)를 사용한다. 기본 설정에서는 `/dev/serial0`이 **미니 UART(`ttyS0`)** 를 가리킨다.
- 115200bps에서는 보통 동작하지만 **글자가 깨지면** `/boot/firmware/config.txt`에 아래 줄을 추가하고 재부팅한다 (블루투스를 쓰지 않을 때).
  ```
  dtoverlay=disable-bt
  ```
  이후 `/dev/serial0`이 `ttyAMA0`(PL011)을 가리킨다.
- 안전하게 하려면 설정 변경 전에 백업: `sudo cp /boot/firmware/config.txt /boot/firmware/config.txt.bak`

## 3. 루프백 테스트 (배선 없이 Pi 단독)

Pi의 **8번 핀(TXD)과 10번 핀(RXD)을 점퍼선으로 직접 연결**한 뒤:
```bash
python3 -c "
import serial,time
s=serial.Serial('/dev/serial0',115200,timeout=1)
s.write(b'hello\n'); time.sleep(0.2); print(s.read(20))"
```
- `b'hello\n'`이 돌아오면 Pi UART 정상.
- 아무것도 안 돌아오면: 설정(§2), 포트 이름, 점퍼 연결을 확인한다.
- 테스트 후 점퍼선은 **반드시 제거**한다 (PC 어댑터와 충돌).

## 4. picocom으로 연결 (Pi 쪽)

### 4.1 설치
```bash
sudo apt install picocom
```

### 4.2 연결
```bash
picocom -b 115200 /dev/serial0
```
- 기본 8N1, 흐름 제어 없음. 줄바꿈이 어긋나면 `--omap crcrlf --imap lfcrlf --echo`를 추가한다.
- **종료**: `Ctrl+A` 다음 `Ctrl+X`
- 권한 오류: `dialout` 그룹 추가(§2.2) 후 재로그인, 임시로는 `sudo picocom …`

## 5. PC 쪽 연결 (Windows)

picocom은 Windows에서 쓸 수 없다. **시리얼 터미널 프로그램**(Tera Term, PuTTY 등, 사용자는 다른 프로그램 사용)이면 무엇이든 된다. 아래 설정값만 맞추면 된다.

| 항목 | 값 |
|---|---|
| 포트 | USB-TTL 어댑터의 COM 번호 (장치 관리자 → 포트에서 확인) |
| 속도 | 115200 |
| 데이터 비트 / 패리티 / 정지 비트 | 8 / none / 1 |
| 흐름 제어 | none |
| 로컬 에코 | 필요 시 켬 (Tera Term: Setup → Terminal → Local echo) |

## 6. 양방향 왕복 테스트 순서

1. Pi에서 `picocom -b 115200 /dev/serial0` 실행
2. PC에서 Tera Term으로 어댑터의 COM 포트에 연결
3. **PC에서 입력 → Pi 화면에 표시**되는지 확인
4. **Pi에서 입력 → PC 화면에 표시**되는지 확인

| 증상 | 점검 |
|---|---|
| 한 방향만 됨 | 안 되는 쪽 TX/RX 교차 연결, GND 연결 |
| 글자가 깨짐 | 속도 불일치(양쪽 115200), 미니 UART 문제(§2.4), 케이블 불량 |
| 로그인 프롬프트가 보임 | 시리얼 콘솔이 켜져 있음 → `do_serial_cons 1` (§2.2) |
| `Permission denied` | `dialout` 그룹 미가입 |
| `No such file` | 시리얼 하드웨어 비활성 → `do_serial_hw 0` 후 재부팅 |

## 7. 테스트 결과 기록 (작성 칸)

| 항목 | 결과 | 날짜 |
|---|---|---|
| `get_serial_hw` / `get_serial_cons` | | |
| `/dev/serial0` 링크 대상 | | |
| 루프백 테스트 | | |
| PC → Pi | ✅ 수신 확인 (사용자 보고) | 2026-10-24 |
| Pi → PC | ✅ 송신 확인 (사용자 보고) | 2026-10-24 |
| `disable-bt` 적용 여부 | | |

## 8. 다음 단계: ADuCM355 모듈 연결 시 확인할 것

- 모듈의 UART0는 **P0.10 / P0.11**, **115200 8N1**이다 ([uart_protocol.md](uart_protocol.md) §1).
- **신호 레벨(3.3V 추정)** 과 Pi 직결 가능 여부, TX/RX 방향, GND 공통, 전원 공급 방식, 리셋선 유무는 **모듈 회로도로 확인되지 않았다.**
- 직결하기 전 모듈의 UART 핀 전압이 **3.3V**인지 반드시 확인한다 (5V이면 레벨 변환기 필요).
- PC ↔ Pi 테스트가 통과하면, Pi에서 `tools/uart_demo.py` 대신(프로토콜 재작업 전) 먼저 PC의 터미널로 `STATUS` 같은 줄 명령에 응답하는 간이 테스트를 할 수 있다.
