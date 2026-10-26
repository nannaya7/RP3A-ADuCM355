"""설정 > 센서: 패치 센서(블루투스) / 내장 센서(UART) 토글. 동시에 하나만 켜진다."""
import dataclasses
import sys
import time

import pytest
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.app_window import AppWindow
from app.config import Config
from app.display import LANDSCAPE, PORTRAIT
from comm.sensor import BUILTIN, OFF, PATCH, SensorStore, make_transport, normalize, toggled
from comm.ble_transport import BleNusTransport
from comm.uart_worker import UartWorker
from net import MockBluetooth, MockWifi
from ui.settings_page import SettingsPage
from ui.theme import load_fonts, load_stylesheet

app = QApplication.instance() or QApplication(sys.argv)
load_fonts()
app.setStyleSheet(load_stylesheet())


# ---------------- 규칙 ----------------
def test_turning_one_on_turns_the_other_off_and_off_means_none():
    assert toggled(BUILTIN, PATCH, True) == PATCH                 # 패치를 켜면 내장은 자동으로 꺼진다
    assert toggled(PATCH, BUILTIN, True) == BUILTIN               # 내장을 켜면 패치는 자동으로 꺼진다
    assert toggled(PATCH, PATCH, False) == OFF                    # 켜진 것을 끄면 둘 다 꺼진다
    assert toggled(OFF, PATCH, False) == OFF
    assert toggled(BUILTIN, PATCH, False) == BUILTIN              # 이미 꺼진 쪽을 또 끄는 요청은 변화 없음
    assert normalize("PATCH") == PATCH and normalize("???") == BUILTIN and normalize(None, OFF) == OFF


def test_selection_is_saved_and_survives_corrupt_file(tmp_path):
    s = SensorStore(tmp_path / "data" / "sensor.json")
    assert s.load() == BUILTIN                                    # 파일이 없으면 기본값
    assert s.save(PATCH) and s.load() == PATCH
    assert s.save("엉뚱한 값") and s.load() == OFF                  # 모르는 값은 꺼짐으로 저장
    (tmp_path / "data" / "sensor.json").write_text("{깨진 파일", encoding="utf-8")
    assert s.load(BUILTIN) == BUILTIN                             # 깨졌으면 기본값 (죽지 않는다)


def test_transport_per_mode():
    cfg = dataclasses.replace(Config(), uart_port="/dev/serial0", patch_name="nFor", patch_address="")
    t = make_transport(PATCH, cfg)
    assert isinstance(t, BleNusTransport) and t.name == "ble:nFor*"       # 패치 = BLE NUS
    assert make_transport(OFF, cfg) is None
    mock = dataclasses.replace(cfg, uart_mock=True)
    assert make_transport(PATCH, mock) is not None and make_transport(BUILTIN, mock) is not None


# ---------------- 워커: 실행 중 전송 장치 교체 ----------------
class FakeTransport:
    def __init__(self, name, fail_open=False):
        self.name, self.fail_open = name, fail_open
        self.opened = self.closed = 0
        self.written = []

    def open(self):
        if self.fail_open:
            raise OSError("no such port")
        self.opened += 1

    def close(self):
        self.closed += 1

    def read(self):
        time.sleep(0.005)
        return b""

    def write(self, data):
        self.written.append(data)


def wait(cond, ms=3000):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            return
        time.sleep(0.005)
    raise AssertionError("조건 미충족")


def test_worker_switches_transport_while_running():
    a, b = FakeTransport("A"), FakeTransport("B")
    w = UartWorker(a)
    states = []
    w.connectionChanged.connect(states.append)
    w.start()
    try:
        wait(lambda: states == [True])
        w.set_transport(b)                                       # A 를 닫고 B 로 다시 연결
        wait(lambda: states == [True, False, True] and b.opened == 1)
        assert a.closed >= 1 and w.transport_name == "B"
        w.send_line("STATUS")
        wait(lambda: b.written and not a.written)               # 이후 명령은 B 로만 간다
        w.set_transport(None)                                    # 센서 꺼짐
        wait(lambda: states[-1] is False and b.closed >= 1)
        w.set_transport(FakeTransport("C"))
        wait(lambda: states[-1] is True and w.transport_name == "C")
    finally:
        w.stop()


def test_worker_keeps_retrying_a_port_that_cannot_open_and_reports_it():
    bad = FakeTransport("BT", fail_open=True)
    w = UartWorker(bad)
    errors = []
    w.errorOccurred.connect(errors.append)
    w.start()
    try:
        wait(lambda: errors)
        assert "열기 실패" in errors[0] and "BT" in errors[0]
        good = FakeTransport("UART")
        w.set_transport(good)                                    # 재시도 대기 중에도 바로 바뀐다
        wait(lambda: good.opened == 1, 2500)
    finally:
        w.stop()


# ---------------- 화면 ----------------
def make_page(portrait):
    page = SettingsPage(MockWifi(delay=0), MockBluetooth(delay=0), portrait=portrait)
    page.resize(*((480, 800) if portrait else (1280, 800)))
    page.show()
    return page


@pytest.mark.parametrize("portrait", [False, True], ids=["landscape", "portrait"])
def test_sensor_tab_shows_two_cards_and_requests_modes(portrait):
    page = make_page(portrait)
    page.tabs._index = 2
    page.tabs.changed.emit("sensor")
    assert page.stack.currentWidget() is page.sensor
    s = page.sensor
    assert "블루투스" in s.patch.how.text() and "UART" in s.builtin.how.text()
    got = []
    page.sensorModeRequested.connect(got.append)
    s.set_mode(BUILTIN)
    assert s.builtin.switch.isChecked() and not s.patch.switch.isChecked()
    s.patch.switch.click()                                       # 패치를 켜 달라는 요청
    assert got == [PATCH]
    assert s.builtin.switch.isChecked() and not s.patch.switch.isChecked()   # 받아들여지기 전에는 그대로
    s.set_mode(PATCH)                                            # 받아들여짐 → 내장은 자동 OFF
    assert s.patch.switch.isChecked() and not s.builtin.switch.isChecked()
    s.patch.switch.click()                                       # 켜진 것을 끄면 모두 OFF 요청
    assert got[-1] == OFF
    s.set_mode(OFF)
    assert not s.patch.switch.isChecked() and not s.builtin.switch.isChecked()
    assert s.patch.state.text() == "꺼짐"


def test_connection_text_follows_state():
    page = make_page(True)
    s = page.sensor
    s.set_mode(PATCH)
    s.set_connection(False, "BLE 센서를 찾지 못함")
    assert "연결 안 됨" in s.patch.state.text() and s.builtin.state.text() == "꺼짐"
    s.set_connection(True, "BLE (nFor*)")
    assert s.patch.state.text().startswith("연결됨")


# ---------------- 앱 전체 ----------------
def make_window(tmp_path, profile=PORTRAIT, **kw):
    cfg = dataclasses.replace(Config(), uart_mock=True, net_mock=True, **kw)
    win = AppWindow(profile, cfg)
    win.sensor_store = SensorStore(tmp_path / "sensor.json")       # 테스트가 실제 data/ 를 건드리지 않게
    win.start_uart()                                               # main.py 와 같게 워커를 시작한다
    win.show()
    QTest.qWait(60)
    return win


@pytest.mark.parametrize("profile", [LANDSCAPE, PORTRAIT], ids=["landscape", "portrait"])
def test_app_switches_sensor_and_saves_choice(tmp_path, profile):
    win = make_window(tmp_path, profile)
    try:
        assert win.sensor_mode == BUILTIN                          # 기본은 내장 센서
        win.settings.sensor.patch.switch.click()                   # 연결 + STATUS 확인이 끝나야 켜진다
        wait(lambda: win.sensor_mode == PATCH and win._probe is None, 6000)
        assert win.settings.sensor.mode == PATCH
        assert SensorStore(tmp_path / "sensor.json").load() == PATCH
        win.settings.sensor.builtin.switch.click()                 # 내장을 켜면 패치는 자동 OFF
        assert win.sensor_mode == BUILTIN and not win.settings.sensor.patch.switch.isChecked()
        win.settings.sensor.builtin.switch.click()                 # 끄면 모두 OFF
        assert win.sensor_mode == OFF
        wait(lambda: win.worker.transport_name == "")              # 워커 스레드가 장치를 내려놓는다
        assert "꺼짐" in win.settings.sensor.patch.state.text() and "꺼짐" in win.settings.sensor.builtin.state.text()
    finally:
        win.shutdown()


class SilentTransport(FakeTransport):
    """포트는 열리지만 모듈이 아무 응답도 하지 않는다 (패치가 꺼져 있거나 다른 장치에 연결된 경우)."""


def use_patch_transport(monkeypatch, patch_transport):
    """패치 센서만 지정한 전송 장치로 바꾼다 (내장 센서는 그대로 가상 펌웨어)."""
    import app.app_window as aw
    real = aw.make_transport
    monkeypatch.setattr(aw, "make_transport", lambda mode, cfg: patch_transport if mode == PATCH else real(mode, cfg))


@pytest.mark.parametrize("transport", [SilentTransport("BT-silent"), FakeTransport("BT-missing", fail_open=True)],
                         ids=["no-response", "port-cannot-open"])
def test_patch_sensor_that_does_not_answer_is_rolled_back_with_a_popup(tmp_path, monkeypatch, transport):
    win = make_window(tmp_path, PORTRAIT)
    win.probe_timeout_s = 1.0                                       # 포트가 안 열리는 경우를 짧게 기다린다
    use_patch_transport(monkeypatch, transport)
    popups = []
    monkeypatch.setattr(win, "notify", popups.append)              # 팝업이 테스트를 멈추지 않게
    try:
        win.settings.sensor.patch.switch.click()
        assert win.settings.sensor.patch.switch.isChecked() is False or win._probe is not None   # 확인하는 동안
        wait(lambda: popups, 6000)
        assert popups == ["먼저 센서를 연결해 주세요."]
        assert win.sensor_mode == BUILTIN and win._probe is None
        assert win.settings.sensor.builtin.switch.isChecked() and not win.settings.sensor.patch.switch.isChecked()
        assert "먼저 센서를 연결해 주세요." in win.settings.sensor.msg.text()
        assert SensorStore(tmp_path / "sensor.json").load() == BUILTIN      # 저장도 바뀌지 않았다
        assert win.settings.sensor.patch.switch.isEnabled()                 # 다시 시도할 수 있다
        wait(lambda: win.controller.state == "ready", 6000)                 # 내장 센서로 돌아가 모듈 확인이 다시 끝난다
    finally:
        win.shutdown()


def test_patch_sensor_turns_on_when_the_module_answers_status(tmp_path, monkeypatch):
    win = make_window(tmp_path, PORTRAIT)
    popups = []
    monkeypatch.setattr(win, "notify", popups.append)
    try:
        win.settings.sensor.patch.switch.click()
        wait(lambda: win.sensor_mode == PATCH and win._probe is None, 6000)
        assert win.controller.state == "ready" and not popups                # STATUS 응답 확인
        assert win.settings.sensor.patch.switch.isChecked() and not win.settings.sensor.builtin.switch.isChecked()
    finally:
        win.shutdown()


def test_patch_sensor_probe_works_after_a_finished_test(tmp_path, monkeypatch):
    """검사가 끝난(DONE) 상태에서는 모듈 확인이 저절로 다시 돌지 않아 앱이 직접 다시 시작한다."""
    from measure.controller import State
    win = make_window(tmp_path, PORTRAIT)
    monkeypatch.setattr(win, "notify", lambda _t: None)
    try:
        wait(lambda: win.controller.state == "ready", 5000)
        win.controller._set_state(State.DONE)
        win.settings.sensor.patch.switch.click()
        wait(lambda: win.sensor_mode == PATCH and win._probe is None, 8000)
        assert win.controller.state == "ready"
    finally:
        win.shutdown()


def spy_on_scan(win):
    calls = []
    real = win.bluetooth.scan
    win.bluetooth.scan = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    return calls


def start_patch_test(win, monkeypatch):
    """패치 센서를 켜고 1단계 측정을 시작한다 (검사 진행 중 상태)."""
    monkeypatch.setattr(win, "notify", lambda _t: None)
    win.settings.sensor.patch.switch.click()
    wait(lambda: win.sensor_mode == PATCH and win._probe is None, 6000)
    wait(lambda: win.controller.state == "ready", 5000)
    win.controller.primary()
    wait(lambda: win.controller.state in ("configuring", "measuring") or win.controller.snapshot().stage_index > 0)


def test_bluetooth_scan_is_blocked_while_testing_with_the_patch_sensor(tmp_path, monkeypatch):
    win = make_window(tmp_path, PORTRAIT, require_patient=False)
    try:
        calls = spy_on_scan(win)
        bt = win.settings.bt
        start_patch_test(win, monkeypatch)
        bt.scan_btn.setEnabled(True)
        bt.scan_btn.click()                                         # 검색 시도 → 막힘
        assert calls == [] and "검색을 할 수 없습니다" in bt.d_msg.text() and not bt.d_msg.isHidden()
        bt._loaded_once = False
        bt.open()                                                   # 탭을 처음 열 때의 자동 검색도 막힌다
        wait(lambda: not bt._busy)
        assert calls == []
    finally:
        win.shutdown()


def test_bluetooth_scan_is_allowed_with_builtin_sensor_or_when_idle(tmp_path):
    win = make_window(tmp_path, PORTRAIT, require_patient=False)
    try:
        calls = spy_on_scan(win)
        bt = win.settings.bt
        wait(lambda: win.controller.state == "ready", 5000)
        win.controller.primary()                                    # 내장 센서로 검사 중 → 검색은 허용
        wait(lambda: win.controller.state in ("configuring", "measuring") or win.controller.snapshot().stage_index > 0)
        bt.refresh(scan=True)
        wait(lambda: calls)
        assert win._bt_scan_block_reason() == ""
    finally:
        win.shutdown()


def test_bluetooth_scan_is_allowed_again_when_the_patch_test_is_finished_or_not_started(tmp_path, monkeypatch):
    win = make_window(tmp_path, PORTRAIT, require_patient=False)
    monkeypatch.setattr(win, "notify", lambda _t: None)
    try:
        win.settings.sensor.patch.switch.click()                    # 패치 센서 ON, 아직 검사 전
        wait(lambda: win.sensor_mode == PATCH and win._probe is None, 6000)
        wait(lambda: win.controller.state == "ready", 5000)
        assert win._bt_scan_block_reason() == ""
        win.controller._set_state("done")                           # 검사 끝
        assert win._bt_scan_block_reason() == ""
    finally:
        win.shutdown()


def test_turning_patch_off_or_builtin_on_needs_no_probe(tmp_path, monkeypatch):
    win = make_window(tmp_path, PORTRAIT)
    popups = []
    monkeypatch.setattr(win, "notify", popups.append)
    try:
        win.settings.sensor.builtin.switch.click()                 # 내장 센서 끄기: 확인 없이 바로
        assert win.sensor_mode == OFF
        win.settings.sensor.builtin.switch.click()                 # 내장 센서 켜기: 확인 없이 바로
        assert win.sensor_mode == BUILTIN and not popups
    finally:
        win.shutdown()


def test_app_refuses_to_switch_sensor_during_a_test(tmp_path):
    win = make_window(tmp_path, PORTRAIT, require_patient=False)
    try:
        wait(lambda: win.controller.state == "ready", 5000)
        win.controller.primary()                                    # 1단계 측정 시작
        wait(lambda: win.controller.state in ("measuring", "configuring") or win.controller.snapshot().stage_index > 0)
        win.settings.sensor.patch.switch.click()
        assert win.sensor_mode == BUILTIN and win._probe is None    # 거절됨 (확인을 시작하지도 않는다)
        assert win.settings.sensor.builtin.switch.isChecked() and not win.settings.sensor.patch.switch.isChecked()
        assert "바꿀 수 없습니다" in win.settings.sensor.msg.text() and not win.settings.sensor.msg.isHidden()
    finally:
        win.shutdown()


def test_saved_choice_is_used_on_next_start(tmp_path):
    SensorStore(tmp_path / "sensor.json").save(PATCH)
    cfg = dataclasses.replace(Config(), uart_mock=True, net_mock=True)
    store_path = tmp_path / "sensor.json"
    import app.app_window as aw
    orig = aw.SensorStore
    aw.SensorStore = lambda _p: orig(store_path)
    try:
        win = AppWindow(PORTRAIT, cfg)
    finally:
        aw.SensorStore = orig
    try:
        assert win.sensor_mode == PATCH and win.settings.sensor.patch.switch.isChecked()
    finally:
        win.shutdown()


def test_panel_shows_module_check_state():
    from ui.sensor_panel import SensorPanel
    s = SensorPanel()
    s.set_mode(BUILTIN)
    s.set_connection(True, "UART", checking=True)
    assert "확인 중" in s.builtin.state.text()
    s.set_connection(False, "모듈이 응답하지 않음 (UART)")
    assert "연결 안 됨" in s.builtin.state.text() and "응답하지 않음" in s.builtin.state.text()
    s.set_connection(True, "UART")
    assert s.builtin.state.text().startswith("연결됨")


def test_ble_transport_read_write_without_radio():
    import asyncio
    t = BleNusTransport("", "nFor")
    t._rx.put(b"AB")
    t._rx.put(b"CD")
    assert t.read() == b"ABCD" and t.read() == b""                # 알림 조각을 이어서 돌려준다
    t._lost.set()
    with pytest.raises(OSError):
        t.read()                                                  # 링크가 끊기면 워커가 재연결하도록 오류
    with pytest.raises(OSError):
        t.write(b"x")
    sent = []

    class C:
        async def write_gatt_char(self, uuid, data, response=True):
            sent.append(bytes(data))
    t._client, t._chunk = C(), 20
    asyncio.run(t._write(bytes(45)))
    assert [len(x) for x in sent] == [20, 20, 5]                  # MTU 크기로 쪼개 보낸다
