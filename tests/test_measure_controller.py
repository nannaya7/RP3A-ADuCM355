"""MeasureController 통합 테스트: 실제 UartWorker(QThread) + FirmwareClient + MockFirmware, 시계는 가짜."""
import json
import sys
import time

import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication

import app.comm.uart_worker as uw
from app.comm.firmware_client import FirmwareClient
from app.comm.mock_device import MockFirmware
from app.comm.uart_worker import UartWorker
from app.measure.controller import MeasureController, State
from app.measure.stages import MeasureSettings, troponin_stages
from app.measure.store import SessionStore

app = QCoreApplication.instance() or QCoreApplication(sys.argv)


def stage_z(stage: int, ch: int, f: float) -> complex:
    """단계별 합성 곡선: 센서 3개는 거의 같고(어레이), 단계마다 다르다. Troponin 모델이 QC 를 통과하는 값."""
    f_arr = np.asarray(f)
    w = 2 * np.pi * f_arr
    z1 = 100 + 5000 / (1 + 1j * w * 5000 * 1e-6)
    scale = 1 + 0.002 * ch
    if stage == 0:
        z = z1
    elif stage == 1:
        z = 150 - 280j
    else:
        z = z1 + abs(z1) * 0.01j * 15
    return complex(z * scale)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class Rig:
    def __init__(self, fw=None, settings=None, wait_s=900, store=None, auto_last=False, **client_kw):
        self.fw = fw or MockFirmware(point_interval=0.0002, z_func=lambda ch, f: stage_z(self.fw.start_count - 1, ch, f))
        self.worker = UartWorker(self.fw)
        self.client = FirmwareClient(self.worker, cmd_timeout_ms=400, start_timeout_ms=800, stop_timeout_ms=400,
                                     **client_kw)
        self.clock = FakeClock()
        self.ctrl = MeasureController(self.client, settings or MeasureSettings(),
                                      troponin_stages(wait_s, auto_last), store=store, clock=self.clock,
                                      tick_ms=20)
        self.views = []
        self.ctrl.viewChanged.connect(self.views.append)
        self.worker.start()

    def wait(self, cond, timeout=8.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            app.processEvents()
            if cond():
                return
            time.sleep(0.003)
        raise AssertionError(f"조건 미충족: state={self.ctrl.state} banner={self.ctrl.snapshot().banner!r}")

    def to_state(self, st, **kw):
        self.wait(lambda: self.ctrl.state == st, **kw)

    @property
    def view(self):
        return self.ctrl.snapshot()

    def close(self):
        self.worker.stop()


@pytest.fixture
def rig():
    # 합성 데이터의 첫 측정은 T2 와 전혀 다른 곡선이라 c0=첫 측정이면 B 가 범위를 벗어난다 → 흐름 시험은 c0 없이(기존 동작)
    r = Rig(settings=MeasureSettings(c0_source="none"))
    yield r
    r.close()


def run_stage(r, expect_idx_after):
    r.ctrl.primary()
    r.wait(lambda: r.ctrl.state in (State.READY, State.DONE, State.ERROR, State.COMPUTING)
           and r.ctrl.snapshot().stage_index == expect_idx_after or r.ctrl.state == State.DONE)


def test_startup_check_reaches_ready_and_reads_module_info(rig):
    rig.to_state(State.READY)
    v = rig.view
    assert v.stage_index == 0 and v.primary_label == "측정 시작" and v.primary_enabled
    assert "보정 있음" in v.module_text
    assert [c.status for c in v.stages] == ["active", "pending", "pending"]
    assert [s.ch for s in v.sensors] == [0, 1, 2]


def test_full_three_stage_flow_with_user_accepts_and_reaction_timer(rig):
    rig.to_state(State.READY)

    # --- T0: 사용자가 시작 버튼을 누른다 ---
    rig.ctrl.primary()
    rig.wait(lambda: rig.ctrl.state == State.MEASURING)
    assert not rig.view.primary_enabled and rig.view.stop_enabled
    assert rig.view.timer_label == "경과 시간"
    rig.wait(lambda: rig.ctrl.state == State.READY and rig.view.stage_index == 1)

    # 센서 0 → 1 → 2 순서로 단계당 101점씩 (한 번의 START)
    assert [(c.ch, len(r)) for c, r in [(s, rig.ctrl._done[0][s.ch]) for s in rig.view.sensors]] == [(0, 101), (1, 101), (2, 101)]
    assert rig.fw.start_count == 1

    # --- T1: 반응 대기 타이머가 끝나기 전에는 버튼이 비활성 ---
    v = rig.view
    assert v.primary_label == "측정 시작" and not v.primary_enabled and v.waiting
    assert v.timer_text == "15:00"
    rig.ctrl.primary()                                       # 눌러도 시작되지 않는다
    time.sleep(0.05)
    app.processEvents()
    assert rig.fw.start_count == 1 and rig.ctrl.state == State.READY
    rig.clock.advance(600)
    assert rig.view.timer_text == "05:00" and not rig.view.primary_enabled
    rig.clock.advance(300)
    assert rig.view.primary_enabled and rig.view.timer_label == "반응 대기 완료"   # 타이머 끝 → 버튼 활성
    assert rig.fw.start_count == 1                                                 # 그래도 자동 시작은 하지 않는다
    rig.ctrl.primary()
    rig.wait(lambda: rig.ctrl.state == State.READY and rig.view.stage_index == 2)

    # --- T2: 대기 없음, 사용자 수락 후 시작 (자동 진행은 담당자 협의 후) ---
    v = rig.view
    assert v.primary_label == "측정 시작" and v.primary_enabled and not v.waiting
    time.sleep(0.05)
    app.processEvents()
    assert rig.fw.start_count == 2
    rig.ctrl.primary()
    rig.wait(lambda: rig.ctrl.state == State.DONE)
    assert rig.fw.start_count == 3

    res = rig.view.result
    assert res is not None and res.qc_pass and res.value is not None
    assert res.warnings                                        # c0·경과시간 없음 경고
    assert [c.status for c in rig.view.stages] == ["done", "done", "done"]
    assert rig.view.primary_label == "새 측정"


@pytest.mark.parametrize("source, anchor_source, kept", [("first", "same_batch_c0", 3), ("none", "historical_day1_c0", 0)])
def test_c0_is_the_first_measurement_unless_disabled(source, anchor_source, kept):
    r = Rig(settings=MeasureSettings(c0_source=source), wait_s=0)
    try:
        r.to_state(State.READY)
        for _ in range(3):
            r.ctrl.primary()
            r.wait(lambda: r.ctrl.state in (State.READY, State.DONE, State.ERROR))
            time.sleep(0.05)
            app.processEvents()
        r.wait(lambda: r.ctrl.state == State.DONE)
        res = r.view.result
        assert res.details["T2_anchor_source"] == anchor_source and res.details["T2_c0_kept"] == kept
        assert any("c0" in w for w in res.warnings) == (source == "none")
        if source == "first":                       # 앵커는 첫 측정(센서 0·1·2)의 T2 형 값과 같다
            from app.models.troponin import raw_t2_b, aggregate_t2_with_qc
            curves = r.ctrl._curves(0)
            z, _, _ = aggregate_t2_with_qc(curves, curves[0][0])
            assert res.details["T2_c0_anchor_ohm"] == pytest.approx(raw_t2_b(curves[0][0], z))
    finally:
        r.close()


def test_progress_and_per_sensor_status_during_measurement():
    r = Rig(fw=MockFirmware(point_interval=0.01, z_func=lambda ch, f: stage_z(0, ch, f)))
    try:
        r.to_state(State.READY)
        r.ctrl.primary()
        r.wait(lambda: r.ctrl.state == State.MEASURING)
        r.wait(lambda: len(r.ctrl._cur.get(1, [])) >= 5)       # 센서 1 을 측정 중 → 센서 0 은 끝나 있어야 한다
        v = r.view
        assert [s.text for s in v.sensors] == ["완료", "측정 중", "대기"]
        assert 0.3 < v.progress < 0.8 and v.progress_text.endswith("/ 303 점")
        r.ctrl.stop()
        r.to_state(State.READY)
    finally:
        r.close()


def test_user_stop_discards_partial_data_and_allows_restart_of_same_stage():
    r = Rig(fw=MockFirmware(point_interval=0.01, z_func=lambda ch, f: stage_z(0, ch, f)))
    try:
        r.to_state(State.READY)
        r.ctrl.primary()
        r.wait(lambda: len(r.ctrl._cur.get(0, [])) >= 3)
        r.ctrl.stop()
        assert r.ctrl.state == State.STOPPING
        r.to_state(State.READY)
        assert r.view.stage_index == 0 and not r.ctrl._done and not r.fw.running
        assert "중지" in r.view.banner
        r.fw.point_interval = 0.0002
        r.ctrl.primary()
        r.wait(lambda: r.view.stage_index == 1)
        assert len(r.ctrl._done[0][2]) == 101
    finally:
        r.close()


def test_firmware_error_goes_to_error_state_then_retry_succeeds():
    r = Rig()
    try:
        r.fw.fault_after_points = 5
        r.to_state(State.READY)
        r.ctrl.primary()
        r.to_state(State.ERROR)
        assert "펌웨어 오류" in r.view.banner and not r.fw.running      # 자동 STOP 으로 멈춤
        assert r.view.primary_label == "다시 시도"
        r.fw.fault_after_points = None
        r.ctrl.primary()
        r.wait(lambda: r.view.stage_index == 1 and r.ctrl.state == State.READY)
        assert len(r.ctrl._done[0][0]) == 101                        # 오류 전의 부분 데이터가 섞이지 않았다
    finally:
        r.close()


def test_silent_module_leads_to_no_module_and_recovers():
    r = Rig()
    try:
        r.fw.silent = True
        orig = r.fw._exec
        r.fw._exec = lambda line: None if r.fw.silent else orig(line)
        r.to_state(State.NO_MODULE, timeout=5)
        assert "응답하지 않습니다" in r.view.banner and r.view.primary_label == "모듈 다시 확인"
        r.fw.silent = False
        r.ctrl.primary()
        r.to_state(State.READY)
    finally:
        r.close()


def test_manual_reaction_timer_mode():
    r = Rig(settings=MeasureSettings(reaction_timer_start="manual"))
    try:
        r.to_state(State.READY)
        r.ctrl.primary()
        r.wait(lambda: r.view.stage_index == 1 and r.ctrl.state == State.READY)
        v = r.view
        assert v.primary_label == "혈액 투입 완료 (타이머 시작)" and v.primary_enabled and v.timer_text == "15:00"
        r.clock.advance(120)
        assert r.view.timer_text == "15:00"                       # 아직 시작 전이라 줄지 않음
        r.ctrl.primary()                                           # 타이머 시작
        r.clock.advance(100)
        assert r.view.timer_text == "13:20" and not r.view.primary_enabled
        r.clock.advance(800)
        assert r.view.primary_label == "측정 시작" and r.view.primary_enabled
    finally:
        r.close()


def test_auto_start_last_stage_when_enabled():
    r = Rig(auto_last=True, wait_s=0)
    try:
        r.to_state(State.READY)
        r.ctrl.primary()
        r.wait(lambda: r.view.stage_index == 1 and r.ctrl.state == State.READY)
        r.ctrl.primary()
        r.to_state(State.DONE)                                     # T2 는 사용자 수락 없이 자동 시작
        assert r.fw.start_count == 3
    finally:
        r.close()


def test_disconnect_during_measurement_gives_link_error_and_retry(monkeypatch):
    monkeypatch.setattr(uw, "RECONNECT_INTERVAL", 0.05)
    r = Rig(fw=MockFirmware(point_interval=0.01, z_func=lambda ch, f: stage_z(0, ch, f)))
    try:
        r.to_state(State.READY)
        r.ctrl.primary()
        r.wait(lambda: len(r.ctrl._cur.get(0, [])) >= 3)
        r.fw.fail_next_read()
        r.to_state(State.ERROR)
        assert "중단" in r.view.banner
        r.wait(lambda: r.client.connected)
        r.fw.point_interval = 0.0002
        r.ctrl.primary()                                           # 링크 오류 → 모듈 확인부터 다시
        r.to_state(State.READY)
        r.ctrl.primary()
        r.wait(lambda: r.view.stage_index == 1)
    finally:
        r.close()


def test_compute_failure_asks_for_remeasure_of_last_stage():
    """T2(UI T1)에서 센서 2개가 어긋나면 모델 QC 가 남은 반복 <2 로 거부 → 마지막 단계 재측정 안내."""
    def z(ch, f):
        k = r.fw.start_count - 1
        v = stage_z(k, ch, f)
        return v * (1.5 + ch * 0.3) if k == 1 and ch > 0 else v
    r = Rig(fw=MockFirmware(point_interval=0.0002, z_func=lambda ch, f: z(ch, f)))
    try:
        r.to_state(State.READY)
        for idx in (1, 2):
            r.ctrl.primary()
            r.wait(lambda: r.view.stage_index == idx and r.ctrl.state == State.READY)
            if idx == 1:
                r.clock.advance(900)
        r.ctrl.primary()
        r.to_state(State.ERROR)
        assert "계산할 수 없습니다" in r.view.banner and r.view.result is None
        assert r.view.primary_label == "다시 시도"
    finally:
        r.close()


def test_session_files_are_written(tmp_path):
    store = SessionStore(tmp_path)
    r = Rig(store=store)
    try:
        r.to_state(State.READY)
        r.ctrl.primary()
        r.wait(lambda: r.view.stage_index == 1 and r.ctrl.state == State.READY)
        r.clock.advance(900)
        r.ctrl.primary()
        r.wait(lambda: r.view.stage_index == 2 and r.ctrl.state == State.READY)
        r.ctrl.primary()
        r.to_state(State.DONE)
        d = store.dir
        raw = (d / "raw.log").read_text(encoding="utf-8")
        assert raw.count("#M,") == 909 and "#H,FW=" in raw and "stage T0 done" in raw
        res = json.loads((d / "result.json").read_text(encoding="utf-8"))
        assert res["result"]["unit"] is None and res["model"]["research_use_only"] is True
        assert res["stages"]["T1"]["counts"] == {"0": 101, "1": 101, "2": 101}
        assert len(res["curves"]["T2"]["2"]) == 101
    finally:
        r.close()


def test_restart_clears_everything(rig):
    rig.to_state(State.READY)
    rig.ctrl.primary()
    rig.wait(lambda: rig.view.stage_index == 1 and rig.ctrl.state == State.READY)
    assert rig.view.reset_enabled
    rig.ctrl.restart()
    rig.to_state(State.READY)
    assert rig.view.stage_index == 0 and not rig.ctrl._done
    assert [c.status for c in rig.view.stages] == ["active", "pending", "pending"]
