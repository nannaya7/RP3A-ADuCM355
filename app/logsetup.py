"""시작할 때의 콘솔 출력 정리: 로그 수준, 실행 폴더 권한 경고, 무해한 Qt 경고 걸러내기."""
import logging
import os
import sys

# 동작에 영향이 없는데 터미널을 어지럽히는 Qt 메시지 (부분 일치)
HARMLESS_QT = (
    "Wayland does not support QWindow::requestActivate",       # 전체화면 창을 앞으로 가져오려는 요청 (Wayland 는 지원 안 함)
    "wrong permissions on runtime directory",                  # fix_runtime_dir() 로 고치지만, 못 고친 경우에도 한 줄만 남기지 않는다
)
LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}


def level_from(name: str, verbose: int = 0) -> int:
    """설정/명령줄의 수준 이름 → logging 수준. -v 는 info, -vv 는 debug."""
    if verbose >= 2:
        return logging.DEBUG
    if verbose == 1:
        return logging.INFO
    return LEVELS.get((name or "").strip().lower(), logging.WARNING)


def setup_logging(level: int) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)


def fix_runtime_dir() -> bool:
    """XDG_RUNTIME_DIR 이 내 소유인데 권한이 0700 이 아니면 0700 으로 고친다. (Qt 가 'wrong permissions' 경고를 내는 원인)

    SSH/VNC 로 접속하면 이 폴더가 0770 으로 바뀌어 있는 경우가 있다. 내 소유 폴더만 고친다. 고쳤으면 True."""
    d = os.environ.get("XDG_RUNTIME_DIR")
    if not d or os.name != "posix":
        return False
    try:
        st = os.stat(d)
        if st.st_uid != os.getuid() or (st.st_mode & 0o777) == 0o700:
            return False
        os.chmod(d, 0o700)
        return True
    except OSError:
        return False


def is_harmless(msg: str) -> bool:
    return any(p in msg for p in HARMLESS_QT)


def install_qt_filter() -> None:
    """Qt 의 qWarning 중 HARMLESS_QT 에 해당하는 것만 숨기고, 나머지는 그대로 stderr 로 보낸다."""
    from PyQt5.QtCore import QtMsgType, qInstallMessageHandler

    def handler(mode, _ctx, msg):
        if is_harmless(msg):
            return
        label = {QtMsgType.QtDebugMsg: "debug", QtMsgType.QtWarningMsg: "warning", QtMsgType.QtCriticalMsg: "critical",
                 QtMsgType.QtFatalMsg: "fatal"}.get(mode, "info")
        if mode == QtMsgType.QtDebugMsg and logging.getLogger().level > logging.DEBUG:
            return                                      # Qt 디버그 메시지는 -vv 일 때만
        print(f"Qt {label}: {msg}", file=sys.stderr)

    qInstallMessageHandler(handler)
