import time

from app.comm import protocol as p
from app.comm.mock_device import BANNER, MockFirmware


def run(fw, *cmds, wait=0.0):
    """명령을 보내고, 잠시 기다리며 나온 줄을 레코드로 모은다."""
    for c in cmds:
        fw.write((c + "\r\n").encode())
    out, lb = [], p.LineBuffer()
    end = time.monotonic() + wait
    while True:
        out += [p.parse_line(l) for l in lb.feed(fw.read())]
        if time.monotonic() >= end:
            return [r for r in out if r is not None]


def new(**kw):
    fw = MockFirmware(point_interval=0.001, **kw)
    fw.open()
    return fw


def msgs(recs):
    return [r.msg for r in recs if isinstance(r, p.InfoRecord)]


def test_config_commands_echo():
    fw = new()
    out = msgs(run(fw, "SWEEP 10 200000 101", "CHAN CH0,CH1,CH2", "VERB FULL", "RCAL 1000", wait=0.05))
    assert out == ["SWEEP set 10.00 200000.00 101", "CHMASK=0x7", "VERB=FULL", "RCAL set 1000.0"]


def test_commands_case_insensitive_and_errors():
    fw = new()
    out = run(fw, "sweep 10", "bogus", "chan CH9", "chan", "verb LOUD", wait=0.05)
    assert [(r.level, r.msg.split(":")[0]) for r in out] == [
        ("ERR", "usage"), ("ERR", "unknown command"), ("ERR", "unknown channel"),
        ("ERR", "usage"), ("ERR", "unknown verbosity")]
    assert msgs(run(fw, "x" * 70, wait=0.02)) == ["command too long"]


def test_sweep_values_are_clamped_and_single_point_ignores_stop():
    fw = new()
    assert msgs(run(fw, "SWEEP 0.001 999999 9999", wait=0.02)) == ["SWEEP set 0.02 200000.00 500"]
    assert msgs(run(fw, "SWEEP 50 9000 1", wait=0.02)) == ["SWEEP set 50.00 50.00 1"]


def test_status_and_cal_status():
    fw = new()
    r = run(fw, "STATUS", "CALSTATUS", "ENV", wait=0.02)
    st = p.parse_kv(r[0].msg)
    assert (r[0].level, st["RUN"], st["CHMASK"]) == ("STATUS", "0", "0x7")
    assert p.parse_kv(r[1].msg)["VALID"] == "1"
    assert r[2].msg.startswith("ENV TEMP_C=")


def test_one_cycle_sensors_are_measured_in_order_full_sweep_each():
    """CH0 을 전체 주파수·점 수만큼 측정한 뒤 CH1, 그다음 CH2 (사용자 설명 = 펌웨어 동작)."""
    fw = new()
    run(fw, "SWEEP 10 200000 5", "CHAN CH0,CH1,CH2", "VERB FULL", wait=0.02)
    recs = run(fw, "START 1", wait=0.5)
    meas = [r for r in recs if isinstance(r, p.MeasRecord)]
    assert [m.ch for m in meas] == [0] * 5 + [1] * 5 + [2] * 5
    for ch in (0, 1, 2):
        f = [m.freq_hz for m in meas if m.ch == ch]
        assert f[0] == 10.0 and f[-1] == 200000.0 and f == sorted(f)
    ms = msgs(recs)
    assert ms[0] == "measurement started, 1 cycle(s)"
    assert ms[-2:] == ["CYCLE=1 done", "measurement stopped"]
    assert isinstance(recs[0], p.HeaderRecord)
    # AFE0 용 #C 는 CH0 앞, AFE1 용 #C 는 CH2 앞에서 한 번씩
    cals = [i for i, r in enumerate(recs) if isinstance(r, p.CalRefRecord)]
    assert [recs[i].afe for i in cals] == [0, 1]


def test_channel_mask_and_verbosity_variants():
    fw = new()
    run(fw, "SWEEP 100 1000 3", "CHAN CH2", "VERB COMPACT", wait=0.02)
    meas = [r for r in run(fw, "START 1", wait=0.2) if isinstance(r, p.MeasRecord)]
    assert [m.ch for m in meas] == [2, 2, 2] and meas[0].z_real is None and meas[0].mag_ohm
    fw2 = new()
    run(fw2, "SWEEP 100 1000 2", "CHAN 0x1", "VERB RAW", wait=0.02)
    meas = [r for r in run(fw2, "START 1", wait=0.2) if isinstance(r, p.MeasRecord)]
    assert len(meas) == 2 and meas[0].z_real is not None and meas[0].mag_ohm is None


def test_start_n_cycles_and_stop_when_running():
    fw = new()
    run(fw, "SWEEP 100 1000 2", "CHAN CH0", wait=0.02)
    ms = msgs(run(fw, "START 2", wait=0.3))
    assert [m for m in ms if m.startswith("CYCLE")] == ["CYCLE=1 done", "CYCLE=2 done"]
    fw = MockFirmware(point_interval=0.2)
    fw.open()
    run(fw, "SWEEP 100 1000 50", "CHAN CH0", "START 0", wait=0.05)
    assert "measurement stopped" in msgs(run(fw, "STOP", wait=0.05))
    assert fw.running is False


def test_stop_when_idle_gives_no_reply():
    fw = new()
    assert run(fw, "STOP", wait=0.05) == []


def test_error_does_not_stop_firmware_retries_cycle_until_stop():
    fw = new()
    fw.fault_after_points = 3
    run(fw, "SWEEP 100 1000 5", "CHAN CH0,CH1", wait=0.02)
    recs = run(fw, "START 1", wait=0.4)
    errs = [r for r in recs if isinstance(r, p.InfoRecord) and r.level == "ERR"]
    assert len(errs) >= 2 and fw.running                      # 계속 재시도 중
    assert "measurement stopped" in msgs(run(fw, "STOP", wait=0.05))


def test_reboot_emits_banner_and_clears_state():
    fw = new()
    run(fw, "CHAN CH1", "START 0", wait=0.02)
    out = msgs(run(fw, wait=0.0) + [])
    fw.reboot()
    out = msgs(run(fw, wait=0.02))
    assert out[0] == BANNER and not fw.running and fw.mask == 0x7
