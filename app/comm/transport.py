"""바이트 전송 계층. 실제 시리얼(SerialTransport)과 가상 펌웨어(MockFirmware)가 같은 인터페이스를 따른다."""
import logging
import sys
from typing import Protocol

log = logging.getLogger(__name__)


class Transport(Protocol):
    name: str

    def open(self) -> None: ...      # 실패 시 OSError 발생
    def close(self) -> None: ...
    def read(self) -> bytes: ...     # 짧은 타임아웃(~50ms) 후 빈 bytes 가능
    def write(self, data: bytes) -> None: ...


class SerialTransport:
    def __init__(self, port: str, baudrate: int):
        self.port, self.baudrate = port, baudrate
        self.name = f"{port}@{baudrate}"
        self._ser = None

    def open(self) -> None:
        import serial  # pyserial 없이도 protocol/mock 을 쓸 수 있도록 지연 import
        try:
            self._ser = serial.Serial(self.port, self.baudrate, timeout=0.05, write_timeout=1.0)
        except serial.SerialException as e:
            raise OSError(str(e)) from e

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def read(self) -> bytes:
        import serial
        try:
            return self._ser.read(self._ser.in_waiting or 1)
        except (serial.SerialException, OSError) as e:  # 케이블 분리 등
            raise OSError(str(e)) from e

    def write(self, data: bytes) -> None:
        import serial
        try:
            self._ser.write(data)
        except (serial.SerialException, OSError) as e:
            raise OSError(str(e)) from e


def create_transport(port: str, baudrate: int, mock: bool = False) -> Transport:
    """mock=True 이면 가상 장치. 개발용 Windows PC 에서는 포트를 열 수 없을 때 가상 장치로 대체한다."""
    from .mock_device import MockFirmware, troponin_demo_z

    def demo() -> MockFirmware:
        fw = MockFirmware(point_interval=0.01)   # 3센서 × 101점 ≈ 3초
        fw.z_func = troponin_demo_z(fw)
        return fw

    if mock:
        return demo()
    t = SerialTransport(port, baudrate)
    if sys.platform == "win32":
        try:
            t.open()
            t.close()
        except OSError:
            log.warning("cannot open port %s, using the mock device", port)
            return demo()
    return t
