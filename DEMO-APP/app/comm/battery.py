"""배터리 상태 확인 (UPS). 유선 UART 로 `AT+BATT` 를 1분마다 보내 `AT+BATT,4.15V,95%` 응답을 읽는다.

- 측정 중(확인·구성·측정·중지·계산)에는 보내지 않는다. 측정이 끝나면 밀린 확인을 바로 한다.
- 유선 UART(내장 센서)일 때만 보낸다. 패치 센서(BLE)로는 보내지 않는다.
- 값을 아직 모르는 동안(앱 시작 직후, 응답 없음)은 3초마다 다시 확인하고, 값이 생기면 1분 간격으로 돌아간다.
- 응답이 오지 않으면 직전 값을 유지하다가, 연속 MISS_LIMIT 번 실패하면 "알 수 없음"으로 바꾼다.
"""
import re
from typing import Callable, Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

CMD_BATT = "AT+BATT"
INTERVAL_MS = 60_000          # 확인 간격: 1분
FAST_RETRY_MS = 3_000         # 값을 아직 모를 때(앱 시작 직후, 응답 없음)는 이 간격으로 다시 확인한다
REPLY_TIMEOUT_MS = 3_000      # 응답을 기다리는 시간
MISS_LIMIT = 3
_RX = re.compile(r"^AT\+BATT,\s*([0-9.]+)\s*V,\s*(\d{1,3})\s*%$", re.IGNORECASE)


def parse_batt(line: str) -> Optional[tuple]:
    """`AT+BATT,4.15V,95%` → (4.15, 95). 형식이 다르면 None."""
    m = _RX.match(line.strip())
    if not m:
        return None
    return float(m.group(1)), max(0, min(100, int(m.group(2))))


def level_of(pct: Optional[int]) -> int:
    """아이콘 단계 0~4 (0 = 알 수 없음). 75% 이상 4, 50% 이상 3, 25% 이상 2, 그 아래 1."""
    if pct is None:
        return 0
    return 4 if pct >= 75 else 3 if pct >= 50 else 2 if pct >= 25 else 1


class BatteryMonitor(QObject):
    changed = pyqtSignal(object, object)       # (전압 V, 잔량 %) — 알 수 없으면 (None, None)

    def __init__(self, send: Callable[[str], None], allowed: Callable[[], bool], parent=None,
                 interval_ms: int = INTERVAL_MS, reply_timeout_ms: int = REPLY_TIMEOUT_MS,
                 fast_retry_ms: int = FAST_RETRY_MS, link_ok: Optional[Callable[[], bool]] = None):
        super().__init__(parent)
        self._send = send
        self._allowed = allowed                # 지금 보내도 되는가 (유선 UART 연결 + 측정 중 아님)
        self._link_ok = link_ok or allowed     # 시작 확인용: 유선 UART 가 연결돼 있는가 (검사 상태는 보지 않는다)
        self._start_cbs: list = []             # check_now 로 기다리는 중인 콜백
        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.timeout.connect(self._flush_start)
        self._due = True                       # 확인할 차례가 되었는데 아직 못 보냈다
        self._waiting = False
        self._misses = 0
        self.volt: Optional[float] = None
        self.pct: Optional[int] = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(interval_ms)
        self._fast = QTimer(self)               # 값이 없는 동안만 짧은 간격으로 재시도 (시작하자마자 수치가 보이게)
        self._fast.timeout.connect(self._retry_unknown)
        self._fast.start(fast_retry_ms)
        self._reply_timer = QTimer(self)
        self._reply_timer.setSingleShot(True)
        self._reply_timer.setInterval(reply_timeout_ms)
        self._reply_timer.timeout.connect(self._on_timeout)

    # ---- 바깥에서 부르는 것 ----
    def poke(self) -> None:
        """상태가 바뀌었을 때(연결됨, 측정 끝남 등) 호출: 밀린 확인이 있으면 지금 한다."""
        if self._due:
            self._query()

    def check_now(self, done: Callable[[], None], timeout_ms: int = 1500) -> None:
        """모듈 확인(ENV) 전에 배터리부터 확인한다: 응답이 오거나 timeout_ms 가 지나면 done() 을 부른다.
        유선 UART 가 아니면(패치 센서·연결 없음) 바로 done() 을 부른다."""
        if not self._link_ok():
            done()
            return
        self._start_cbs.append(done)
        self._start_timer.start(timeout_ms)
        self._due = True
        self._query(force=True)

    def reset(self) -> None:
        """연결이 끊기거나 센서가 바뀌었다: 값을 알 수 없음으로 되돌리고 다시 연결되면 바로 확인한다."""
        self._reply_timer.stop()
        self._waiting = False
        self._misses = 0
        self._due = True
        self._set(None, None)
        self._flush_start()

    def on_line(self, line: str) -> None:
        if not line.startswith("AT+BATT"):
            return
        parsed = parse_batt(line)
        if parsed is None:
            return
        self._reply_timer.stop()
        self._waiting = False
        self._misses = 0
        self._set(*parsed)
        self._flush_start()

    # ---- 내부 ----
    def _retry_unknown(self) -> None:
        if self.pct is None:
            self._due = True
            self._query()

    def _tick(self) -> None:
        self._due = True
        self._query()

    def _flush_start(self) -> None:
        self._start_timer.stop()
        cbs, self._start_cbs = self._start_cbs, []
        for cb in cbs:
            cb()

    def _query(self, force: bool = False) -> None:
        if self._waiting or not (self._link_ok() if force else self._allowed()):
            return                             # 못 보내면 _due 를 남겨 두고 poke() 때 다시 시도한다
        self._due = False
        self._waiting = True
        self._reply_timer.start()
        try:
            self._send(CMD_BATT)
        except (ValueError, OSError):
            self._waiting = False
            self._reply_timer.stop()
            self._flush_start()

    def _on_timeout(self) -> None:
        self._waiting = False
        self._misses += 1
        if self._misses >= MISS_LIMIT:
            self._set(None, None)

    def _set(self, volt, pct) -> None:
        if (volt, pct) != (self.volt, self.pct):
            self.volt, self.pct = volt, pct
            self.changed.emit(volt, pct)
