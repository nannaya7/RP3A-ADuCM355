# 부팅 스플래시: 무지개 화면 끄기 + nformare 브랜드 화면

> 상태: 파일과 설치 스크립트는 만들었고, **부팅 설정 파일을 고치는 로직은 PC에서 테스트로 확인했다(15개).**
> **Plymouth 스플래시 자체는 PC에서 볼 수 없어 Pi 실기에서 아직 확인하지 않았다.** 아래 §6의 확인 목록으로 검증한다.

## 1. 부팅 중 화면과 처리

| 순서 | 화면 | 처리 |
|---|---|---|
| 1 | 무지개색 사각형 (GPU 펌웨어) | `config.txt`에 `disable_splash=1` — **DSI만 쓰므로 필요 없어 끈다** |
| 2 | 커널 로고(왼쪽 위 열매)와 글자 메시지 | `cmdline.txt`에 `logo.nologo quiet loglevel=3 vt.global_cursor_default=0` |
| 3 | 라즈베리 로고 스플래시 (Plymouth) | **nformare 테마로 교체** (`splash` 유지) |
| 4 | 데스크톱 → 앱 | 자동 시작(6단계)에서 처리 — 아래 §7 |

## 2. 만든 파일

```
deploy/
  install_splash.sh              설치/제거 스크립트 (Pi 에서 실행, LF 줄바꿈)
  patch_boot_files.py            cmdline.txt / config.txt 를 안전하게 고치는 도구 (테스트됨)
  plymouth/
    nformare/
      nformare.plymouth          테마 정의
      nformare.script            로고를 중앙에 배치 (배경색 #E9F1ED)
      logo.png                   로고(심볼+워드마크+태그라인), 투명 배경, 744x264
    preview/splash_480x800.png, splash_1280x800.png    PC 에서 합성한 미리보기
tools/make_boot_splash.py        logo.png 와 미리보기를 다시 만드는 도구
tests/test_boot_patch.py         부팅 파일 수정 로직 테스트 15개
```
- 로고는 로그인 화면의 `BrandLockup`과 같은 비율이고, 배경색은 앱의 페이지 배경색과 같다. 그래서 스플래시 → 앱으로 넘어갈 때 색이 튀지 않는다.
- 스크립트가 화면 크기에 맞춰 로고를 줄인다: **세로 화면은 폭의 82%, 가로 화면은 50%, 최대 640px**, 항상 중앙. 한 테마로 480x800과 1280x800 모두 쓴다.
- 스크립트는 **정적 로고만** 그린다(진행 표시 애니메이션 없음). PC에서 미리 시험할 수 없는 코드라 가장 단순하게 두었다. 동작이 확인되면 로딩 표시를 추가할 수 있다.

## 3. 설치 (Pi)

1. **`deploy/` 폴더를 Pi에 올린다** (FileZilla). 예: `~/PyNFor/deploy/`
2. 먼저 **무엇을 할지만 확인**:
   ```bash
   cd ~/PyNFor
   bash deploy/install_splash.sh --dry-run
   ```
   `cmdline.txt 이전 / 이후`가 출력된다. 이후 줄이 **한 줄**이고 기존 항목(`root=PARTUUID=…` 등)이 그대로인지 눈으로 본다.
3. 설치:
   ```bash
   sudo bash deploy/install_splash.sh
   sudo reboot
   ```
4. 되돌리기:
   ```bash
   sudo bash deploy/install_splash.sh --uninstall
   sudo reboot
   ```

### 스크립트가 하는 일
- 원본 `cmdline.txt`, `config.txt`, 현재 Plymouth 테마 이름을 `/var/lib/nformare-splash/`에 **처음 한 번만** 백업한다 (이미 있으면 덮어쓰지 않는다).
- 테마를 `/usr/share/plymouth/themes/nformare/`에 복사한다.
- `config.txt` 맨 끝(`[all]` 섹션)에 `disable_splash=1`을 추가한다.
- `cmdline.txt` 한 줄 끝에 없는 항목만 추가한다: `quiet splash plymouth.ignore-serial-consoles logo.nologo loglevel=3 vt.global_cursor_default=0`. 이미 있는 항목은 중복하지 않고, `loglevel=`처럼 값이 있는 항목은 값만 바꾼다.
- `plymouth-set-default-theme -R nformare`로 기본 테마를 바꾸고 initramfs를 다시 만든다 (1~2분 걸릴 수 있음).
- 여러 번 실행해도 결과가 같다(멱등).

### 안전장치
- `cmdline.txt`가 **여러 줄이거나 비어 있으면 아무것도 쓰지 않고 중단**한다 (잘못 고치면 부팅이 안 되기 때문).
- `--dry-run`은 파일을 전혀 쓰지 않는다.
- 필요한 명령이 없으면(예: Plymouth 미설치) 설치 전에 멈춘다. Plymouth가 없으면 `sudo apt install plymouth plymouth-themes` 후 다시 실행한다.

## 4. 문제가 생겼을 때

| 증상 | 조치 |
|---|---|
| 스플래시가 안 나오고 검은 화면 | `cmdline.txt`에 `splash`가 있는지 확인. `plymouth-set-default-theme`로 현재 테마가 `nformare`인지 확인 |
| 예전 라즈베리 로고가 그대로 나옴 | `sudo plymouth-set-default-theme -R nformare` 를 다시 실행하고 재부팅 (initramfs가 갱신되지 않은 경우) |
| 스플래시가 **옆으로 누워** 보임 | 세로가 기본인 패널(예: 10.1인치, 800x1280)을 가로로 쓰는데 부팅 단계에서는 회전이 적용되지 않는 경우. 로고를 미리 돌려서 만든다: `python tools/make_boot_splash.py --rotate 90` (또는 `270`) 후 `logo.png`를 다시 올려 설치 |
| 부팅이 안 됨 | SD카드를 PC에 꽂아 `/var/lib/nformare-splash/cmdline.txt.orig`(또는 `cmdline.txt.bak`류 백업) 내용을 SD의 `cmdline.txt`에 되돌린다 (한 줄) |
| 로그가 필요함 | `cmdline.txt`에서 `quiet`와 `loglevel=3`을 임시로 빼면 부팅 메시지가 다시 보인다 |

## 5. 확인된 것과 확인되지 않은 것
- ✅ 로고 이미지 생성과 크기 규칙(미리보기), `cmdline.txt`·`config.txt` 수정 로직 15개 테스트, 스크립트 문법과 `--dry-run` 동작(PC)
- ⚠️ 확인하지 못함: Plymouth 스크립트가 이 Pi OS 버전에서 실제로 로고를 그리는지, 패널 회전 시 스플래시 방향, DSI에서 무지개 화면이 실제로 안 나오는지, initramfs 재생성 소요 시간
- `plymouth-set-default-theme`의 옵션(`-R`)과 `/usr/share/plymouth/themes/` 경로는 Debian/Raspberry Pi OS의 일반적인 방식에 근거한 것이다.

## 6. Pi에서 확인 목록
1. `--dry-run` 출력에서 `cmdline.txt 이후`가 한 줄이고 기존 값이 보존되는가
2. 설치 후 재부팅 시 무지개 화면과 왼쪽 위 열매 로고가 나오지 않는가
3. 스플래시가 nformare 로고, 배경색 `#E9F1ED`로 **화면 중앙**에 나오는가 (480x800 / 1280x800 각각)
4. 방향이 올바른가 (누워 있지 않은가)
5. 스플래시 이후 화면이 어떻게 이어지는가 (바탕화면이 잠깐 보이는지)
6. `--uninstall`로 원래대로 돌아오는가

## 7. 남은 과제
- 스플래시가 끝난 뒤 **바탕화면과 작업표시줄이 잠깐 보이는 문제**는 이 작업으로 해결되지 않는다. 앱 자동 시작(6단계)에서 데스크톱 패널/배경을 숨기거나 앱을 바로 전체화면으로 띄우는 작업과 같이 한다.
- 스플래시에 로딩 표시(점 애니메이션)를 넣을지, 문구("부팅 중…")를 넣을지는 스플래시 동작을 확인한 뒤 정한다.

## 6. 무지개 화면이 아직 나올 때 — `deploy/check_boot.sh`
```bash
bash deploy/check_boot.sh          # 읽기 전용, 아무것도 바꾸지 않는다
```
- `config.txt` 의 `disable_splash` 줄과 **그 줄이 속한 섹션**(`[cm5]` 같은 특정 모델 섹션 안에 있으면 이 Pi 에 적용되지 않는다), `cmdline.txt` 항목, Plymouth 테마를 점검한다.
- 핵심은 `vcgencmd get_config disable_splash`: **펌웨어가 실제로 읽은 값**이다. `disable_splash=1` 이면 설정은 적용된 것이다. 설정을 고친 뒤에는 **재부팅**해야 한다.
- 설정 스크립트(`patch_boot_files.py`)는 이제 `disable_splash=1` 이 특정 모델 섹션에만 있으면 `[all]` 아래에 다시 넣는다.
- 무지개 화면은 GPU 펌웨어가 그려서 **다른 이미지로 바꿀 수 없고 끌 수만 있다**. 끄면 Plymouth 가 시작될 때까지(Pi 3A+ 는 수 초) 화면이 검게 보이는 것이 정상이다.
- `disable_splash=1` 이 읽혔는데도 무지개가 보이면 설정 밖의 원인이므로, `check_boot.sh` 출력 전체와 `cat /boot/firmware/config.txt` 를 보내 주면 다음 원인을 찾는다. (DSI 패널에서 실제로 꺼지는지는 아직 Pi 에서 확인하지 못했다.)

## 7. 대체 이미지를 만들 때의 규격 (브랜드 로고)
스플래시는 **단색 배경(#E9F1ED) 위에 로고 한 장을 가운데에 놓는** 방식이다 (`nformare.script`).
| 항목 | 권장 |
|---|---|
| 파일 | `deploy/plymouth/nformare/logo.png` 한 장 |
| 형식 | **PNG, 24비트 + 투명도(RGBA), 투명 배경**, sRGB, 비인터레이스, ICC 프로필 없음 |
| 크기 | **가로 1280 px 이상**(권장 1280~1600), 세로는 비율대로 (현재 로고 744x264). 화면에서는 가로 최대 **640 px** 로 줄여 보이므로 2배 크기로 만들면 선명하다 |
| 화면에서의 크기 | 세로 화면(480x800): 가로의 82% ≈ 394 px / 가로 화면(1280x800): 50% = 640 px (최대 640) |
| 여백 | 로고 둘레에 투명 여백 20~40 px (잘림 방지) |
| 용량 | 500 KB 이하 권장 (initramfs 에 들어간다) |
- 올리고 나서: `sudo bash deploy/install_splash.sh` → 재부팅 (`plymouth-set-default-theme -R` 이 initramfs 를 다시 만든다).
- 패널이 세로가 기본(예: 800x1280)이라 스플래시가 누워 보이면 로고를 미리 돌려서 만든다 (`tools/make_boot_splash.py --rotate 90`).
- **전체 화면 이미지**(배경 사진 포함)로 바꾸려면 화면 크기별 이미지(1280x800, 800x1280, 480x800)가 필요하고 회전 문제도 다시 봐야 해서 별도 작업이다. 필요하면 말씀해 주세요.

## 9. 가로 장비(1280x800)에서 뒤집힘·쏠림 (2026-10-26)
> **해결 (Pi 실기 확인, 2026-10-26): 가로 장비는 로고를 시계 방향 90도 돌려 설치하면 맞다 (`--for landscape` = `--rotate 90`).** 세로 장비는 270도. 아래는 그 과정과 각도를 바꿔 시험하는 방법이다.

가로 장비에서 부팅 화면 두 단계(무지개 화면이 있던 자리, 로고 화면) 모두 **180도 뒤집혀** 보이고, 로고 화면은 **한쪽으로 쏠렸다.** (180도로 돌려 보니 90도가 어긋났고, `--rotate 90` 에서 맞았다. 처음의 "180도 뒤집힘"은 실제 패널 방향이 90도 어긋난 것을 다르게 본 것이었다.)

**스크립트는 하나** (`nformare.script`)이고 가로/세로를 따로 관리하지 않는다. 화면 크기로 로고 크기를 정하고(세로 82%, 가로 50%), 장비마다 다른 것은 **로고 이미지의 회전**뿐이다. 그래서 설치할 때 장비 종류를 알려 준다:
```bash
sudo bash deploy/install_splash.sh --for landscape    # 가로 장비: deploy/boot_logo_landscape_90.png (시계 방향 90도 돌린 로고)
sudo bash deploy/install_splash.sh --for portrait     # 세로 장비: deploy/boot_logo_rot270.png (270도)
sudo bash deploy/install_splash.sh --logo 내로고.png   # 직접 고른 PNG (--for 보다 우선)
sudo reboot
```
- `--for`/`--logo` 가 없으면 테마 폴더의 `logo.png`(지금은 세로용 270도)가 설치된다. **가로 장비에 이걸 쓰면 옆으로 눕는다.**
- **뒤집힘/눕힘**: 장비(패널)마다 필요한 로고 각도가 다르다. 가로(10.1인치 Waveshare 1280x800) = 90도, 세로(480x800) = 270도로 확인했다. 다른 패널은 아래 `--rotate` 로 시험한다. (PC 에서 파일을 만들려면 `python tools/make_boot_splash.py --source deploy/boot_logo.png --rotate 90|180|270 --out-dir 폴더`, 또는 `python deploy/rotate_logo.py 원본.png 90 결과.png`.)
- **한쪽 쏠림**: 이전 스크립트는 시작할 때 화면 크기를 **한 번만** 읽어 로고 위치를 정했다. 부팅 중에는 Plymouth 가 처음엔 펌웨어 프레임버퍼에, 나중엔 실제 DSI 디스플레이에 그리는데 두 화면의 크기가 다르면 두 번째 단계에서 위치가 어긋난다. 새 스크립트는 **화면 크기가 바뀔 때마다 로고를 다시 배치**한다. (이 가설은 추정이고 Pi 에서 확인하지 못했다.) 이전 스크립트는 `deploy/plymouth/nformare_static.script.bak` 에 백업해 두었다.
- ⚠️ Plymouth 스크립트는 PC 에서 실행해 볼 수 없다. 새 스크립트에 문법 오류가 있으면 로고가 안 나오고 글자 부팅 화면이 나올 수 있다 → 위 백업 내용을 `nformare.script` 로 되돌리고 `--for ...` 로 다시 설치한다.

**각도를 바로 시험하기**: `sudo bash deploy/install_splash.sh --rotate 90|180|270` (시계 방향, 돌리지 않은 `boot_logo_centered.png` 를 Pi 에서 돌려 설치). `--for landscape` = `--rotate 90`, `--for portrait` = `--rotate 270` (둘 다 Pi 실기 확인). 새 패널이면 `--rotate 90`, 안 맞으면 `270`, `180`, `0` 순으로 시험한다. 자세한 내용은 [pi_setup.md](pi_setup.md) §4-1.

### 그래도 이상하면: 진단 테마
```bash
sudo bash deploy/splash_debug.sh on     # 진단 테마 설치 (1~2분) → sudo reboot
sudo bash deploy/splash_debug.sh off    # 원래 테마로 → sudo reboot
```
부팅 화면에 Plymouth 가 **보고하는 화면 크기(W, H)**, 크기가 **바뀐 횟수(N)**, 화면 가장자리의 빨간 테두리, 가운데 십자, 왼쪽 위 `TOP-LEFT` / 오른쪽 아래 `BOTTOM-RIGHT` 표식, 돌리지 않은 로고를 보여 준다. **두 단계 모두 사진**을 찍어 보내 주면 뒤집힘 각도와 쏠림 원인을 숫자로 알 수 있다. (이미지는 `python tools/make_boot_debug.py` 로 다시 만든다. 테마는 `deploy/plymouth/nformare-debug/`.)

## 8. 세로로 쓰는 패널에서 로고 돌리기 (2026-10-26)
패널의 원래 방향이 가로(예: 800x480)인데 세로로 세워 쓰면, 부팅 단계(Plymouth)에서는 OS 의 화면 회전이 적용되지 않아 로고가 옆으로 눕는다. 로고 이미지를 미리 돌려서 만든다.
```bat
python tools/make_boot_splash.py --source deploy/boot_logo.png --rotate 90  --out-dir deploy/plymouth/nformare --preview-dir deploy/plymouth/preview
python tools/make_boot_splash.py --source deploy/boot_logo.png --rotate 270 --out-dir deploy/plymouth/nformare     # 반대 방향
```
- `--source` 는 투명 배경 PNG. 투명하지 않은 부분만 잘라 사방 같은 여백(56 px)으로 맞추고 돌린다. 없으면 앱의 BrandLockup 으로 그린다.
- `--rotate 90` = 시계 방향, `270` = 반시계 방향. **결과가 거꾸로 보이면 다른 쪽**으로 다시 만든다.
- 돌려서 세로로 선 로고(높이 > 폭)는 `nformare.script` 가 **화면의 짧은 변의 82%** 에 긴 변을 맞춘다 (480x800 화면에서 약 394 px). 가로로 긴 로고는 이전 규칙(세로 화면 폭의 82%, 가로 화면 50%, 최대 640 px) 그대로다.
- 미리보기(`--preview-dir`): 패널 원래 방향(`--panel`, 기본 800x480)에서 합성한 뒤 사용자가 보는 방향으로 되돌려 저장한다. `deploy/boot_logo_rot90.png`, `boot_logo_rot270.png` 는 미리 만들어 둔 결과다.
- **가로 패널(1280x800 등)에서 이 로고(세로로 선 것)를 쓰면 안 된다.** 가로로 쓰는 장비는 돌리지 않은 로고를 쓴다 (`--rotate 0`).

