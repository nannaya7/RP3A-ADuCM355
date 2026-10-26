# 프로젝트 규칙

## Git 커밋 / 푸시
- 커밋 메시지는 항상 **버전 접두사**로 시작한다: `[V.0.10.001] 내용`
- 커밋 전에 현재 버전을 확인해(직전 커밋 `git log`의 접두사 기준) 접두사에 붙인다. 버전을 올릴 때는 사용자가 지정한 값을 쓴다.
- 요청받으면 커밋 후 `origin main` 으로 푸시한다.
- `refer/`(참고 자료, 가상환경 포함), `data/`, `results/` 는 저장소에 올리지 않는다(.gitignore).

## 폴더 메모
- `Devices/` : 주변 장치 펌웨어 소스 (git 제외). `ADuCM355`(임피던스 AFE), `BT-Nordic-NUS`(BLE NUS 브리지, 광고 이름 `nFor…`), `UPS-stm32f103`(전원 장치/UPS, STM32F103).

## 코드 구조
- 앱 코드와 리소스는 모두 `app/` 아래에 있다 (`app.ui`, `app.comm`, `app.measure`, `app.models`, `app.net`, `app.auth`, `app/assets`, `app/fonts`, `app/icon`). import 는 `from app.ui.x import …` 형식.
- `tools/`(개발용 스크립트), `tests/`, `deploy/`, `docs/` 는 `app/` 밖. `data/`, `results/`, `config.ini` 는 프로젝트 루트.
