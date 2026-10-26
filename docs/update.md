# 배포 패키지와 업데이트

파이썬 코드를 **그대로** 배포한다 (바이너리 아님). 서버에 새 버전이 올라오면 장비가 알려 주고, **사용자가 버튼을 눌러** 설치한다.

## 1. 구성
| 파일 | 역할 |
|---|---|
| `app/version.py` | 앱 버전 `VERSION`. 커밋 접두사 `[V.x.xx.xxx]` 와 같은 값으로 맞춘다 |
| `tools/make_release.py` | 배포 패키지(`nformare-<버전>.tar.gz`)와 `latest.json` 생성, 서명 키 생성 |
| `app/update/updater.py` | manifest 가져오기, 서명 검증, 내려받기(SHA-256), 안전한 풀기, 설치 |
| `app/update/guard.py` | 설치 직후 안전장치: 계속 죽으면 이전 버전으로 되돌림 (표준 라이브러리만 사용) |
| `app/update/controller.py` | 화면과 연결, 백그라운드 실행, 재시작 |
| `app/ui/update_panel.py` | 설정 > **정보** 탭 (버전, 업데이트 확인, 설치) |

## 2. 패키지 만들기 (개발 PC)
```bash
# 처음 한 번: 서명 키 생성 (개인 키는 안전한 곳에 보관, 저장소에 넣지 않는다)
python tools/make_release.py --gen-key ~/nformare-keys
#   → ~/nformare-keys/update_private.key  (비밀)
#   → app/update/update_key.pub           (공개 키 — 커밋한다. 장비에 같이 배포된다)

# 릴리스 만들기: app/version.py 의 VERSION 으로 dist/ 에 생성
python tools/make_release.py --key ~/nformare-keys/update_private.key --notes "변경 내용 한 줄"
```
- 결과: `dist/nformare-V.0.10.006.tar.gz`(약 7MB), `dist/latest.json`. **두 파일을 같은 서버 폴더에 올린다.**
- 포함: `app/`, `deploy/`, `main.py`, `requirements.txt`, `tools/uart_demo.py`, `tools/net_check.py`, `VERSION`. 제외: `tests/`, `docs/`, `Devices/`, `refer/`, 캐시.
- 같은 내용이면 같은 파일이 나온다 (시각·소유자 고정). 셸 스크립트 등은 LF 로 들어간다.
- 시험용으로 서명 없이: `--no-sign` (장비는 `require_signature = false` 여야 설치).

`latest.json`:
```json
{"version": "V.0.10.007", "url": "nformare-V.0.10.007.tar.gz", "sha256": "…", "size": 7045942,
 "notes": "변경 내용", "signature": "<base64 ed25519>"}
```
`url` 이 상대 경로이면 `latest.json` 주소 기준이다. 서명 대상은 `"<version>\n<sha256>"`.

## 3. 장비 설정 (`config.ini`)
```ini
[update]
url = https://서버주소/경로/latest.json     ; 비우면 업데이트 기능 꺼짐 (서버가 정해지면 채운다)
check_on_start = true                       ; 시작 20초 뒤 한 번 조용히 확인
require_signature = true                    ; 서명이 맞는 패키지만 설치
token =                                     ; 비공개 서버의 읽기 토큰 (선택, Authorization: Bearer)
```
`file:///…/latest.json` 주소도 되므로 USB/로컬 폴더로 시험할 수 있다.

## 4. 장비에서 보이는 동작
1. 시작 20초 뒤(또는 설정 > 정보 > **업데이트 확인**) 서버의 `latest.json` 을 읽는다. 현재보다 높은 버전이면 **톱니바퀴에 빨간 점**이 뜨고, 정보 탭에 새 버전과 변경 내용이 보인다. 아무것도 설치하지 않는다.
2. 사용자가 **설치**를 누르고 확인 창에서 `예` → 서명 확인 → 내려받기 → SHA-256 확인 → 검사 → 교체 → 앱이 다시 시작된다.
3. **검사 중(측정 중이거나 1단계 이상 진행 중)에는 확인도 설치도 하지 않는다.**

## 5. 설치가 하는 일과 안전장치
- 패키지는 `.update/staging` 에 풀어 검사한다: 허용된 최상위 이름만(`app deploy tools main.py requirements.txt VERSION`), `..`/절대 경로/링크/장치 파일 거부, `main.py` 와 `app/version.py` 존재, 버전이 `latest.json` 과 같은지, 모든 `.py` 문법 검사. 하나라도 어긋나면 **아무것도 바꾸지 않고** 오류 문구만 보인다.
- 통과하면 현재 `app/ deploy/ tools/ main.py …` 를 `.update/prev/` 로 옮기고 새 것을 놓는다. **`config.ini`, `data/`, `results/` 는 건드리지 않는다.**
- 설치 직후 `.update/state.json` 에 `pending` 을 적는다. 새 버전이 켜질 때마다 시도 횟수가 오르고, 앱이 30초 정상으로 떠 있으면 확정(`pending` 삭제). **정상 표시 없이 4번째로 시작되면 이전 버전으로 자동 복구**한다 (`main.py` 맨 앞에서 확인).
- 개발용 작업 폴더(`.git` 이 있는 곳)에는 설치하지 않는다.
- 서명: ed25519. 서명이 없거나 틀리면, 또는 공개 키/`python3-cryptography` 가 없으면 설치하지 않는다 (`require_signature = true`).

## 6. 한계 / 알아둘 것
- 복구는 **다시 시작될 때** 일어난다. 새 버전이 시작하자마자 죽으면 전원을 껐다 켜거나(자동 시작) 앱을 다시 실행하는 것을 3번 더 하면 복구된다. 자동 재시작을 원하면 systemd 서비스(`Restart=always`)로 앱을 띄우도록 바꾸는 것을 권한다.
- `deploy/` 의 스크립트(부팅 로고, 시스템 설정 등)는 **파일만 교체**된다. 장비에 다시 적용(`sudo bash deploy/…`)하는 것은 사람이 한다.
- 새 버전이 새 시스템 패키지(`apt`)를 요구하면 업데이트만으로는 설치되지 않는다. 그런 릴리스는 별도 안내가 필요하다.
- 서버가 정해지면 `[update] url` 만 채우면 된다. GitHub Releases 를 쓰면 `latest.json` 과 `tar.gz` 를 릴리스 자산으로 올리고, 비공개 저장소는 `token` 을 넣는다.
- 장비 수가 늘면 롤아웃 단계 구분(채널), 서명 키 교체 절차가 추가로 필요하다.
