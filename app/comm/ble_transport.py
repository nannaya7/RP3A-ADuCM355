"""BLE(Nordic UART Service) 전송 계층. 패치 센서의 ADuCM355 는 BLE NUS 로 UART 를 그대로 흉내 내므로
패킷 처리는 유선 UART 와 완전히 같다 — 바이트를 읽고 쓰는 일만 BLE 로 바꾼다.

- 장치 찾기: 주소(address)가 있으면 그 주소, 없으면 광고 이름이 name_prefix 로 시작하거나 NUS 서비스를 광고하는 장치.
- 쓰기: RX 특성(6E400002)에 MTU 크기로 쪼개 보낸다.  읽기: TX 특성(6E400003)의 notify 를 큐에 모은다.
- bleak(asyncio)는 전용 스레드에서 돌리고, open/read/write/close 는 UartWorker 스레드에서 동기로 부른다.
"""
import asyncio
import logging
import queue
import threading
from typing import Optional

log = logging.getLogger(__name__)

NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"      # 앱 → 모듈 (write)
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"      # 모듈 → 앱 (notify)


class BleNusTransport:
    def __init__(self, address: str = "", name_prefix: str = "nFor",
                 scan_timeout: float = 5.0, connect_timeout: float = 8.0):
        self.address, self.name_prefix = address.strip(), name_prefix.strip()
        self.scan_timeout, self.connect_timeout = scan_timeout, connect_timeout
        self.name = f"ble:{self.address or self.name_prefix + '*'}"
        self._rx: "queue.Queue[bytes]" = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._client = None
        self._lost = threading.Event()
        self._chunk = 20

    # ---- Transport 인터페이스 ----
    def open(self) -> None:
        try:
            import bleak  # noqa: F401  (없으면 OSError 로 알린다)
        except ImportError as e:
            raise OSError("bleak is not installed") from e
        self._lost.clear()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="ble-nus", daemon=True)
        self._thread.start()
        try:
            fut = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
            fut.result(self.scan_timeout + self.connect_timeout + 2.0)
        except Exception as e:
            self.close()
            raise OSError(str(e) or e.__class__.__name__) from e

    def close(self) -> None:
        loop, self._loop = self._loop, None
        if loop is None:
            return
        try:
            if self._client is not None:
                asyncio.run_coroutine_threadsafe(self._client.disconnect(), loop).result(3.0)
        except Exception as e:
            log.debug("ble disconnect: %s", e)
        finally:
            self._client = None
            loop.call_soon_threadsafe(loop.stop)
            if self._thread is not None:
                self._thread.join(2.0)
            self._thread = None
            while not self._rx.empty():
                self._rx.get_nowait()

    def read(self) -> bytes:
        try:
            data = self._rx.get(timeout=0.05)
        except queue.Empty:
            if self._lost.is_set():
                raise OSError("BLE link lost")
            return b""
        while True:                                   # 쌓인 조각을 한 번에 돌려준다
            try:
                data += self._rx.get_nowait()
            except queue.Empty:
                return data

    def write(self, data: bytes) -> None:
        if self._loop is None or self._lost.is_set():
            raise OSError("BLE link lost")
        try:
            asyncio.run_coroutine_threadsafe(self._write(data), self._loop).result(5.0)
        except Exception as e:
            raise OSError(str(e) or e.__class__.__name__) from e

    # ---- bleak (전용 스레드) ----
    async def _find(self):
        from bleak import BleakScanner
        if self.address:
            dev = await BleakScanner.find_device_by_address(self.address, timeout=self.scan_timeout)
        else:
            prefix = self.name_prefix.lower()

            def match(d, adv):
                return (NUS_SERVICE in [u.lower() for u in (adv.service_uuids or [])]
                        or bool(prefix and (d.name or adv.local_name or "").lower().startswith(prefix)))
            dev = await BleakScanner.find_device_by_filter(match, timeout=self.scan_timeout)
        if dev is None:
            raise OSError("BLE sensor not found")
        return dev

    async def _connect(self) -> None:
        from bleak import BleakClient
        dev = await self._find()
        client = BleakClient(dev, disconnected_callback=lambda _c: self._lost.set(), timeout=self.connect_timeout)
        await client.connect()
        self._client = client
        try:
            await client.start_notify(NUS_TX, lambda _c, data: self._rx.put(bytes(data)))
        except Exception:
            await client.disconnect()
            self._client = None
            raise
        self._chunk = max(20, (getattr(client, "mtu_size", 23) or 23) - 3)
        log.info("ble sensor connected: %s (%s), chunk=%d", dev.name, dev.address, self._chunk)

    async def _write(self, data: bytes) -> None:
        for i in range(0, len(data), self._chunk):
            await self._client.write_gatt_char(NUS_RX, data[i:i + self._chunk], response=False)
