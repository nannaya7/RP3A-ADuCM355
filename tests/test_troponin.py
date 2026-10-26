"""Troponin numpy 포팅 검증.

원본 CLI(refer/Troponin …/eis_concentration_predictor.py)를 같은 입력으로 실행해 결과를 비교한다.
원본 폴더나 pandas 가 없으면 패리티 테스트는 건너뛴다 (나머지는 항상 실행).
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from app.models import troponin as T

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL = ROOT / "refer" / "Troponin 정량 코드 및 사용방법" / "eis_concentration_predictor.py"
FREQ = 10 * (200000 / 10) ** (np.arange(101) / 100)      # 10Hz~200kHz, 101점 (확정된 격자)


def randles(rs=100.0, rct=5000.0, c=1e-6):
    w = 2 * np.pi * FREQ
    return rs + rct / (1 + 1j * w * rct * c)


def noisy(rng, z, s=0.002):
    return z * (1 + s * (rng.standard_normal(len(z)) + 1j * rng.standard_normal(len(z))))


def curves(rng, z, n=3, s=0.002):
    out = []
    for _ in range(n):
        zz = noisy(rng, z, s)
        out.append((FREQ.copy(), np.abs(zz), np.degrees(np.angle(zz))))
    return out


def dataset(seed=0, k=15.0, t2_imag=280.0, c0_imag=240.0):
    """합성 T1/T2/T3/c0 (센서 3개씩). k = T3 의 허수부 상대 변화 크기(%)."""
    rng = np.random.default_rng(seed)
    z1 = randles()
    z3 = z1 + np.abs(z1) * 0.01 * 1j * k
    z2 = (150 - t2_imag * 1j) * np.ones(101)
    zc = (150 - c0_imag * 1j) * np.ones(101)
    return {"t1": curves(rng, z1), "t2": curves(rng, z2), "t3": curves(rng, z3), "c0": curves(rng, zc)}


def to_model_curves(raw):
    return [T.make_curve(f, m, p) for f, m, p in raw]


def run_port(ds, use_c0=True, elapsed=None, rtia=None):
    return T.TroponinModel().predict(
        to_model_curves(ds["t1"]), to_model_curves(ds["t2"]), to_model_curves(ds["t3"]),
        to_model_curves(ds["c0"]) if use_c0 else None, elapsed_min=elapsed, rtia_ohm=rtia)


# ---- 문서에 있는 기준값 ---------------------------------------------------------
def test_features_example_from_original_docs():
    out = T.TroponinModel().predict_features(2.9058, 1.4012)
    assert out["qc_pass"] and round(out["predicted_concentration"], 1) == 25.3   # 원본 실행 결과(25.3)
    assert out["combined_score"] == pytest.approx(0.9668, abs=1e-4)


def test_qc_gates_suppress_value():
    m = T.TroponinModel()
    out = m.predict_features(40.0, 0.0)
    assert not out["qc_pass"] and not out["D_qc_pass"] and out["B_qc_pass"]
    assert out["predicted_concentration"] is None
    assert not m.predict_features(0.0, 9.0)["B_qc_pass"]


def test_prediction_is_clipped_to_model_range():
    out = T.TroponinModel().predict_features(-20.0, 4.0)       # 게이트 안쪽 극단 → 상한 41 로 제한
    assert out["qc_pass"] and out["predicted_concentration"] == 41.0
    assert out["prediction_before_clipping"] > 41.0


# ---- 포팅 자체 동작 -------------------------------------------------------------
def test_pipeline_runs_and_reports_provenance():
    r = run_port(dataset(), use_c0=True, elapsed=120.0, rtia=1000)
    assert r.qc_pass and r.value is not None
    assert r.details["T2_anchor_source"] == "same_batch_c0" and r.details["T2_kept"] == 3
    assert not r.warnings


def test_missing_c0_and_elapsed_produce_warnings():
    r = run_port(dataset(), use_c0=False)
    assert r.details["T2_anchor_source"] == "historical_day1_c0"
    assert any("c0" in w for w in r.warnings) and any("경과시간" in w for w in r.warnings)


def test_t2_qc_drops_bad_sensor_and_needs_two():
    ds = dataset()
    bad = ds["t2"][2]
    ds["t2"][2] = (bad[0], bad[1] * 1.4, bad[2])                 # 센서 2 가 크게 어긋남
    r = run_port(ds)
    assert r.details["T2_kept"] == 2 and any("repeat 제외" in a for a in r.details["T2_qc_actions"])
    for i in (1, 2):                                             # 둘 다 어긋나면 남은 반복이 1개 → 재측정
        f, m, p = ds["t2"][i]
        ds["t2"][i] = (f, m * (1.4 + 0.3 * i), p)
    with pytest.raises(T.TroponinInputError):
        run_port(ds)


def test_t2_requires_101_points_and_same_grid():
    ds = dataset()
    short = [(f[:50], m[:50], p[:50]) for f, m, p in ds["t2"]]
    with pytest.raises(T.TroponinInputError):
        T.aggregate_t2_with_qc(to_model_curves(short), FREQ)
    ds2 = dataset()
    f, m, p = ds2["t2"][1]
    ds2["t2"][1] = (f * 1.01, m, p)
    with pytest.raises(T.TroponinInputError):
        T.aggregate_t2_with_qc(to_model_curves(ds2["t2"]), FREQ)


def test_frequency_range_must_cover_the_model_grid():
    ds = dataset()
    narrow = [(f[10:], m[10:], p[10:]) for f, m, p in ds["t1"]]  # 10Hz 쪽이 잘려 위상 PCA 주파수를 못 덮는 경우는 아님 → 보간 범위 검사
    with pytest.raises(T.TroponinInputError):
        T.interp_complex(FREQ[10:], np.ones(91, complex), FREQ)  # 목표가 입력 범위를 벗어남


def test_nan_rows_are_dropped_like_original():
    f = np.array([100.0, 10.0, np.nan, 1000.0])
    cf, cz = T.make_curve(f, [1, 2, 3, 4], [0, 0, 0, np.nan])
    assert list(cf) == [10.0, 100.0] and len(cz) == 2


# ---- 원본 CLI 와의 패리티 ---------------------------------------------------------
def _write_csv(path, rows):
    f, m, p = rows
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("Frequency_Hz,Magnitude_Ohm,Phase_Deg\n")
        for a, b, c in zip(f, m, p):
            fh.write(f"{float(a)!r},{float(b)!r},{float(c)!r}\n")   # numpy 2 의 repr(np.float64) 회피


def run_original(tmp_path, ds, use_c0, elapsed, rtia):
    args = [sys.executable, "-I", str(ORIGINAL)]
    for key, flag in (("t1", "--t1"), ("t2", "--t2"), ("t3", "--t3"), ("c0", "--t2-c0")):
        if key == "c0" and not use_c0:
            continue
        files = []
        for i, rows in enumerate(ds[key]):
            path = tmp_path / f"{key}_{i}.csv"
            _write_csv(path, rows)
            files.append(str(path))
        args += [flag] + files
    if elapsed is not None:
        args += ["--elapsed-min", str(elapsed)]
    if rtia is not None:
        args += ["--rtia-ohm", str(rtia)]
    out = tmp_path / "out.json"
    args += ["--output", str(out)]
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    assert out.exists(), proc.stderr
    return json.loads(out.read_text(encoding="utf-8")), proc.returncode


needs_original = pytest.mark.skipif(not ORIGINAL.exists(), reason="원본 Troponin 코드 폴더가 없음")


@needs_original
@pytest.mark.parametrize("name,kw,mod", [
    ("정상+c0", dict(use_c0=True, elapsed=120.0, rtia=1000), {}),
    ("c0 없음+경과시간 없음", dict(use_c0=False, elapsed=None, rtia=None), {}),
    ("rtia/경과시간 다름", dict(use_c0=True, elapsed=300.0, rtia=2000), {"seed": 7}),
    ("D 작은 변화", dict(use_c0=True, elapsed=60.0, rtia=1000), {"k": 4.0, "seed": 3}),
    ("QC 실패(D 범위 초과)", dict(use_c0=True, elapsed=120.0, rtia=1000), {"k": 80.0}),
])
def test_parity_with_original_cli(tmp_path, name, kw, mod):
    ds = dataset(**mod)
    orig, code = run_original(tmp_path, ds, **kw)
    mine = run_port(ds, **kw)
    assert mine.qc_pass == orig["qc_pass"]
    assert code == (0 if orig["qc_pass"] else 2)
    assert mine.d == pytest.approx(orig["D_corrected"], rel=1e-7, abs=1e-9)
    assert mine.b == pytest.approx(orig["B_normalized"], rel=1e-7, abs=1e-9)
    assert mine.score == pytest.approx(orig["combined_score"], rel=1e-7, abs=1e-9)
    assert mine.details["D_raw"] == pytest.approx(orig["D_raw"], rel=1e-7, abs=1e-9)
    assert mine.details["T2_neg_imag_raw_ohm"] == pytest.approx(orig["T2_neg_imag_raw_ohm"], rel=1e-9)
    assert mine.details["T2_anchor_source"] == orig["T2_anchor_source"]
    if orig["qc_pass"]:
        assert mine.value == pytest.approx(orig["predicted_concentration"], rel=1e-7)
    else:
        assert mine.value is None and orig["predicted_concentration"] is None


@needs_original
def test_parity_with_qc_actions_spike_and_bad_repeat(tmp_path):
    """T2 에 고립 스파이크와 이상 반복을 넣어 QC 분기까지 원본과 같은지 본다."""
    ds = dataset(seed=11)
    f, m, p = ds["t2"][0]
    m = m.copy()
    m[40] *= 1.6                                                # 고립 스파이크
    ds["t2"][0] = (f, m, p)
    f, m, p = ds["t2"][2]
    ds["t2"][2] = (f, m * 1.5, p)                               # 이상 반복
    orig, _ = run_original(tmp_path, ds, True, 120.0, 1000)
    mine = run_port(ds, True, 120.0, 1000)
    assert mine.details["T2_kept"] == orig["repeat_counts"]["T2_kept"] == 2
    assert [a.split(":", 1)[1] for a in mine.details["T2_qc_actions"]] == \
           [a.split(":", 1)[1] for a in orig["T2_qc_actions"]]
    assert mine.b == pytest.approx(orig["B_normalized"], rel=1e-7, abs=1e-9)
    assert mine.d == pytest.approx(orig["D_corrected"], rel=1e-7, abs=1e-9)
