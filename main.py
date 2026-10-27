import argparse
import logging
import sys
import threading
from dataclasses import replace
from pathlib import Path

try:                                    # 업데이트 직후 계속 죽으면 이전 버전으로 되돌린다 (다른 import 보다 먼저, 실패해도 무시)
    from app.update.guard import on_startup as _update_guard
    _update_guard(Path(__file__).resolve().parent)
except Exception:
    pass

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

from app.config import load_config
from app.display import pick_screen, select_profile
from app.logsetup import fix_runtime_dir, install_qt_filter, level_from, setup_logging
from app.ui.splash import StartupSplash
from app.ui.theme import load_fonts, load_stylesheet


def _preload() -> None:
    """화면이 뜬 뒤 백그라운드에서 미리 불러 둔다 → 처음 쓸 때(검사 계산, 업데이트 확인) 멈칫하지 않는다."""
    try:
        import app.models.troponin  # noqa: F401  (numpy)
        import app.update.updater  # noqa: F401  (urllib/ssl/tarfile)
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="모듈 없이 가상 펌웨어로 실행")
    ap.add_argument("--profile", choices=("auto", "landscape", "portrait"), help="화면 방향 프로파일 (설정 파일보다 우선)")
    ap.add_argument("--screen", help="사용할 화면 이름 (설정 파일보다 우선)")
    ap.add_argument("-v", "--verbose", action="count", default=0, help="자세한 로그 (-v: 정보, -vv: 디버그)")
    args, qt_args = ap.parse_known_args()
    cfg = load_config()
    setup_logging(level_from(cfg.log_level, args.verbose))      # 기본은 경고 이상만 (연결/화면 선택 같은 정보 줄은 숨김)
    fix_runtime_dir()                                          # "wrong permissions on runtime directory" 경고의 원인을 고친다
    install_qt_filter()
    if args.mock:
        cfg = replace(cfg, uart_mock=True, net_mock=True)
    if args.profile:
        cfg = replace(cfg, display_profile=args.profile)
    if args.screen:
        cfg = replace(cfg, screen=args.screen)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication([sys.argv[0]] + qt_args)
    app.setStyle("Fusion")
    load_fonts()
    app.setFont(QFont("Pretendard", 10))
    app.setStyleSheet(load_stylesheet())
    screen, warn = pick_screen(app.screens(), app.primaryScreen(), cfg.screen)
    if warn:
        logging.getLogger("main").warning(warn)
    profile = select_profile(cfg.display_profile, screen.size())
    splash = StartupSplash(profile.size, cfg.fullscreen, screen)     # 무거운 불러오기·화면 만들기 동안 먼저 보여 준다
    app.processEvents()
    from app.app_window import AppWindow                             # 가장 오래 걸리는 import 는 스플래시를 띄운 뒤에
    win = AppWindow(profile, cfg)
    win.move(screen.geometry().topLeft())            # 지정한 화면으로 (전체화면도 그 화면에서 열린다)
    try:
        win.winId()
        win.windowHandle().setScreen(screen)         # Wayland 에서는 move 만으로 화면이 정해지지 않을 수 있다
    except (AttributeError, RuntimeError):
        pass
    app.aboutToQuit.connect(win.shutdown)
    win.start_uart()
    if cfg.fullscreen:
        win.showFullScreen()
    else:
        win.show()
    app.processEvents()
    splash.close()
    threading.Thread(target=_preload, name="preload", daemon=True).start()
    # 아래가 잘릴 때 원인을 찾기 위한 정보: 화면(전체/사용 가능), 창 크기·위치. 보려면 python3 main.py -v
    log = logging.getLogger("main")
    log.info("screen %s size=%s available=%s", screen.name(), screen.size(), screen.availableGeometry())
    log.info("window fullscreen=%s size=%s pos=%s bottom_margin=%s", cfg.fullscreen, win.size(), win.pos(),
             win.contentsMargins().bottom())
    # 터미널의 Ctrl+C 로 깨끗이 끝낸다 (그대로 두면 Qt 슬롯 안에서 KeyboardInterrupt 가 나 "Qt fatal" 로 비정상 종료한다).
    # 파이썬 시그널 처리기는 이벤트 루프가 파이썬 코드를 실행할 때만 돌므로 타이머로 주기적으로 깨운다.
    import signal
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    wake = QTimer()
    wake.start(300)
    wake.timeout.connect(lambda: None)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
