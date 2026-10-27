"""NT-proBNP(V18) numpy 포팅 검증.

변환본(refer/POCT_V18_NumPy_Ready_261027)의 numpy_inference/numpy_rescue_inference 와 같은 입력으로 비교한다.
변환본 폴더나 scipy 가 없으면 해당 테스트만 건너뛴다.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from app.models import ntprobnp as N

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "refer" / "POCT_V18_NumPy_Ready_261027" / "poct_numpy"
HAS_SCIPY = importlib.util.find_spec("scipy") is not None
FREQ = 10 * (200000 / 10) ** (np.arange(101) / 100)

MEAN = {"HF_Zmag_mean": 152.42446252774226, "HF_Zmag_CV": 0.2059837727918813,
        "log_CPE_Yratio_10Hz": 0.3664958133381485, "CPE_phase_difference_rad": 0.051843761706316674,
        "logZratio_10k_1k": -1.226511233745992, "delta_Rct_Ohm": -12450.288048689381,
        "phase_30000Hz": -20.0, "HF_10k_100k_phase_mean": -15.0}


def test_example_features_give_the_reference_value():
    res = N.NtProBnpModel().predict_features(MEAN)
    assert res.value == pytest.approx(211.7711, abs=1e-3)       # 변환본 numpy_inference 의 출력
    assert res.qc_pass and not res.rescued


@pytest.mark.skipif(not REF.exists(), reason="reference package missing")
def test_matches_the_reference_numpy_package():
    sys.path.insert(0, str(REF))
    try:
        from numpy_rescue_inference import V18C6Rescue
        ref = V18C6Rescue(REF / "v18_parameters.npz", REF / "v18_metadata.json",
                          REF / "v18_c6_rescue_parameters.npz", REF / "v18_c6_rescue_metadata.json")
    finally:
        sys.path.remove(str(REF))
    model = N.NtProBnpModel()
    rng = np.random.default_rng(1)
    ranges = model.v18.meta["training_ranges"]
    for _ in range(20):
        f = {k: rng.uniform(v["min"], v["max"]) for k, v in ranges.items()}
        f.update(phase_30000Hz=rng.uniform(-40, 0), HF_10k_100k_phase_mean=rng.uniform(-40, 0))
        want = ref.predict_one(f)
        got = model.rescue.predict(f)
        assert got["final_pg_mL"] == pytest.approx(want["final_pg_mL"], rel=1e-9)
        assert got["secondary_pg_mL"] == pytest.approx(want["secondary_pg_mL"], rel=1e-9)
        assert got["rescue"] == want["rescue"]


def test_missing_or_nan_features_are_rejected():
    model = N.NtProBnpModel()
    with pytest.raises(N.NtProBnpInputError):
        model.predict_features({k: v for k, v in MEAN.items() if k != "delta_Rct_Ohm"})
    with pytest.raises(N.NtProBnpInputError):
        model.predict_features({**MEAN, "HF_Zmag_CV": float("nan")})


def test_out_of_range_result_is_withheld():
    far = {**MEAN, "HF_Zmag_mean": 400.0}
    res = N.NtProBnpModel(use_rescue=False).predict_features(far)
    assert "HF_Zmag_mean" in res.details["v18"]["out_of_training_range_features"]
    if res.value is None:
        assert not res.qc_pass and res.details["raw_value"] is not None


def test_raw_features_use_the_documented_formulas():
    z = 100 * np.exp(-1j * np.deg2rad(20)) * np.ones_like(FREQ)
    f = N.raw_features((FREQ, z))
    assert f["HF_Zmag_mean"] == pytest.approx(100.0)
    assert f["HF_Zmag_CV"] == pytest.approx(0.0, abs=1e-9)
    assert f["logZratio_10k_1k"] == pytest.approx(0.0, abs=1e-9)
    assert f["phase_30000Hz"] == pytest.approx(-20.0)


def _curve(fn, *params):
    return FREQ, fn(2 * np.pi * FREQ, *params)


@pytest.mark.skipif(not HAS_SCIPY, reason="scipy missing")
def test_circuit_fit_recovers_parameters():
    blood = _curve(N._blood_z, 100, 800, 2e-6, .85, 2.5e5, 6e-7, .95)
    redox = _curve(N._redox_z, 200, 5e4, 1e-7, .9, 3000)
    fb, fr = N.fit_circuit(blood, "blood"), N.fit_circuit(redox, "redox")
    assert N._blood_z(2 * np.pi * FREQ, *fb.values()) == pytest.approx(blood[1], rel=1e-2)
    assert N._redox_z(2 * np.pi * FREQ, *fr.values()) == pytest.approx(redox[1], rel=1e-2)
    assert N.blood_lf_branch(fb) in (2, 3)


@pytest.mark.skipif(not HAS_SCIPY, reason="scipy missing")
def test_full_pipeline_from_three_stages():
    rng = np.random.default_rng(0)

    def sensors(fn, *params):
        out = []
        for _ in range(3):
            z = fn(2 * np.pi * FREQ, *params)
            out.append((FREQ.copy(), z * (1 + 0.001 * (rng.standard_normal(101) + 1j * rng.standard_normal(101)))))
        return out

    t1 = sensors(N._redox_z, 200, 6e4, 1e-7, .9, 3000)          # 시료준비 (농도 0 기준)
    t2 = sensors(N._blood_z, 100, 800, 2e-6, .85, 2.5e5, 6e-7, .95)  # 혈액투입
    t3 = sensors(N._redox_z, 200, 5e4, 1e-7, .9, 3000)          # 세척후 검증
    res = N.NtProBnpModel().predict(t1, t2, t3)
    assert set(N.FEATURES) <= set(res.features)
    assert res.features["delta_Rct_Ohm"] == pytest.approx(-1e4, rel=0.1)
    assert res.warnings[0].startswith("연구개발용")
    assert res.details["fits"]["lf_branch"] in (2, 3)
