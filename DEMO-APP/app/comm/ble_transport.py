"""BLE(Nordic UART Service) 전송 계층. 패치 센서의 ADuCM355 는 BLE NUS 로 UART 를 그대로 흉내 내므로
패킷 처리는 유선 UART 와 완전히 같다 — 바이트를 읽고 쓰는 일만 BLE 로 바꾼다.

- 장치 찾기: 주소(address)가 있으면 그 주소, 없으면 광고 이름이 name_prefix 로 시작하거나 NUS 서비스를 광고하는 장치.
- 쓰기: RX 특성(6E400002)에 MTU 크기로 쪼개 보낸다.  읽기: TX 특성(6E400003)의 notify 를 큐에 모은다.
- bleak(asyncio)는 전용 스레드에서 돌리고, open/read/write/close 는 UartWorker 스레드에서 동기로 부른다.
"""
import asyncio
import atexit
import logging
import queue
import threading
import warnings
import weakref
from typing import List, NamedTuple, Optional

log = logging.getLogger(__name__)

NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"      # 앱 → 모듈 (write)
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"      # 모듈 → 앱 (notify)


NUS_MAX_CHUNK = 244                                    # 펌웨어 NRF_SDH_BLE_GATT_MAX_MTU_SIZE(247) - 3

_loop_lock = threading.Lock()
_shared_loop: Optional[asyncio.AbstractEventLoop] = None


def shared_loop() -> asyncio.AbstractEventLoop:
    """BLE 전용 이벤트 루프 (프로그램이 끝날 때까지 하나만 쓴다).
    bleak 은 BlueZ(D-Bus) 연결을 처음 쓴 이벤트 루프에 묶어 두므로, 연결·검색마다 루프를 새로 만들었다 닫으면
    두 번째부터 연결·해제가 멈춘다. 그래서 스레드 하나를 만들어 계속 둔다."""
    global _shared_loop
    with _loop_lock:
        if _shared_loop is None or _shared_loop.is_closed():
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="ble-loop", daemon=True).start()
            _shared_loop = loop
        return _shared_loop


class BleFound(NamedTuple):
    name: str
    address: str
    rssi: Optional[int]


def scan_patch_sensors(name_prefix: str = "nFor", timeout: float = 5.0) -> List[BleFound]:
    """주변의 패치 센서 후보(이름이 name_prefix 로 시작하거나 NUS 서비스를 광고하는 장치)를 찾는다. 신호가 센 순.
    블로킹이므로 백그라운드 스레드에서 부른다. 실패하면 OSError."""
    try:
        from bleak import BleakScanner
    except ImportError as e:
        raise OSError("bleak is not installed") from e
    prefix = name_prefix.strip().lower()

    async def run():
        return await BleakScanner.discover(timeout=timeout, return_adv=True)

    try:
        found = asyncio.run_coroutine_threadsafe(run(), shared_loop()).result(timeout + 10.0)
    except Exception as e:
        raise OSError(_why(e)) from e
    out = []
    for dev, adv in found.values():
        name = dev.name or adv.local_name or ""
        nus = NUS_SERVICE in [u.lower() for u in (adv.service_uuids or [])]
        if nus or (prefix and name.lower().startswith(prefix)):
            out.append(BleFound(name, dev.address, adv.rssi))
    return sorted(out, key=lambda f: (-(f.rssi if f.rssi is not None else -200), f.name.lower()))


_OPEN: "weakref.WeakSet[BleNusTransport]" = weakref.WeakSet()       # 연결돼 있는 센서 (앱이 어떻게 끝나든 연결을 풀기 위해)


@atexit.register
def _disconnect_all() -> None:
    """정상 종료 경로(UartWorker.stop)를 못 거치고 끝날 때의 안전망: 열려 있는 BLE 센서의 연결을 푼다."""
    for t in list(_OPEN):
        try:
            t.close()
        except Exception:
            pass


def _why(e: BaseException) -> str:
    """오류 문구. 메시지가 비어 있는 예외(TimeoutError 등)도 종류가 보이게 한다."""
    text = str(e).strip()
    return f"{type(e).__name__}: {text}" if text else type(e).__name__


class BleNusTransport:
    def __init__(self, address: str = "", name_prefix: str = "nFor",
                 scan_timeout: float = 5.0, connect_timeout: float = 8.0):
        self.address, self.name_prefix = address.strip(), name_prefix.strip()
        self.scan_timeout, self.connect_timeout = scan_timeout, connect_timeout
        self.name = f"ble:{self.address or self.name_prefix + '*'}"
        self._rx: "queue.Queue[bytes]" = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._open_fut = None
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
        self._loop = shared_loop()
        try:
            self._open_fut = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
            self._open_fut.result(self.scan_timeout + self.connect_timeout + 2.0)
            _OPEN.add(self)
        except Exception as e:
            self.close()
            log.info("BLE: 열기 실패: %s", _why(e))
            raise OSError(str(e) if isinstance(e, OSError) and str(e) else _why(e)) from e
        finally:
            self._open_fut = None

    def cancel(self) -> None:
        """연결하는 중이면 중단한다 (다른 스레드에서 불러도 된다). 이미 연결됐으면 아무 일도 하지 않는다."""
        fut = self._open_fut
        if fut is not None and not fut.done():
            log.info("BLE: 연결 중단 요청")
            fut.cancel()

    def close(self) -> None:
        _OPEN.discard(self)
        loop, self._loop = self._loop, None
        client, self._client = self._client, None
        while not self._rx.empty():
            self._rx.get_nowait()
        if loop is None or client is None:
            return
        lost = self._lost.is_set()                        # 센서가 먼저 끊은 경우: 해제할 연결이 이미 없다
        try:
            asyncio.run_coroutine_threadsafe(client.disconnect(), loop).result(5.0)
            log.info("BLE: 연결 해제됨")
        except Exception as e:
            # 이미 끊긴 연결을 정리할 때 BlueZ(D-Bus) 쪽이 EOFError 등을 내는 것은 정상이다 → 경고로 올리지 않는다
            (log.debug if lost or isinstance(e, EOFError) else log.warning)("BLE: 연결 해제 실패: %s", _why(e))

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
            log.info("BLE: 쓰기 실패: %s", _why(e))
            raise OSError(_why(e)) from e

    # ---- bleak (전용 스레드) ----
    async def _find(self):
        """장치를 찾는다. 못 찾으면 주변에서 보인 장치를 오류 문구에 적어 원인을 알 수 있게 한다."""
        from bleak import BleakScanner
        target, prefix = self.address.upper(), self.name_prefix.lower()
        seen: dict = {}
        found: list = []
        got = asyncio.Event()

        def on_adv(d, adv):
            name = d.name or adv.local_name or ""
            seen[d.address] = (name, adv.rssi)
            if target:
                ok = d.address.upper() == target
            else:
                ok = (NUS_SERVICE in [u.lower() for u in (adv.service_uuids or [])]
                      or bool(prefix and name.lower().startswith(prefix)))
            if ok and not found:
                found.append(d)
                got.set()

        log.info("BLE: 센서 검색 시작 (%s, 최대 %.0f초)", target or self.name_prefix + "*", self.scan_timeout)
        try:
            async with BleakScanner(detection_callback=on_adv):
                try:
                    await asyncio.wait_for(got.wait(), self.scan_timeout)
                except asyncio.TimeoutError:
                    pass
        except Exception as e:
            raise OSError(f"BLE 검색을 시작하지 못함: {_why(e)}") from e
        if not found:
            top = sorted(seen.values(), key=lambda v: -(v[1] if v[1] is not None else -200))[:6]
            around = ", ".join(f"{n or '?'}({r}dBm)" for n, r in top)
            log.info("BLE: 센서를 찾지 못함. 주변 장치 %d개: %s", len(seen), around)
            raise OSError("센서를 찾지 못함 (" + (f"주변 BLE 장치 {len(seen)}개: {around}" if seen else
                          "BLE 신호가 하나도 안 보임 — 블루투스가 꺼졌거나 다른 검색이 진행 중일 수 있음") + ")")
        return found[0]

    def _on_disconnected(self, _client) -> None:
        log.info("BLE: 연결이 끊김")
        self._lost.set()

    async def _connect(self) -> None:
        from bleak import BleakClient
        dev = await self._find()
        log.info("BLE: 센서 발견 %s (%s), 연결 중…", dev.name, dev.address)
        client = BleakClient(dev, disconnected_callback=self._on_disconnected, timeout=self.connect_timeout)
        try:
            await client.connect()
        except BaseException as e:                        # 취소(CancelledError)도 포함: 반쯤 연결된 채로 두지 않는다
            try:
                await client.disconnect()
            except Exception:
                pass
            if isinstance(e, Exception):
                raise OSError(f"연결 실패: {_why(e)}") from e
            raise
        self._client = client
        uuids = [s.uuid.lower() for s in client.services]
        log.info("BLE: 연결됨. 서비스 %s", uuids)
        try:
            if NUS_SERVICE not in uuids:
                raise OSError("NUS 서비스(6e400001…)가 없음. 이 장치의 서비스: " + ", ".join(uuids))
            await client.start_notify(NUS_TX, self._on_notify)
        except Exception as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            self._client = None
            raise (e if isinstance(e, OSError) else OSError(f"알림(TX) 시작 실패: {_why(e)}")) from e
        mtu = await self._read_mtu(client)
        self._chunk = min(max(20, mtu - 3), NUS_MAX_CHUNK)
        log.info("ble sensor connected: %s (%s), mtu=%d, chunk=%d", dev.name, dev.address, mtu, self._chunk)

    def _on_notify(self, _char, data) -> None:
        log.debug("BLE RX %r", bytes(data))
        self._rx.put(bytes(data))

    @staticmethod
    async def _read_mtu(client) -> int:
        """협상된 ATT MTU. BlueZ 백엔드의 bleak 은 _acquire_mtu() 를 부르기 전에는 기본값(23)과 경고만 돌려준다.
        비공개 함수라 실패해도 연결은 계속한다 (기본값 → 20바이트씩 보낸다)."""
        acquire = getattr(getattr(client, "_backend", None), "_acquire_mtu", None)
        if acquire is not None:
            try:
                await acquire()
            except Exception as e:
                log.debug("ble mtu acquire failed: %s", e)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            return getattr(client, "mtu_size", 23) or 23

    async def _write(self, data: bytes) -> None:
        for i in range(0, len(data), self._chunk):
            await self._client.write_gatt_char(NUS_RX, data[i:i + self._chunk], response=False)
