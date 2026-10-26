import argparse
import logging
import sys
from dataclasses import replace

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

from app.app_window import AppWindow
from app.config import load_config
from app.display import pick_screen, select_profile
from app.logsetup import fix_runtime_dir, install_qt_filter, level_from, setup_logging
from ui.theme import load_fonts, load_stylesheet


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
    # 아래가 잘릴 때 원인을 찾기 위한 정보: 화면(전체/사용 가능), 창 크기·위치. 보려면 python3 main.py -v
    log = logging.getLogger("main")
    log.info("screen %s size=%s available=%s", screen.name(), screen.size(), screen.availableGeometry())
    log.info("window fullscreen=%s size=%s pos=%s bottom_margin=%s", cfg.fullscreen, win.size(), win.pos(),
             win.contentsMargins().bottom())
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
