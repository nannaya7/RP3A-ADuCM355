"""FirmwareClient + UartWorker(실제 QThread) + MockFirmware 통합 테스트."""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtCore import QCoreApplication

import comm.uart_worker as uw
from comm import protocol as p
from comm.firmware_client import FirmwareClient
from comm.mock_device import MockFirmware
from comm.uart_worker import UartWorker

app = QCoreApplication.instance() or QCoreApplication(sys.argv)


class Rig:
    """워커 + 클라이언트를 만들고 신호를 모아 둔다."""

    def __init__(self, fw=None, **client_kw):
        self.fw = fw or MockFirmware(point_interval=0.001)
        self.worker = UartWorker(self.fw)
        self.client = FirmwareClient(self.worker, cmd_timeout_ms=400, start_timeout_ms=800,
                                     stop_timeout_ms=400, **client_kw)
        self.records, self.cmds, self.events = [], [], []
        c = self.client
        c.recordReceived.connect(self.records.append)
        c.commandFinished.connect(lambda t, ok, m: self.cmds.append((t, ok, m)))
        for name in ("measurementStarted", "measurementStopped", "watchdogExpired", "moduleRestarted"):
            getattr(c, name).connect(lambda n=name: self.events.append(n))
        c.cycleDone.connect(lambda n: self.events.append(f"cycle{n}"))
        c.firmwareError.connect(lambda m: self.events.append("fwerror"))
        c.measurementFailed.connect(lambda m: self.events.append("failed:" + m))
        self.worker.start()
        self.wait(lambda: c.connected)

    def wait(self, cond, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            app.processEvents()
            if cond():
                return True
            time.sleep(0.005)
        raise AssertionError(f"조건 미충족: events={self.events} cmds={self.cmds[-3:]}")

    def close(self):
        self.worker.stop()

    @property
    def meas(self):
        return [r for r in self.records if isinstance(r, p.MeasRecord)]


@pytest.fixture
def rig():
    r = Rig()
    yield r
    r.close()


def configure(r, points=4, chans=(0, 1, 2)):
    r.client.set_sweep(10, 200000, points)
    r.client.set_channels(chans)
    r.client.set_verb("FULL")
    r.wait(lambda: len(r.cmds) >= 3)
    assert all(ok for _, ok, _ in r.cmds), r.cmds


def test_commands_are_serialized_and_status_is_parsed(rig):
    configure(rig)
    assert [c[0] for c in rig.cmds] == ["SWEEP 10 200000 4", "CHAN CH0,CH1,CH2", "VERB FULL"]
    rig.client.query_status()
    rig.client.query_cal_status()
    rig.client.query_env()
    rig.wait(lambda: len(rig.cmds) >= 6)
    assert rig.client.status["RUN"] == "0" and rig.client.status["SWEEP"] == "10.00:200000.00:4"
    assert rig.client.cal_status["VALID"] == "1"
    assert rig.client.last_env == {"temp_c": 24.3, "hum_rh": 41.2}


def test_command_error_is_reported_per_command(rig):
    rig.client.send_command("SWEEP 10")
    rig.client.query_status()                      # 이후 명령은 계속 진행
    rig.wait(lambda: len(rig.cmds) >= 2)
    assert rig.cmds[0][1] is False and rig.cmds[0][2].startswith("usage")
    assert rig.cmds[1][1] is True


def test_one_stage_reads_sensors_0_1_2_in_order(rig):
    """단계 하나 = START 1 한 번 = 센서 0 → 1 → 2 를 각각 전체 스윕."""
    configure(rig, points=4)
    rig.client.start(1)
    rig.wait(lambda: "measurementStopped" in rig.events)
    assert [m.ch for m in rig.meas] == [0] * 4 + [1] * 4 + [2] * 4
    assert rig.events[0] == "measurementStarted" and "cycle1" in rig.events
    assert rig.events.index("cycle1") < rig.events.index("measurementStopped")
    assert not rig.client.measuring
    start_cmd = [c for c in rig.cmds if c[0] == "START 1"][0]
    assert start_cmd[1] is True


def test_three_stages_back_to_back(rig):
    """T0 → T1 → T2: 단계마다 START 1, 단계 사이에는 아무것도 보내지 않는다."""
    configure(rig, points=3)
    per_stage = []
    for stage in range(3):
        n0 = len(rig.meas)
        rig.events.clear()
        rig.client.start(1)
        rig.wait(lambda: "measurementStopped" in rig.events)
        per_stage.append([m.ch for m in rig.meas[n0:]])
    assert per_stage == [[0, 0, 0, 1, 1, 1, 2, 2, 2]] * 3


def test_stop_during_measurement(rig):
    rig.fw.point_interval = 0.05
    configure(rig, points=50)
    rig.client.start(0)
    rig.wait(lambda: len(rig.meas) >= 3)
    rig.client.stop()
    rig.wait(lambda: "measurementStopped" in rig.events)
    assert not rig.client.measuring and not rig.fw.running


def test_stop_when_idle_is_ok_after_timeout(rig):
    rig.client.stop()
    rig.wait(lambda: any(c[0] == "STOP" for c in rig.cmds))
    assert rig.cmds[-1] == ("STOP", True, "실행 중이 아님")


def test_firmware_error_triggers_automatic_stop(rig):
    rig.fw.fault_after_points = 2
    configure(rig, points=5)
    rig.client.start(1)
    rig.wait(lambda: "measurementStopped" in rig.events)
    assert "fwerror" in rig.events and not rig.fw.running      # 펌웨어는 스스로 멈추지 않으므로 자동 STOP 이 필요
    n = len(rig.meas)
    time.sleep(0.1)
    app.processEvents()
    assert len(rig.meas) == n                                   # 더 이상 측정이 이어지지 않는다


def test_watchdog_stops_a_silent_module():
    r = Rig(watchdog_ms=250)
    try:
        r.fw.hang_after_points = 2
        configure(r, points=5)
        r.client.start(1)
        r.wait(lambda: "measurementStopped" in r.events)
        assert "watchdogExpired" in r.events and not r.fw.running
    finally:
        r.close()


def test_module_restart_fails_running_measurement(rig):
    rig.fw.point_interval = 0.05
    configure(rig, points=50)
    rig.client.start(1)
    rig.wait(lambda: len(rig.meas) >= 2)
    rig.fw.reboot()
    rig.wait(lambda: "moduleRestarted" in rig.events)
    assert "failed:모듈 재시작" in rig.events and not rig.client.measuring


def test_disconnect_fails_running_measurement_and_reconnects(monkeypatch):
    monkeypatch.setattr(uw, "RECONNECT_INTERVAL", 0.05)
    r = Rig()
    try:
        r.fw.point_interval = 0.05
        configure(r, points=50)
        r.client.start(1)
        r.wait(lambda: len(r.meas) >= 2)
        r.fw.fail_next_read()                          # 케이블 분리
        r.wait(lambda: "failed:연결 끊김" in r.events)
        r.wait(lambda: r.client.connected)             # 자동 재연결
        r.client.query_status()
        r.wait(lambda: r.cmds[-1][0] == "STATUS")
        assert r.cmds[-1][1] is True
    finally:
        r.close()


def test_garbage_lines_are_ignored_and_reported(rig):
    errors = []
    rig.client.parseError.connect(lambda line, why: errors.append(line))
    rig.fw._immediate.extend(["hello noise", "#M,1,CH0,bad", "#I,5,INFO,fine"])
    rig.wait(lambda: any(isinstance(r, p.InfoRecord) and r.msg == "fine" for r in rig.records))
    assert errors == ["#M,1,CH0,bad"]
