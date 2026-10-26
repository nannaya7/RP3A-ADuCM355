"""UART 모니터링: TrafficLog(기록) + MonitorPage(화면) + 측정 화면의 [모니터링] 버튼."""
import dataclasses

import pytest
from PyQt5.QtGui import QFont
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.app_window import AppWindow
from app.config import Config
from app.display import LANDSCAPE, PORTRAIT
from app.comm.traffic_log import RX, SYS, TX, Entry, TrafficLog, format_entry
from app.ui.monitor_page import MonitorPage, color_of
from app.ui.theme import load_fonts, load_stylesheet

app = QApplication.instance()


@pytest.fixture(scope="module", autouse=True)
def styled():
    load_fonts()
    app.setFont(QFont("Pretendard", 10))
    app.setStyleSheet(load_stylesheet())
    yield
    app.setStyleSheet("")


def fake_clock():
    t = [0.0]

    def clock():
        t[0] += 0.5
        return t[0]
    return clock


def text_of(page: MonitorPage) -> str:
    return page.view.toPlainText()


def flush(page: MonitorPage) -> None:
    QTest.qWait(150)


# ---------------- 기록 ----------------
def test_log_records_in_order_with_relative_time_and_counts():
    log = TrafficLog(clock=fake_clock())
    log.on_tx("STATUS")
    log.on_rx("#I,000001,INFO,ready")
    log.on_sys("UART 열기 실패")
    es = log.entries()
    assert [e.kind for e in es] == [TX, RX, SYS]
    assert [e.text for e in es] == ["STATUS", "#I,000001,INFO,ready", "UART 열기 실패"]
    assert es[0].t < es[1].t < es[2].t
    assert (log.tx_count, log.rx_count) == (1, 1)
    assert format_entry(Entry(1.5, TX, "STATUS")).endswith("→ STATUS")
    assert format_entry(Entry(1.5, RX, "OK")).endswith("← OK")


def test_log_is_a_ring_buffer_and_truncates_long_lines():
    log = TrafficLog(maxlen=3)
    for i in range(5):
        log.on_rx(f"line{i}")
    assert [e.text for e in log.entries()] == ["line2", "line3", "line4"]
    log.on_rx("x" * 1000)
    assert len(log.entries()[-1].text) < 400 and "+700자" in log.entries()[-1].text


def test_entry_classification_and_colors():
    assert Entry(0, RX, "#D,1,2").is_data and not Entry(0, TX, "#D").is_data
    assert Entry(0, RX, "ERR,BUSY").is_error and Entry(0, SYS, "x").is_error and not Entry(0, RX, "OK").is_error
    assert color_of(Entry(0, RX, "ERR,x")) != color_of(Entry(0, RX, "OK"))
    assert color_of(Entry(0, RX, "#D,1")) != color_of(Entry(0, RX, "#M,1"))


def test_log_save_writes_file(tmp_path):
    log = TrafficLog(clock=fake_clock())
    log.on_tx("STATUS")
    log.on_rx("#I,1,INFO,한글")
    p = log.save(tmp_path / "sub" / "u.log")
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("#") and "→ STATUS" in lines[1] and "한글" in lines[2]


def test_log_clear_resets_counters():
    log = TrafficLog()
    log.on_tx("A")
    log.on_rx("B")
    got = []
    log.cleared.connect(lambda: got.append(1))
    log.clear()
    assert log.entries() == [] and (log.tx_count, log.rx_count) == (0, 0) and got == [1]


# ---------------- 화면 ----------------
@pytest.mark.parametrize("portrait", [False, True], ids=["landscape", "portrait"])
def test_page_shows_live_traffic_and_status(portrait):
    log = TrafficLog()
    page = MonitorPage(log, portrait=portrait)
    page.resize(*((480, 800) if portrait else (1280, 800)))
    page.show()
    log.on_tx("STATUS")
    log.on_rx("#I,000001,INFO,ready")
    flush(page)
    t = text_of(page)
    assert "→ STATUS" in t and "← #I,000001,INFO,ready" in t and t.index("STATUS") < t.index("ready")
    assert "보냄 1" in page.status.text() and "받음 1" in page.status.text()


def test_page_shows_history_from_before_it_was_opened():
    log = TrafficLog()
    log.on_tx("STATUS")
    page = MonitorPage(log)
    assert "→ STATUS" in text_of(page)


def test_filters_hide_data_points_and_directions():
    log = TrafficLog()
    page = MonitorPage(log)
    page.show()
    for line in ("#I,1,INFO,x", "#D,1,CH0,10", "#M,1,CH0,10,1"):
        log.on_rx(line)
    log.on_tx("START 1")
    flush(page)
    page.cb_data.setChecked(False)
    t = text_of(page)
    assert "#D," not in t and "#M," in t and "START 1" in t
    page.cb_tx.setChecked(False)
    assert "START 1" not in text_of(page)
    log.on_sys("UART 연결 끊김")                                # 상태 줄은 필터와 무관하게 보인다
    log.on_rx("#D,2,CH0,20")                                     # 숨긴 #D 는 새로 와도 안 보인다
    flush(page)
    assert "연결 끊김" in text_of(page) and "#D," not in text_of(page)
    page.cb_data.setChecked(True)
    assert "#D,1" in text_of(page) and "#D,2" in text_of(page)


def test_pause_holds_new_lines_and_resume_shows_them():
    log = TrafficLog()
    page = MonitorPage(log)
    page.show()
    log.on_rx("first")
    flush(page)
    page.pause_btn.click()
    assert page.pause_btn.text() == "계속"
    log.on_rx("second")
    flush(page)
    assert "second" not in text_of(page) and "일시정지" in page.status.text() and "보류 1" in page.status.text()
    page.pause_btn.click()
    assert page.pause_btn.text() == "일시정지" and "second" in text_of(page)


def test_clear_button_empties_view_and_counters():
    log = TrafficLog()
    page = MonitorPage(log)
    page.show()
    log.on_tx("STATUS")
    flush(page)
    page.clear_btn.click()
    assert text_of(page).strip() == "" and "보냄 0" in page.status.text()
    log.on_rx("after")
    flush(page)
    assert text_of(page).strip().endswith("after")


def test_save_button_writes_file_and_reports_path(tmp_path):
    log = TrafficLog()
    page = MonitorPage(log, save_dir=tmp_path)
    page.show()
    log.on_tx("STATUS")
    page.save_btn.click()
    files = list((tmp_path / "monitor").glob("uart_*.log"))
    assert len(files) == 1 and "STATUS" in files[0].read_text(encoding="utf-8")
    assert page.note.isVisible() and "저장했습니다" in page.note.text()


def test_view_keeps_following_only_when_at_bottom():
    log = TrafficLog()
    page = MonitorPage(log)
    page.resize(600, 400)
    page.show()
    for i in range(200):
        log.on_rx(f"line {i}")
    flush(page)
    bar = page.view.verticalScrollBar()
    assert bar.value() == bar.maximum()                          # 맨 아래를 따라간다
    bar.setValue(0)
    for i in range(50):
        log.on_rx(f"more {i}")
    flush(page)
    assert bar.value() < bar.maximum() // 2                      # 위로 올려 읽는 중이면 끌어내리지 않는다


def test_block_count_is_capped():
    log = TrafficLog(maxlen=20000)
    page = MonitorPage(log)
    page.show()
    for i in range(6000):
        log.on_rx(f"l{i}")
    flush(page)
    assert page.view.blockCount() <= 4001


# ---------------- 앱 연결 ----------------
def make_window(profile, **kw):
    cfg = dataclasses.replace(Config(), uart_mock=True, net_mock=True, **kw)
    win = AppWindow(profile, cfg)
    win.show()
    QTest.qWait(60)
    return win


@pytest.mark.parametrize("profile", [LANDSCAPE, PORTRAIT], ids=["landscape", "portrait"])
def test_monitor_button_next_to_stop_opens_page_with_real_traffic(profile):
    win = make_window(profile)
    try:
        win.start_uart()
        deadline = 0
        while not win.client.connected and deadline < 100:
            QTest.qWait(20)
            deadline += 1
        QTest.qWait(300)
        win._on_skip()
        QTest.qWait(50)
        m = win.measure
        sx = m.stop_btn.mapTo(win, m.stop_btn.rect().topLeft()).x()
        mx = m.monitor_btn.mapTo(win, m.monitor_btn.rect().topLeft()).x()
        assert abs(sx - mx) <= (m.stop_btn.width() + 16) and m.monitor_btn.isVisible()     # 중지 바로 옆
        assert m.monitor_btn.mapTo(win, m.monitor_btn.rect().topLeft()).y() == \
            m.stop_btn.mapTo(win, m.stop_btn.rect().topLeft()).y()
        m.monitor_btn.click()
        QTest.qWait(200)
        assert win.currentWidget() is win.monitor and not win.gear.isVisible()
        t = text_of(win.monitor)
        assert "→ STATUS" in t and "← #I" in t                    # 모듈 확인 때 오간 명령과 응답
        win.monitor.back_btn.click()
        assert win.currentWidget() is win.measure and win.gear.isVisible()
    finally:
        win.shutdown()


def test_traffic_is_recorded_during_a_measurement():
    win = make_window(PORTRAIT, require_patient=False)          # 이 시험은 프로필 선택과 무관
    try:
        win.start_uart()
        QTest.qWait(400)
        win._on_skip()
        win.measure.primary_btn.click()
        QTest.qWait(300)
        kinds = [e.text for e in win.traffic.entries() if e.kind == TX]
        assert "STATUS" in kinds and any(t.startswith("START") for t in kinds)
        assert any(e.is_data or e.text.startswith("#M") for e in win.traffic.entries() if e.kind == RX)
    finally:
        win.shutdown()
