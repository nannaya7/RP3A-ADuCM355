"""UART 송수신 워커. 전용 QThread 에서 수신 루프를 돌리고, 줄 단위로 GUI 에 전달한다.

전송 장치(Transport)는 실행 중에도 set_transport() 로 바꿀 수 있다 (설정의 내장 센서 / 패치 센서 전환).
None 이면 연결하지 않고 쉰다 (센서 꺼짐)."""
import logging
import queue
import threading
from typing import Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from .protocol import LineBuffer, check_cmd
from .transport import Transport

log = logging.getLogger(__name__)
RECONNECT_INTERVAL = 1.0  # 초
IDLE_INTERVAL = 0.2       # 전송 장치가 없을 때 바뀌었는지 확인하는 간격


class UartWorker(QObject):
    lineReceived = pyqtSignal(str)      # 펌웨어가 보낸 한 줄 (줄바꿈 제외, 원문)
    lineSent = pyqtSignal(str)          # 우리가 보낸 한 줄 (모니터링용. 줄바꿈 제외)
    connectionChanged = pyqtSignal(bool)
    errorOccurred = pyqtSignal(str)

    def __init__(self, transport: Optional[Transport]):
        super().__init__()
        self._transport = transport
        self._pending: Optional[tuple] = None          # (새 transport,) — 워커 스레드가 다음 반복에서 적용
        self._lock = threading.Lock()
        self._tx: "queue.Queue[bytes]" = queue.Queue()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lines = LineBuffer()
        self._connected = False
        self._thread: Optional[QThread] = None

    # ---- 수명 주기 -------------------------------------------------
    def start(self) -> None:
        """전용 스레드를 만들어 수신 루프를 시작한다."""
        self._stop.clear()
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)
        self._thread.start()

    def stop(self, timeout_ms: int = 3000) -> None:
        """루프를 멈추고 스레드를 정리한다 (GUI 스레드에서 호출)."""
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.quit()
            if not self._thread.wait(timeout_ms):
                log.warning("UART thread did not stop in time")
            self._thread = None

    def set_transport(self, transport: Optional[Transport]) -> None:
        """전송 장치를 바꾼다 (스레드 안전). 연결 중이면 닫고 새 장치로 다시 연결한다. None = 연결 안 함."""
        with self._lock:
            self._pending = (transport,)
        cancel = getattr(self._transport, "cancel", None)      # 연결하는 중이면 기다리지 않고 중단시킨다
        if callable(cancel):
            cancel()
        self._wake.set()

    @property
    def transport_name(self) -> str:
        t = self._transport
        return t.name if t is not None else ""

    # ---- 송신 (스레드 안전: 큐에 넣기만 한다) ------------------------
    def send_line(self, text: str) -> None:
        """명령 한 줄을 보낸다 (`\\r\\n` 은 여기서 붙인다)."""
        line = check_cmd(text)
        self._tx.put((line + "\r\n").encode("ascii"))
        self.lineSent.emit(line)

    # ---- 워커 스레드 -------------------------------------------------
    def _sleep(self, seconds: float) -> None:
        self._wake.wait(seconds)
        self._wake.clear()

    def _apply_pending(self) -> None:
        with self._lock:
            pending, self._pending = self._pending, None
        if pending is None:
            return
        if self._connected:
            self._close_quietly()
            self._connected = False
            self.connectionChanged.emit(False)
        self._drop_pending_tx()                         # 이전 장치로 보낼 명령이 새 장치로 가지 않게 한다
        self._transport = pending[0]
        log.info("UART transport changed: %s", self.transport_name or "(none)")

    @pyqtSlot()
    def _run(self) -> None:
        while not self._stop.is_set():
            self._apply_pending()
            t = self._transport
            if t is None:                               # 센서 꺼짐: 쉬면서 다시 켜지기를 기다린다
                self._sleep(IDLE_INTERVAL)
                continue
            if not self._connected:
                try:
                    t.open()
                except OSError as e:
                    if self._pending is None:                  # 장치를 바꾸려고 중단한 것이면 오류로 알리지 않는다
                        self.errorOccurred.emit(f"{t.name} 열기 실패: {e}")
                        self._sleep(RECONNECT_INTERVAL)
                    continue
                if self._pending is not None:           # 여는 동안 장치가 바뀌었다
                    try:
                        t.close()
                    except OSError:
                        pass
                    continue
                self._connected = True
                self._lines = LineBuffer()
                log.info("UART connected: %s", t.name)
                self.connectionChanged.emit(True)
            try:
                while True:  # 송신 큐 비우기
                    try:
                        data = self._tx.get_nowait()
                    except queue.Empty:
                        break
                    log.debug("TX %r", data)
                    t.write(data)
                rx = t.read()
                if rx:
                    log.debug("RX %r", rx)
                    for line in self._lines.feed(rx):
                        self.lineReceived.emit(line)
            except OSError as e:
                self.errorOccurred.emit(f"UART 오류: {e}")
                self._close_quietly()
                self._connected = False
                self._drop_pending_tx()  # 끊긴 동안의 명령이 재연결 후 늦게 실행되지 않게 한다
                self.connectionChanged.emit(False)
                self._sleep(RECONNECT_INTERVAL)
        if self._connected:
            self._close_quietly()
            self._connected = False
            self.connectionChanged.emit(False)

    def _drop_pending_tx(self) -> None:
        while True:
            try:
                self._tx.get_nowait()
            except queue.Empty:
                return

    def _close_quietly(self) -> None:
        try:
            if self._transport is not None:
                self._transport.close()
        except OSError:
            pass
