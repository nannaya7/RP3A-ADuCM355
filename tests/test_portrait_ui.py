"""세로(480x800) 화면: 로그인, 측정, 터치 키보드와 해상도 선택 연결."""
import dataclasses

import pytest
from PyQt5.QtGui import QFont
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QPushButton

from app.app_window import AppWindow
from app.config import Config, load_config
from app.display import LANDSCAPE, PORTRAIT
from ui.theme import load_fonts, load_stylesheet

app = QApplication.instance()


@pytest.fixture(scope="module", autouse=True)
def styled():
    load_fonts()
    app.setFont(QFont("Pretendard", 10))
    app.setStyleSheet(load_stylesheet())
    yield
    app.setStyleSheet("")


def make(profile, **kw):
    cfg = dataclasses.replace(Config(), uart_mock=True, **kw)
    win = AppWindow(profile, cfg)
    win.show()
    QTest.qWait(80)
    return win


def bottom_in_window(win, widget) -> int:
    return widget.mapTo(win, widget.rect().bottomLeft()).y()


def test_portrait_login_fits_inside_480x800():
    win = make(PORTRAIT)
    try:
        assert (win.width(), win.height()) == (480, 800)
        lg = win.login
        assert lg.hero is not None and lg.hero.isVisible() and lg.hero.height() > 200   # 위쪽 사진
        for w in (lg.headline, lg.roles, lg.email, lg.password, lg.login_btn, lg.skip_btn, lg.logo):
            assert w.isVisible()
            assert 0 <= w.mapTo(win, w.rect().topLeft()).x() and w.mapTo(win, w.rect().topRight()).x() <= 480
            assert bottom_in_window(win, w) <= 800
        assert lg.login_btn.height() >= 48 and lg.email.frame.height() >= 48          # 터치 크기
        # 로고는 위쪽 사진의 좌측 상단에 얹혀 있다 (레이아웃 밖이라 다른 요소의 위치에 영향이 없다)
        assert lg.logo.parent() is lg.hero
        pos = lg.logo.mapTo(win, lg.logo.rect().topLeft())
        assert (pos.x(), pos.y()) == (20, 18)
        # 로그인(3) : 건너뛰기(2) 가 한 줄에, 같은 높이로 나란히 있다. 글씨는 '건너뛰기' (개발용 표기 없음)
        assert lg.skip_btn.text() == "건너뛰기"
        assert lg.login_btn.mapTo(win, lg.login_btn.rect().topLeft()).y() == lg.skip_btn.mapTo(win, lg.skip_btn.rect().topLeft()).y()
        assert lg.login_btn.height() == lg.skip_btn.height() == 52
        assert lg.login_btn.mapTo(win, lg.login_btn.rect().topLeft()).x() < lg.skip_btn.mapTo(win, lg.skip_btn.rect().topLeft()).x()
        assert abs(lg.login_btn.width() / lg.skip_btn.width() - 1.5) < 0.05                 # 3 : 2
        assert lg.skip_btn.mapTo(win, lg.skip_btn.rect().topRight()).x() <= 480 - 19      # 오른쪽 여백 안
        assert [t for _, t in lg.roles._tabs] == ["일반 회원", "의료진", "의료기관"]
    finally:
        win.shutdown()


def test_portrait_keyboard_folds_photo_and_keeps_form_visible():
    win = make(PORTRAIT)
    try:
        lg = win.login
        lg.email.edit.setFocus()
        QTest.qWait(80)
        kb = win.keyboard
        assert kb.isVisible() and not lg.hero.isVisible() and not lg.logo.isVisible()
        top = kb.geometry().top()
        for w in (lg.email, lg.password, lg.login_btn, lg.skip_btn):                   # 키보드에 가려지지 않는다
            assert bottom_in_window(win, w) <= top, w
        assert lg.headline.mapTo(win, lg.headline.rect().topLeft()).y() >= 0
        kb.press("<done>")                                                              # 닫으면 사진이 돌아온다
        QTest.qWait(50)
        assert not kb.isVisible() and lg.hero.isVisible() and lg.logo.isVisible()
    finally:
        win.shutdown()


def test_portrait_keyboard_is_compact_and_fits_width():
    win = make(PORTRAIT)
    try:
        win.login.email.edit.setFocus()
        QTest.qWait(80)
        kb = win.keyboard
        assert kb.property("compact") is True and kb.width() == 480
        keys = [b for b in kb.findChildren(QPushButton) if b.isVisible()]
        assert keys and all(b.mapTo(kb, b.rect().topRight()).x() <= 480 for b in keys)       # 모든 키가 폭 안에
        letters = [b for b in keys if len(b.text()) == 1 and b.text().isdigit()]
        assert len(letters) == 10 and min(b.width() for b in letters) >= 36             # 숫자 줄 키 폭(백스페이스 1.5배 포함)
    finally:
        win.shutdown()


def test_landscape_login_is_unchanged():
    win = make(LANDSCAPE)
    try:
        assert win.login.hero is None and (win.width(), win.height()) == (1280, 800)
        assert win.keyboard.property("compact") is False
        win.login.email.edit.setFocus()
        QTest.qWait(50)
        win.login.on_keyboard(True, 335)                    # 가로는 접지 않는다
    finally:
        win.shutdown()


def test_portrait_without_skip_button_login_takes_full_width():
    win = make(PORTRAIT, skip_login=False)
    try:
        assert win.login.skip_btn is None
        assert win.login.login_btn.width() >= 430                                          # 건너뛰기가 없으면 전폭
    finally:
        win.shutdown()


def test_config_defaults_to_auto_and_reads_screen(tmp_path):
    assert Config().display_profile == "auto" and Config().screen == ""
    ini = tmp_path / "c.ini"
    ini.write_text("[display]\nprofile = auto\nscreen = DSI-1\n", encoding="utf-8")
    c = load_config(ini)
    assert c.display_profile == "auto" and c.screen == "DSI-1"
    assert load_config(tmp_path / "missing.ini").display_profile == "auto"


def test_landscape_login_buttons_side_by_side():
    from ui.login_page import LoginPage
    lg = LoginPage(show_skip=True, portrait=False)
    lg.resize(1280, 800)
    lg.show()
    assert lg.skip_btn.text() == "건너뛰기"
    assert lg.login_btn.height() == lg.skip_btn.height() == 44
    assert abs(lg.login_btn.width() / lg.skip_btn.width() - 1.5) < 0.05
    assert lg.login_btn.geometry().y() == lg.skip_btn.geometry().y()
    assert lg.login_btn.geometry().x() < lg.skip_btn.geometry().x()
    assert LoginPage(show_skip=False, portrait=False).skip_btn is None
