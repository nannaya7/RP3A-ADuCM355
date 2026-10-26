"""설정 버튼(우측 상단)과 설정 화면(Wi-Fi / 블루투스) — 가상 백엔드로 가로/세로 모두 시험."""
import dataclasses

import pytest
from PyQt5.QtGui import QFont
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.app_window import AppWindow
from app.config import Config
from app.display import LANDSCAPE, PORTRAIT
from net import MockBluetooth, MockWifi
from ui.settings_page import SettingsPage, bars_for_rssi, bars_for_signal
from ui.theme import load_fonts, load_stylesheet

app = QApplication.instance()


@pytest.fixture(scope="module", autouse=True)
def styled():
    load_fonts()
    app.setFont(QFont("Pretendard", 10))
    app.setStyleSheet(load_stylesheet())
    yield
    app.setStyleSheet("")


def wait_idle(page: SettingsPage, ms: int = 3000) -> None:
    """백그라운드 작업이 끝나 화면이 풀릴 때까지 이벤트를 돌린다."""
    for _ in range(ms // 10):
        QTest.qWait(10)
        if not page.wifi._busy and not page.bt._busy:
            QTest.qWait(10)
            return
    raise AssertionError("작업이 끝나지 않았습니다")


def make_page(portrait: bool) -> SettingsPage:
    page = SettingsPage(MockWifi(delay=0), MockBluetooth(delay=0), portrait=portrait)
    page.resize(*((480, 800) if portrait else (1280, 800)))
    page.show()
    page.open()
    wait_idle(page)
    return page


def titles(panel) -> list:
    return [panel.list.item(i).data(Qt_ROLE_TITLE) for i in range(panel.list.count())]


def click_row(panel, row) -> None:
    if isinstance(row, str):                                                  # 제목으로 고른다 (목록은 신호 세기 순이라 위치가 바뀐다)
        row = titles(panel).index(row)
    panel._on_item_clicked(panel.list.item(row))
    panel.list.setCurrentRow(row)


def make_window(profile):
    cfg = dataclasses.replace(Config(), uart_mock=True, net_mock=True)
    win = AppWindow(profile, cfg)
    win.show()
    QTest.qWait(60)
    return win


# ---------------- 설정 버튼 ----------------
@pytest.mark.parametrize("profile", [LANDSCAPE, PORTRAIT], ids=["landscape", "portrait"])
def test_gear_is_top_right_on_login_and_measure(profile):
    win = make_window(profile)
    try:
        g = win.gear
        assert g.isVisible()
        assert g.geometry().top() < 40 and win.width() - g.geometry().right() < 50      # 우측 상단
        assert g.geometry().right() < win.width()
        win._on_skip()
        QTest.qWait(30)
        assert win.currentWidget() is win.measure and g.isVisible()
        if not profile.is_portrait:                       # 가로: 날짜/시간 문구가 설정 버튼과 겹치지 않는다
            clock_right = win.measure.clock.mapTo(win, win.measure.clock.rect().topRight()).x()
            assert clock_right <= g.geometry().left()
    finally:
        win.shutdown()


@pytest.mark.parametrize("profile", [LANDSCAPE, PORTRAIT], ids=["landscape", "portrait"])
def test_gear_opens_settings_and_back_returns_to_previous_page(profile):
    win = make_window(profile)
    try:
        win.gear.click()
        QTest.qWait(30)
        assert win.currentWidget() is win.settings and not win.gear.isVisible()
        win.settings.back_btn.click()
        assert win.currentWidget() is win.login and win.gear.isVisible()
        win._on_skip()
        win.gear.click()
        win.settings.back_btn.click()
        assert win.currentWidget() is win.measure                    # 측정 화면에서 열었으면 측정 화면으로 돌아온다
    finally:
        win.shutdown()


def test_measurement_state_survives_opening_settings():
    win = make_window(PORTRAIT)
    try:
        win._on_skip()
        before = win.controller.snapshot()
        win.gear.click()
        win.settings.back_btn.click()
        assert win.controller.snapshot().stage_index == before.stage_index
    finally:
        win.shutdown()


def test_gear_hidden_while_keyboard_open_and_back_after():
    win = make_window(PORTRAIT)
    try:
        win._on_keyboard(True, 335)
        assert not win.gear.isVisible()
        win._on_keyboard(False, 0)
        assert win.gear.isVisible()
    finally:
        win.shutdown()


# ---------------- 설정 화면 ----------------
@pytest.mark.parametrize("portrait", [False, True], ids=["landscape", "portrait"])
def test_wifi_list_and_connect_flow(portrait):
    page = make_page(portrait)
    w = page.wifi
    assert w.list.count() == 5 and "연결된 네트워크 없음" in w.status.text()
    assert w.list.item(0).data(Qt_ROLE_TITLE) == "Nformare-Lab"                # 신호가 가장 센 것이 맨 위

    click_row(w, "Office_5G")                                                 # Office_5G: 새 네트워크 → 비밀번호 필요
    assert w.pw_field.isVisible() and w.btn_main.isVisible() and not w.btn_del.isVisible()
    w.btn_main.click()                                                        # 비밀번호 없이 → 막힘
    assert w.d_msg.isVisible() and "비밀번호" in w.d_msg.text() and w.d_msg.property("level") == "error"
    w.pw_field.edit.setText("wrongpass")
    w.btn_main.click()
    wait_idle(page)
    assert "맞지 않습니다" in w.d_msg.text()
    assert w.pw_field.text() == "wrongpass"                                   # 실패해도 입력한 글자는 남는다
    w.pw_field.edit.setText(MockWifi.PASSWORD)
    w.btn_main.click()
    wait_idle(page)
    assert "연결되었습니다" in w.d_msg.text() and "Office_5G" in w.status.text()
    assert w.list.item(titles(w).index("Office_5G")).data(ROLE_BADGE) == "연결됨"   # 순서는 신호 세기 그대로, 배지만 붙는다
    assert w.btn_alt.isVisible() and w.btn_del.isVisible() and not w.btn_main.isVisible()   # 해제 / 저장 삭제

    w.btn_alt.click()
    wait_idle(page)
    assert "해제" in w.d_msg.text() and "연결된 네트워크 없음" in w.status.text()
    w.btn_del.click()
    wait_idle(page)
    assert "삭제" in w.d_msg.text()
    assert w.pw_field.isVisible()                                             # 저장이 지워졌으니 다시 비밀번호가 필요
    page.shutdown()


def test_wifi_saved_network_connects_without_password():
    page = make_page(False)
    w = page.wifi
    click_row(w, 0)                                                           # Nformare-Lab (저장됨)
    assert not w.pw_field.isVisible()
    w.btn_main.click()
    wait_idle(page)
    assert "연결되었습니다" in w.d_msg.text()
    page.shutdown()


def test_wifi_manual_entry_validates_and_connects():
    page = make_page(True)
    w = page.wifi
    w.manual_btn.click()
    assert w.ssid_field.isVisible() and w.pw_field.isVisible()
    w.btn_main.click()
    assert "이름" in w.d_msg.text()
    w.ssid_field.edit.setText("HiddenNet")
    w.pw_field.edit.setText("short")
    w.btn_main.click()
    assert "8자" in w.d_msg.text()
    w.pw_field.edit.setText(MockWifi.PASSWORD)
    w.btn_main.click()
    wait_idle(page)
    assert "HiddenNet" in w.status.text()
    assert not w._manual and "HiddenNet" in [w.list.item(i).data(Qt_ROLE_TITLE) for i in range(w.list.count())]
    page.shutdown()


def test_wifi_manual_mode_survives_refresh():
    page = make_page(False)
    w = page.wifi
    w.manual_btn.click()
    w.scan_btn.click()
    wait_idle(page)
    assert w.ssid_field.isVisible()
    page.shutdown()


def test_wifi_power_toggle():
    page = make_page(False)
    w = page.wifi
    w.power_btn.click()
    wait_idle(page)
    assert "꺼져" in w.status.text() and w.list.count() == 0 and w.power_btn.text() == "켜기"
    assert not w.scan_btn.isEnabled() and not w.manual_btn.isEnabled()
    w.power_btn.click()
    wait_idle(page)
    assert w.list.count() == 5 and w.scan_btn.isEnabled()
    page.shutdown()


def test_bluetooth_tab_search_register_connect_remove():
    page = make_page(False)
    page.tabs._index = 1
    page.tabs.changed.emit("bt")
    wait_idle(page)
    b = page.bt
    assert page.stack.currentWidget() is b and b.list.count() == 4              # 열 때 한 번 검색
    names = titles(b)
    assert names == ["JBL Speaker", "Nformare Printer", "Barcode Scanner", "이름 없는 장치"]   # RSSI -48, -55, -62, -80 순
    from net.bluetooth import BtDevice
    assert b.sort_key(BtDevice("AA:00", "X", True, False, True, None)) > b.sort_key(BtDevice("AA:01", "Y", False, False, False, -95))   # 신호 정보 없음은 맨 아래

    click_row(b, "Nformare Printer")                                          # 등록됨 / 연결 안 됨
    assert b.btn_main.text() == "연결" and b.btn_del.isVisible()
    b.btn_main.click()
    wait_idle(page)
    assert "연결했습니다" in b.d_msg.text() and "연결됨: Nformare Printer" in b.status.text()
    assert b.btn_alt.text() == "연결 해제" and b.btn_alt.isVisible()

    row = names.index("JBL Speaker")
    click_row(b, row)
    assert b.btn_main.text() == "등록" and not b.btn_del.isVisible()
    b.btn_main.click()
    wait_idle(page)
    assert "등록하고 연결" in b.d_msg.text()

    click_row(b, "이름 없는 장치")
    b.btn_main.click()                                                        # 거절되는 장치
    wait_idle(page)
    assert b.d_msg.property("level") == "error" and "PIN" in b.d_msg.text()
    page.shutdown()


def test_bluetooth_off_and_no_backend():
    page = make_page(True)
    b = page.bt
    b.open()
    wait_idle(page)
    b.power_btn.click()
    wait_idle(page)
    assert "꺼져" in b.status.text() and b.list.count() == 0

    class NoBt(MockBluetooth):
        def available(self):
            return False

    p2 = SettingsPage(MockWifi(delay=0), NoBt(delay=0), portrait=False)
    p2.show()
    p2.bt.open()
    wait_idle(p2)
    assert "bluez" in p2.bt.status.text() and not p2.bt.scan_btn.isEnabled()
    page.shutdown()
    p2.shutdown()


def test_keyboard_folds_header_so_inputs_stay_visible():
    page = make_page(True)
    w = page.wifi
    click_row(w, "Office_5G")
    page.on_keyboard(True, 335)
    QTest.qWait(30)                                                           # 배치가 다시 계산되도록
    assert not page.tabs_row.isVisible() and not w.head.isVisible() and not w.list.isVisible()
    y = w.pw_field.mapTo(page, w.pw_field.rect().bottomLeft()).y()
    assert y < 800 - 335 - 60                                                 # 입력란이 키보드 위에 보인다
    assert w.btn_main.mapTo(page, w.btn_main.rect().bottomLeft()).y() < 800 - 335
    page.on_keyboard(False, 0)
    assert page.tabs_row.isVisible() and w.list.isVisible()
    page.shutdown()


def test_signal_bars():
    assert [bars_for_signal(x) for x in (0, 10, 30, 60, 90, 100)] == [0, 1, 2, 3, 4, 4]
    assert bars_for_rssi(None) == -1 and bars_for_rssi(-40) == 4 and bars_for_rssi(-95) == 1


from ui.settings_page import ROLE_BADGE, ROLE_SUB, ROLE_TITLE as Qt_ROLE_TITLE  # noqa: E402  (테스트 가독성을 위해 아래에 둔다)


# ---------------- 필터 / 정렬 / 아래 여백 ----------------
@pytest.mark.parametrize("portrait", [False, True], ids=["landscape", "portrait"])
def test_wifi_list_is_sorted_by_signal_and_filtered_by_text(portrait):
    page = make_page(portrait)
    w = page.wifi
    sig = [w.list.item(i).data(ROLE_SUB) for i in range(w.list.count())]
    pct = [int(s.rsplit("신호 ", 1)[1].rstrip("%")) for s in sig]
    assert pct == sorted(pct, reverse=True)                                   # 신호가 센 순

    w.filter.edit.setText("OFFICE")                                           # 대소문자 무시, 포함 검색
    assert titles(w) == ["Office_5G"] and w.filter_count.text() == "1 / 5"
    w.filter.edit.setText("zzz-없음")
    assert w.list.count() == 0 and w.filter_count.text() == "0 / 5"
    w.filter.edit.setText("")
    assert w.list.count() == 5 and w.filter_count.text() == "5개"
    page.shutdown()


def test_filter_keeps_selection_when_row_is_hidden_and_restores_it():
    page = make_page(False)
    w = page.wifi
    click_row(w, "Office_5G")
    w.filter.edit.setText("Nformare")                                         # 선택한 항목이 가려져도 선택 키는 유지
    assert titles(w) == ["Nformare-Lab"] and w.current_obj() is None
    w.filter.edit.setText("")
    assert w.current_obj() is not None and w.current_obj().ssid == "Office_5G"
    page.shutdown()


def test_bluetooth_filter_matches_name_or_address():
    page = make_page(False)
    page.tabs._index = 1
    page.tabs.changed.emit("bt")
    wait_idle(page)
    b = page.bt
    b.filter.edit.setText("jbl")
    assert titles(b) == ["JBL Speaker"]
    b.filter.edit.setText("00:03")                                            # MAC 일부로도 찾는다
    assert titles(b) == ["JBL Speaker"]
    page.shutdown()


def test_filter_edit_does_not_grab_focus_on_open():
    page = make_page(True)
    assert not page.wifi.filter.edit.hasFocus()                               # 열릴 때 포커스를 받으면 키보드가 저절로 뜬다


def test_portrait_keeps_results_visible_while_typing_the_filter():
    page = make_page(True)
    w = page.wifi
    w.filter.edit.setFocus()
    page.on_keyboard(True, 335)
    QTest.qWait(30)
    assert w.list.isVisible() and w.filter_row.isVisible() and not w.detail.isVisible() and not w.head.isVisible()
    page.on_keyboard(False)
    QTest.qWait(30)
    assert w.detail.isVisible() and w.head.isVisible()


def test_portrait_window_leaves_a_bottom_margin_and_keyboard_sits_above_it():
    win = make_window(PORTRAIT)
    try:
        assert win.contentsMargins().bottom() == 20
        assert win.login.geometry().bottom() == win.height() - 21             # 페이지가 그만큼 올라와 있다
        win.keyboard.show_keyboard()
        assert win.keyboard.geometry().bottom() == win.height() - 21
    finally:
        win.shutdown()


def test_fullscreen_portrait_window_is_not_forced_taller_than_the_screen():
    """Pi 실측: 전체화면 창이 463x814 로 떠서 (화면 480x800) 아래가 잘렸다. 내용의 최소 크기가 창을 키우면 안 된다."""
    cfg = dataclasses.replace(Config(), uart_mock=True, net_mock=True, fullscreen=True)
    win = AppWindow(PORTRAIT, cfg)
    try:
        win.show()
        win.resize(480, 700)                       # 측정 화면의 최소 높이(787)보다 작게도 줄일 수 있어야 한다
        QTest.qWait(60)
        assert win.height() <= 700 and win.width() == 480
        win.resize(480, 800)
        QTest.qWait(60)
        assert (win.width(), win.height()) == (480, 800)
    finally:
        win.shutdown()


def test_portrait_measure_page_scrolls_instead_of_overflowing_when_a_banner_shows():
    win = make_window(PORTRAIT)
    try:
        win._on_skip()
        QTest.qWait(60)
        m = win.measure
        m._flash("모듈이 응답하지 않습니다 (STATUS: 응답 시간 초과). 배선과 전원을 확인하세요.", "error")
        QTest.qWait(60)
        sb = m.body_scroll.verticalScrollBar()
        assert m.banner.isVisible() and sb.maximum() > 0                       # 넘치는 만큼 스크롤된다
        assert m.body_scroll.geometry().bottom() <= m.height()                  # 본문 영역은 페이지 안에 있다
        sb.setValue(sb.maximum())
        assert m.history_btn.mapTo(m, m.history_btn.rect().bottomLeft()).y() <= m.height()   # 맨 아래 항목까지 볼 수 있다
    finally:
        win.shutdown()


def test_landscape_window_has_no_bottom_margin():
    win = make_window(LANDSCAPE)
    try:
        assert win.contentsMargins().bottom() == 0 and win.login.geometry().bottom() == win.height() - 1
    finally:
        win.shutdown()
