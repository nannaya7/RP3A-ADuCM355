"""config.ini 로더."""
import configparser
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.ini"


@dataclass(frozen=True)
class Config:
    skip_login: bool = True
    log_level: str = "warning"        # warning(기본) | info | debug  (명령줄 -v / -vv 가 우선)
    virtual_keyboard: bool = True
    display_profile: str = "auto"      # auto | landscape | portrait
    screen: str = ""                  # 사용할 화면 이름(예: DSI-1). 비우면 주 화면
    fullscreen: bool = False
    bottom_margin: int = 20           # 세로 화면 아래쪽 안전 여백(px). 보이는 영역이 실제 해상도보다 작아 아래가 잘릴 때 키운다
    uart_port: str = "/dev/serial0"
    uart_baudrate: int = 115200
    uart_mock: bool = False           # true: 가상 펌웨어로 동작 (모듈 없이 화면 시험)
    # 측정 (Troponin)
    reaction_wait_s: int = 900        # 혈액 반응 대기(초). 타이머가 끝나야 T1 시작 버튼이 활성화
    reaction_timer_start: str = "auto"    # auto | manual
    auto_start_last: bool = False     # true: T2 를 사용자 수락 없이 자동 시작 (담당자 협의 후 결정)
    sensor_default: str = "builtin"   # 처음 실행할 때 켜 둘 센서: builtin(UART) | patch(블루투스) | off
    patch_name: str = "nFor"        # 패치 센서(BLE Nordic NUS) 광고 이름의 앞부분
    patch_address: str = ""           # 지정하면 이 BLE 주소로만 연결 (비우면 이름/NUS 서비스로 검색)
    sweep_start_hz: float = 10.0
    sweep_stop_hz: float = 200000.0
    sweep_points: int = 101
    channels: str = "0,1,2"
    rtia_ohm: float = 1000.0
    elapsed_min: Optional[float] = None
    assay: str = "troponin"           # 계산 모델: troponin | ntprobnp (연구개발용)
    c0_source: str = "first"          # first: c0 = 첫 측정(센서 0·1·2) 결과 | none: 과거 Day-1 기준값
    results_dir: str = "results"
    require_patient: bool = True      # true: 환자 프로필 필수 항목(성명/성별/나이/몸무게)을 채워야 첫 단계를 시작할 수 있다
    # 결과 표시 (단위와 참고 범위는 모델 담당자 확정 전까지 비워 둔다 → 숫자만 표시하고 정상/주의 판정은 하지 않는다)
    result_title: str = "Troponin"
    result_unit: str = ""
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    method: str = "EIS"
    net_mock: bool = False            # true: Wi-Fi/블루투스를 가상 백엔드로 (PC 시험용. Windows 는 자동)
    update_url: str = ""              # 업데이트 정보(latest.json) 주소. 비우면 업데이트 기능 끔
    update_check_on_start: bool = True    # 시작 후 한 번 새 버전을 조용히 확인 (설치는 사용자가 버튼으로)
    update_require_signature: bool = True # true: 서명이 맞는 패키지만 설치
    update_token: str = ""            # 비공개 서버의 읽기 토큰 (선택)
    server_base_url: str = ""


def _opt_float(text: str) -> Optional[float]:
    text = text.strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None


def load_config(path: Path = CONFIG_PATH) -> Config:
    cp = configparser.ConfigParser()
    try:
        # 편집기/전송 도구가 인코딩을 깨뜨려도 죽지 않도록 errors="replace" 로 읽는다 (파일이 없으면 기본값)
        with open(path, encoding="utf-8", errors="replace") as f:
            cp.read_file(f)
    except FileNotFoundError:
        pass
    d = Config()
    return Config(
        skip_login=cp.getboolean("app", "skip_login", fallback=d.skip_login),
        log_level=cp.get("app", "log_level", fallback=d.log_level).strip().lower(),
        virtual_keyboard=cp.getboolean("app", "virtual_keyboard", fallback=d.virtual_keyboard),
        fullscreen=cp.getboolean("display", "fullscreen", fallback=d.fullscreen),
        bottom_margin=max(0, min(200, cp.getint("display", "bottom_margin", fallback=d.bottom_margin))),
        display_profile=cp.get("display", "profile", fallback=d.display_profile).strip().lower(),
        screen=cp.get("display", "screen", fallback=d.screen).strip(),
        uart_port=cp.get("uart", "port", fallback=d.uart_port).strip(),
        uart_baudrate=cp.getint("uart", "baudrate", fallback=d.uart_baudrate),
        uart_mock=cp.getboolean("uart", "mock", fallback=d.uart_mock),
        sensor_default=cp.get("sensor", "default", fallback=d.sensor_default).strip().lower(),
        patch_name=cp.get("sensor", "patch_name", fallback=d.patch_name).strip(),
        patch_address=cp.get("sensor", "patch_address", fallback=d.patch_address).strip(),
        reaction_wait_s=cp.getint("measure", "reaction_wait_s", fallback=d.reaction_wait_s),
        reaction_timer_start=cp.get("measure", "reaction_timer_start", fallback=d.reaction_timer_start).strip().lower(),
        auto_start_last=cp.getboolean("measure", "auto_start_last", fallback=d.auto_start_last),
        sweep_start_hz=cp.getfloat("measure", "sweep_start_hz", fallback=d.sweep_start_hz),
        sweep_stop_hz=cp.getfloat("measure", "sweep_stop_hz", fallback=d.sweep_stop_hz),
        sweep_points=cp.getint("measure", "sweep_points", fallback=d.sweep_points),
        channels=cp.get("measure", "channels", fallback=d.channels).strip(),
        rtia_ohm=cp.getfloat("measure", "rtia_ohm", fallback=d.rtia_ohm),
        elapsed_min=_opt_float(cp.get("measure", "elapsed_min", fallback="")),
        assay=cp.get("measure", "assay", fallback=d.assay).strip().lower(),
        c0_source=cp.get("measure", "c0_source", fallback=d.c0_source).strip().lower(),
        results_dir=cp.get("measure", "results_dir", fallback=d.results_dir).strip(),
        require_patient=cp.getboolean("measure", "require_patient", fallback=d.require_patient),
        result_title=cp.get("result", "title", fallback=d.result_title).strip() or d.result_title,
        result_unit=cp.get("result", "unit", fallback=d.result_unit).strip(),
        ref_low=_opt_float(cp.get("result", "ref_low", fallback="")),
        ref_high=_opt_float(cp.get("result", "ref_high", fallback="")),
        method=cp.get("result", "method", fallback=d.method).strip() or d.method,
        net_mock=cp.getboolean("network", "mock", fallback=d.net_mock),
        update_url=cp.get("update", "url", fallback=d.update_url).strip(),
        update_check_on_start=cp.getboolean("update", "check_on_start", fallback=d.update_check_on_start),
        update_require_signature=cp.getboolean("update", "require_signature", fallback=d.update_require_signature),
        update_token=cp.get("update", "token", fallback=d.update_token).strip(),
        server_base_url=cp.get("server", "base_url", fallback=d.server_base_url).strip(),
    )
