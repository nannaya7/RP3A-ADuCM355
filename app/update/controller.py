"""업데이트 화면과 updater 를 잇는 컨트롤러. 네트워크·설치는 백그라운드 스레드에서 하고 결과만 GUI 로 돌려준다.

상태: idle → checking → (uptodate | available | error) → downloading → installing → installed(재시작) | error
설치는 사용자가 버튼으로만 시작한다. 검사 중에는 확인도 설치도 하지 않는다 (blocked 가 이유 문구를 돌려준다).
"""
import logging
import os
import sys
from pathlib import Path
from typing import Callable, Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from app.net.errors import NetError
from app.net.tasks import TaskRunner
from app.version import VERSION

from . import guard, updater

log = logging.getLogger(__name__)

IDLE, CHECKING, UPTODATE, AVAILABLE, DOWNLOADING, INSTALLED, ERROR = (
    "idle", "checking", "uptodate", "available", "downloading", "installed", "error")


def restart_process() -> None:
    """같은 명령으로 앱을 다시 시작한다 (프로세스를 교체)."""
    os.execv(sys.executable, [sys.executable] + sys.argv)


class UpdateController(QObject):
    stateChanged = pyqtSignal(str, str)         # (상태, 화면에 보여 줄 문구)
    availabilityChanged = pyqtSignal(bool)      # 설치 가능한 새 버전이 있는지 (톱니바퀴 점 표시용)

    def __init__(self, cfg, root: Path, blocked: Callable[[], str] = lambda: "",
                 restart: Callable[[], None] = restart_process, restart_delay_ms: int = 1500, parent=None):
        super().__init__(parent)
        self.cfg, self.root = cfg, Path(root)
        self.blocked, self._restart, self._delay = blocked, restart, restart_delay_ms
        self.current = VERSION
        self.manifest: Optional[updater.Manifest] = None
        self.state = IDLE
        self._runner = TaskRunner(self)

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.update_url)

    @property
    def available(self) -> bool:
        return self.manifest is not None

    def _set(self, state: str, text: str = "") -> None:
        self.state = state
        self.stateChanged.emit(state, text)

    # ---- 확인 ----
    def check(self, silent: bool = False) -> None:
        if self.state in (CHECKING, DOWNLOADING, INSTALLED):
            return
        if not self.enabled:
            if not silent:
                self._set(ERROR, "업데이트 서버가 설정되어 있지 않습니다. (config.ini [update] url)")
            return
        why = self.blocked()
        if why:
            if not silent:
                self._set(ERROR, why)
            return
        if not silent:
            self._set(CHECKING, "새 버전을 확인하는 중…")
        cfg = self.cfg

        def work():
            try:
                return updater.fetch_manifest(cfg.update_url, cfg.update_token)
            except updater.UpdateError as e:
                raise NetError(str(e))

        self._runner.submit(work, lambda m, err: self._checked(m, err, silent))

    def _checked(self, m, err: str, silent: bool) -> None:
        if err:
            log.info("update check failed: %s", err)
            if not silent:
                self._set(ERROR, err)
            return
        if updater.is_newer(m.version, self.current):
            self.manifest = m
            self.availabilityChanged.emit(True)
            self._set(AVAILABLE, f"새 버전 {m.version} 을(를) 설치할 수 있습니다." + (f"\n{m.notes}" if m.notes else ""))
        else:
            self.manifest = None
            self.availabilityChanged.emit(False)
            if not silent:
                self._set(UPTODATE, "최신 버전입니다.")

    # ---- 설치 ----
    def install(self) -> None:
        m = self.manifest
        if m is None or self.state in (DOWNLOADING, INSTALLED, CHECKING):
            return
        why = self.blocked()
        if why:
            self._set(ERROR, why)
            return
        cfg, root = self.cfg, self.root
        self._set(DOWNLOADING, f"{m.version} 을(를) 내려받아 설치하는 중… 전원을 끄지 마세요.")

        def work():
            try:
                updater.verify_signature(m, required=cfg.update_require_signature)
                archive = updater.download(m, guard.update_dir(root) / "download", cfg.update_token)
                updater.install(archive, root, m.version)
                return m.version
            except updater.UpdateError as e:
                raise NetError(str(e))

        self._runner.submit(work, self._installed)

    def _installed(self, version, err: str) -> None:
        if err:
            self._set(ERROR, err)
            return
        self.manifest = None
        self.availabilityChanged.emit(False)
        self._set(INSTALLED, f"{version} 설치 완료. 잠시 후 앱이 다시 시작됩니다.")
        QTimer.singleShot(self._delay, self._restart)

    def wait(self, ms: int = 5000) -> bool:
        return self._runner.wait(ms)
