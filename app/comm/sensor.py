"""센서 선택: 내장 센서(UART) / 패치 센서(블루투스) / 꺼짐. 선택은 data/sensor.json 에 저장해 다음 실행에도 유지한다.

- 내장 센서: 기존대로 UART(config.ini [uart] port) 로 ADuCM355 에 연결한다.
- 패치 센서: BLE(Nordic UART Service)로 연결된 ADuCM355. UART 를 그대로 흉내 내므로 패킷 처리는 유선과 같다
  (config.ini [sensor] patch_name / patch_address). 설정 > 센서 에서 고른 장치의 주소(data/sensor.json)가 있으면 그것이 우선한다.
  두 센서는 동시에 켤 수 없다 (하나를 켜면 다른 하나는 자동으로 꺼진다).
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional, Tuple

from .transport import Transport, create_transport

log = logging.getLogger(__name__)

BUILTIN, PATCH, OFF = "builtin", "patch", "off"
MODES = (BUILTIN, PATCH, OFF)


def normalize(mode: Optional[str], default: str = BUILTIN) -> str:
    mode = (mode or "").strip().lower()
    return mode if mode in MODES else default


def toggled(current: str, which: str, on: bool) -> str:
    """토글 결과: which(patch/builtin)를 on 으로 켜면 그 센서만 켜지고(다른 센서는 자동 OFF), 끄면 모두 꺼진다."""
    if on:
        return which
    return OFF if current == which else current


class SensorStore:
    """선택한 센서를 파일에 저장한다 (임시 파일에 쓰고 바꿔치기해서 도중에 꺼져도 깨지지 않는다)."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            log.warning("cannot read the sensor setting (%s): %s", self.path, e)
            return {}

    def _write(self, data: dict) -> bool:
        tmp = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            log.warning("cannot save the sensor setting (%s): %s", self.path, e)
            return False

    def load(self, default: str = BUILTIN) -> str:
        return normalize(self._read().get("mode"), default)

    def save(self, mode: str) -> bool:
        data = self._read()
        data["mode"] = normalize(mode, OFF)
        return self._write(data)

    def load_patch(self) -> Tuple[str, str]:
        """설정 > 센서 에서 고른 패치 센서 (BLE 주소, 이름). 고르지 않았으면 ("", "")."""
        data = self._read()
        return str(data.get("patch_address") or "").strip(), str(data.get("patch_name") or "").strip()

    def save_patch(self, address: str, name: str = "") -> bool:
        data = self._read()
        data["patch_address"], data["patch_name"] = address.strip(), name.strip()
        return self._write(data)


def make_transport(mode: str, cfg) -> Optional[Transport]:
    """선택에 맞는 전송 장치. 꺼짐이면 None. 가상 모드(uart_mock)에서는 두 센서 모두 가상 펌웨어."""
    if mode == BUILTIN:
        return create_transport(cfg.uart_port, cfg.uart_baudrate, cfg.uart_mock)
    if mode == PATCH:
        if cfg.uart_mock:
            return create_transport("", cfg.uart_baudrate, True)
        from .ble_transport import BleNusTransport          # asyncio 가 들어 있어 패치 센서를 쓸 때만 불러온다
        return BleNusTransport(cfg.patch_address, cfg.patch_name)
    return None


def describe(mode: str, cfg) -> str:
    """설정 화면에 보이는 연결 방법 설명."""
    if mode == PATCH:
        return f"BLE ({cfg.patch_address or cfg.patch_name + '*'})"
    return f"UART ({cfg.uart_port})"
