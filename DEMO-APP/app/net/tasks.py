"""블로킹 함수(nmcli/bluetoothctl 호출)를 백그라운드 스레드에서 실행하고, 결과를 GUI 스레드로 돌려준다."""
from typing import Callable

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from .errors import NetError


class _Signals(QObject):
    finished = pyqtSignal(object, str)      # (결과, 오류 문구 — 성공이면 "")


class _Job(QRunnable):
    def __init__(self, fn: Callable, signals: _Signals):
        super().__init__()
        self._fn, self._sig = fn, signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result, err = self._fn(), ""
        except NetError as e:
            result, err = None, str(e) or "실패했습니다."
        except Exception as e:                       # 예상 못한 오류도 화면에는 문구로만 알린다
            result, err = None, f"오류: {e}"
        self._sig.finished.emit(result, err)


class TaskRunner(QObject):
    """submit(fn, on_done) — on_done(result, error) 은 GUI 스레드에서 불린다. 한 번에 하나씩 순서대로 실행한다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._live = set()

    def submit(self, fn: Callable, on_done: Callable) -> None:
        sig = _Signals()
        self._live.add(sig)

        def done(result, err, sig=sig):
            self._live.discard(sig)
            on_done(result, err)

        sig.finished.connect(done)
        self._pool.start(_Job(fn, sig))

    def wait(self, ms: int = 5000) -> bool:
        return self._pool.waitForDone(ms)
