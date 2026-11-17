"""UART 로 주고받은 줄을 시간순으로 기록한다 (모니터링 화면용).

앱이 켜져 있는 동안 항상 기록하므로, 화면을 나중에 열어도 그 전의 송수신 내용을 볼 수 있다.
오래된 것부터 버리는 링 버퍼(기본 5000줄)라 메모리가 무한히 늘지 않는다.
"""
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

MAX_TEXT = 300           # 한 줄 최대 길이 (잡음으로 아주 긴 줄이 와도 화면이 느려지지 않게)

TX, RX, SYS = "tx", "rx", "sys"


@dataclass(frozen=True)
class Entry:
    t: float             # 앱 시작(로그 생성) 후 경과 초
    kind: str            # tx(보냄) / rx(받음) / sys(연결·오류)
    text: str

    @property
    def is_data(self) -> bool:
        """측정점 레코드(#D …). 스윕 중 매우 많이 오므로 따로 숨길 수 있게 구분한다."""
        return self.kind == RX and self.text.startswith("#D")

    @property
    def is_error(self) -> bool:
        return self.kind == SYS or (self.kind == RX and self.text.upper().startswith("ERR"))


ARROW = {TX: "→", RX: "←", SYS: "•"}


def format_entry(e: Entry) -> str:
    return f"{e.t:9.3f} {ARROW[e.kind]} {e.text}"


class TrafficLog(QObject):
    entryAdded = pyqtSignal(object)      # Entry
    cleared = pyqtSignal()

    def __init__(self, worker=None, maxlen: int = 5000, clock: Callable[[], float] = time.monotonic):
        super().__init__()
        self._entries: Deque[Entry] = deque(maxlen=maxlen)
        self._clock = clock
        self._t0 = clock()
        self.tx_count = 0
        self.rx_count = 0
        self.connected: Optional[bool] = None
        if worker is not None:
            self.attach(worker)

    def attach(self, worker) -> None:
        """UartWorker 의 신호를 연결한다. (수신/오류 신호는 워커 스레드에서 오지만 큐로 GUI 스레드에서 처리된다.)"""
        worker.lineReceived.connect(self.on_rx)
        worker.lineSent.connect(self.on_tx)
        worker.connectionChanged.connect(self._on_connection)
        worker.errorOccurred.connect(self.on_sys)

    # ---- 기록 ----
    def _add(self, kind: str, text: str) -> None:
        text = text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + f"… (+{len(text) - MAX_TEXT}자)"
        e = Entry(self._clock() - self._t0, kind, text)
        self._entries.append(e)
        self.entryAdded.emit(e)

    def on_tx(self, text: str) -> None:
        self.tx_count += 1
        self._add(TX, text)

    def on_rx(self, text: str) -> None:
        self.rx_count += 1
        self._add(RX, text)

    def on_sys(self, text: str) -> None:
        self._add(SYS, text)

    def _on_connection(self, up: bool) -> None:
        self.connected = up
        self._add(SYS, "UART 연결됨" if up else "UART 연결 끊김")

    # ---- 조회 ----
    def entries(self) -> List[Entry]:
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()
        self.tx_count = self.rx_count = 0
        self.cleared.emit()

    def save(self, path) -> Path:
        """현재 기록 전체를 텍스트 파일로 저장한다 (개발자에게 보낼 때 사용)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("# 시간(초) 방향(→보냄 ←받음 •상태) 내용\n")
            for e in self._entries:
                f.write(format_entry(e) + "\n")
        return path
