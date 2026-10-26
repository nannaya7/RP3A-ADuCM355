"""펌웨어 명령/응답 클라이언트 (GUI 스레드).

- 명령은 **한 번에 하나씩** 보내고 echo(`#I`)를 받은 뒤 다음 명령을 보낸다 (큐)
- 측정 중 `ERR` 를 받으면 즉시 `STOP` 을 보낸다 (펌웨어는 오류 후에도 같은 사이클을 재시도하므로)
- 측정 중 일정 시간 아무 줄도 안 오면 watchdog → `STOP`
- 모듈 재시작(부팅 배너), 연결 끊김은 진행 중 측정을 실패 처리
규격: docs/uart_protocol.md
"""
import logging
import re
from collections import deque
from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from . import protocol as p
from .uart_worker import UartWorker

log = logging.getLogger(__name__)

# 명령별 정상 응답: (허용 LEVEL, 메시지 정규식)
_EXPECT = {
    "SWEEP": (("INFO",), r"SWEEP set "),
    "CHAN": (("INFO",), r"CHMASK=0x"),
    "VERB": (("INFO",), r"VERB="),
    "SIGNAL": (("INFO",), r"SIGNAL set "),
    "RCAL": (("INFO",), r"RCAL set "),
    "STATUS": (("STATUS",), r"RUN="),
    "CALSTATUS": (("STATUS",), r"CAL VALID="),
    "ENV": (("INFO",), r"ENV TEMP_C="),
    "START": (("INFO",), r"measurement started"),
    "CAL": (("INFO",), r"calibration will be"),
}
# 명령 자체에 대한 오류 응답 (측정 중 발생하는 ERR 과 구분)
_CMD_ERR_PREFIXES = ("usage:", "unknown", "channel mask", "no channel", "command too long")
BANNER_PREFIX = "ADuCM355 3-wire bio-impedance"


@dataclass
class _Pending:
    text: str
    word: str


class FirmwareClient(QObject):
    recordReceived = pyqtSignal(object)        # 파싱된 레코드 (protocol.*Record)
    rawLine = pyqtSignal(str)                  # 원문 줄 (raw.log 용)
    parseError = pyqtSignal(str, str)          # (줄, 사유)
    commandFinished = pyqtSignal(str, bool, str)   # (명령 줄, 성공 여부, 메시지)
    measurementStarted = pyqtSignal()
    cycleDone = pyqtSignal(int)
    measurementStopped = pyqtSignal()
    measurementFailed = pyqtSignal(str)        # 재시작/연결 끊김/STOP 무응답
    firmwareError = pyqtSignal(str)            # 측정 중 ERR (자동 STOP 이 이어진다)
    watchdogExpired = pyqtSignal()
    moduleRestarted = pyqtSignal()
    connectionChanged = pyqtSignal(bool)

    def __init__(self, worker: UartWorker, cmd_timeout_ms: int = 1000,
                 start_timeout_ms: int = 3000, stop_timeout_ms: int = 2000,
                 watchdog_ms: int = 130000, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._worker = worker
        self._cmd_timeout = cmd_timeout_ms
        self._start_timeout = start_timeout_ms
        self._stop_timeout = stop_timeout_ms
        self._watchdog_ms = watchdog_ms
        self._queue: deque = deque()
        self._pending: Optional[_Pending] = None
        self._measuring = False
        self._stop_waiting = False
        self.connected = False
        self.status: dict = {}          # 마지막 STATUS 응답
        self.cal_status: dict = {}      # 마지막 CALSTATUS 응답
        self.last_env: Optional[dict] = None

        self._cmd_timer = QTimer(self)
        self._cmd_timer.setSingleShot(True)
        self._cmd_timer.timeout.connect(self._on_cmd_timeout)
        self._stop_timer = QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(self._on_stop_timeout)
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_watchdog)

        worker.lineReceived.connect(self._on_line)
        worker.connectionChanged.connect(self._on_connection)

    @property
    def measuring(self) -> bool:
        return self._measuring

    # ---- 공개 API ----------------------------------------------------------
    def send_command(self, text: str) -> None:
        """명령을 큐에 넣는다. 결과는 commandFinished 로 온다. STOP 은 큐를 거치지 않는다."""
        text = p.check_cmd(text)
        if text.upper().split()[0] == p.CMD_STOP:
            self.stop()
            return
        self._queue.append(text)
        self._pump()

    def set_sweep(self, start_hz: float, stop_hz: float, points: int) -> None:
        self.send_command(p.cmd_sweep(start_hz, stop_hz, points))

    def set_channels(self, channels) -> None:
        self.send_command(p.cmd_chan(channels))

    def set_verb(self, mode: str = "FULL") -> None:
        self.send_command(p.cmd_verb(mode))

    def query_status(self) -> None:
        self.send_command(p.CMD_STATUS)

    def query_cal_status(self) -> None:
        self.send_command(p.CMD_CALSTATUS)

    def query_env(self) -> None:
        self.send_command(p.CMD_ENV)

    def start(self, cycles: int = 1) -> None:
        self.send_command(p.cmd_start(cycles))

    def stop(self) -> None:
        """즉시 STOP. 실행 중이 아니면 펌웨어가 응답하지 않으므로 타임아웃을 정상으로 본다."""
        self._worker.send_line(p.CMD_STOP)
        self._stop_waiting = True
        self._stop_timer.start(self._stop_timeout)

    # ---- 명령 큐 -------------------------------------------------------------
    def _pump(self) -> None:
        if self._pending is not None or not self._queue or not self.connected:
            return
        text = self._queue.popleft()
        word = text.upper().split()[0]
        self._pending = _Pending(text, word)
        self._worker.send_line(text)
        self._cmd_timer.start(self._start_timeout if word == "START" else self._cmd_timeout)

    def _finish(self, ok: bool, msg: str) -> None:
        pend, self._pending = self._pending, None
        self._cmd_timer.stop()
        if pend is not None:
            self.commandFinished.emit(pend.text, ok, msg)
        self._pump()

    def _fail_all(self, reason: str) -> None:
        if self._pending is not None:
            self._finish(False, reason)
        while self._queue:
            self.commandFinished.emit(self._queue.popleft(), False, reason)

    def _on_cmd_timeout(self) -> None:
        if self._pending is not None:
            self._finish(False, "응답 시간 초과")

    # ---- 수신 처리 -----------------------------------------------------------
    def _on_line(self, line: str) -> None:
        self.rawLine.emit(line)
        if self._measuring:
            self._watchdog.start(self._watchdog_ms)
        try:
            rec = p.parse_line(line)
        except p.ParseError as e:
            self.parseError.emit(line, str(e))
            return
        if rec is None:
            return
        self.recordReceived.emit(rec)
        if isinstance(rec, p.InfoRecord):
            self._on_info(rec)

    def _on_info(self, rec: p.InfoRecord) -> None:
        msg, level = rec.msg, rec.level
        if level == "INFO" and msg.startswith(BANNER_PREFIX):
            self._on_restart()
            return
        if level == "INFO" and msg.startswith("measurement started"):
            self._measuring = True
            self._watchdog.start(self._watchdog_ms)
            self.measurementStarted.emit()
        elif level == "INFO" and msg.startswith("measurement stopped"):
            self._on_stopped()
        elif level == "INFO" and (m := re.match(r"CYCLE=(\d+) done", msg)):
            self.cycleDone.emit(int(m.group(1)))
        elif level == "ERR" and not msg.startswith(_CMD_ERR_PREFIXES):
            self._on_firmware_error(msg)
            return
        self._match_pending(rec)

    def _match_pending(self, rec: p.InfoRecord) -> None:
        pend = self._pending
        if pend is None:
            return
        if rec.level == "ERR" and rec.msg.startswith(_CMD_ERR_PREFIXES):
            self._finish(False, rec.msg)
            return
        if pend.word == "ENV" and rec.level == "WARN" and rec.msg.startswith("ENV not available"):
            self.last_env = None
            self._finish(False, rec.msg)
            return
        spec = _EXPECT.get(pend.word)
        if spec is None:       # 목록에 없는 명령(MODE, RTIA …): 첫 INFO/STATUS 를 응답으로 본다
            if rec.level in ("INFO", "STATUS"):
                self._finish(True, rec.msg)
            return
        levels, rx = spec
        if rec.level in levels and re.match(rx, rec.msg):
            kv = p.parse_kv(rec.msg)
            if pend.word == "STATUS":
                self.status = kv
            elif pend.word == "CALSTATUS":
                self.cal_status = kv
            elif pend.word == "ENV":
                self.last_env = {"temp_c": float(kv["TEMP_C"]), "hum_rh": float(kv["HUM_RH"])}
            self._finish(True, rec.msg)

    # ---- 상태 전이 -----------------------------------------------------------
    def _on_stopped(self) -> None:
        was = self._measuring or self._stop_waiting
        self._measuring = False
        self._watchdog.stop()
        if self._stop_waiting:
            self._stop_waiting = False
            self._stop_timer.stop()
            self.commandFinished.emit(p.CMD_STOP, True, "stopped")
        if was:
            self.measurementStopped.emit()

    def _on_stop_timeout(self) -> None:
        self._stop_waiting = False
        if self._measuring:
            self._measuring = False
            self._watchdog.stop()
            self.commandFinished.emit(p.CMD_STOP, False, "STOP 응답 없음")
            self.measurementFailed.emit("STOP 응답 없음")
        else:
            self.commandFinished.emit(p.CMD_STOP, True, "실행 중이 아님")

    def _on_firmware_error(self, msg: str) -> None:
        log.warning("firmware error: %s", msg)
        self.firmwareError.emit(msg)
        if self._measuring and not self._stop_waiting:
            self.stop()

    def _on_watchdog(self) -> None:
        if not self._measuring:
            return
        log.warning("no data received for %d ms during measurement", self._watchdog_ms)
        self.watchdogExpired.emit()
        if not self._stop_waiting:
            self.stop()

    def _on_restart(self) -> None:
        self._fail_all("모듈 재시작")
        self._stop_waiting = False
        self._stop_timer.stop()
        if self._measuring:
            self._measuring = False
            self._watchdog.stop()
            self.measurementFailed.emit("모듈 재시작")
        self.moduleRestarted.emit()

    def _on_connection(self, ok: bool) -> None:
        self.connected = ok
        if not ok:
            self._fail_all("연결 끊김")
            self._stop_waiting = False
            self._stop_timer.stop()
            if self._measuring:
                self._measuring = False
                self._watchdog.stop()
                self.measurementFailed.emit("연결 끊김")
        else:
            self._pump()
        self.connectionChanged.emit(ok)
