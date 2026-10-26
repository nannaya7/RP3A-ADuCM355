"""Troponin EIS 정량 모델 (numpy 포팅).

원본: refer/Troponin 정량 코드 및 사용방법/eis_concentration_predictor.py (Day-1 보정 `261014-v1`)
원본과 **같은 계산**을 하되 pandas/파일 입출력을 없애고, 메모리의 (주파수, 복소 임피던스) 곡선을 입력으로 받는다.
연구용 임시 모델이다 (원본 docstring): 임상적으로 검증되지 않았다.

단계 이름: 원본의 T1/T2/T3 (= UI 의 T0/T1/T2).
  T1 : 혈액 전 redox probe  / T2 : 혈액 15분 반응 후 / T3 : 세척 후 redox probe
  T2 c0 : 같은 배치의 기준 혈액 T2 (없으면 과거 Day-1 앵커를 쓰고 경고)
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

DEFAULT_MODEL = Path(__file__).resolve().parent / "troponin_day1_calibration.json"
T2_POINTS = 101           # T2 반복은 각각 101 주파수점이어야 한다 (원본 규칙)
Curve = Tuple[np.ndarray, np.ndarray]   # (freq_hz, z complex)


class TroponinInputError(ValueError):
    """입력 데이터가 모델 요구를 만족하지 못함 (재측정 필요)."""


def load_model(path: Path = DEFAULT_MODEL) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---- 곡선 준비 / 보간 -----------------------------------------------------------
def make_curve(freq_hz, magnitude_ohm, phase_deg) -> Curve:
    """원본 read_eis 와 같은 처리: NaN 행 제거, Z = |Z|·exp(j·phase), 주파수 오름차순."""
    f = np.asarray(freq_hz, float)
    mag = np.asarray(magnitude_ohm, float)
    ph = np.asarray(phase_deg, float)
    ok = np.isfinite(f) & np.isfinite(mag) & np.isfinite(ph)
    f, mag, ph = f[ok], mag[ok], ph[ok]
    z = mag * np.exp(1j * np.deg2rad(ph))
    order = np.argsort(f)
    return f[order], z[order]


def interp_complex(freq: np.ndarray, z: np.ndarray, target: np.ndarray) -> np.ndarray:
    if target.min() < freq.min() or target.max() > freq.max():
        raise TroponinInputError(
            f"주파수 범위 부족: 입력 {freq.min():g}–{freq.max():g} Hz, "
            f"필요 {target.min():g}–{target.max():g} Hz")
    x = np.log10(freq)
    xt = np.log10(target)
    return np.interp(xt, x, z.real) + 1j * np.interp(xt, x, z.imag)


def aggregate_repeats(curves: Sequence[Curve], target: Optional[np.ndarray] = None):
    """T1/T3: 목표 격자(기본 첫 곡선)로 보간해 복소 평균."""
    if not curves:
        raise TroponinInputError("측정 곡선이 없습니다.")
    if target is None:
        target = curves[0][0]
    stacked = np.vstack([interp_complex(f, z, target) for f, z in curves])
    return target, np.mean(stacked, axis=0)


# ---- T2 QC ---------------------------------------------------------------------
def rolling_median5(values: np.ndarray) -> np.ndarray:
    padded = np.pad(values, (2, 2), mode="edge")
    return np.array([np.median(padded[i:i + 5]) for i in range(len(values))])


def robust_sigma(values: np.ndarray) -> float:
    median = np.nanmedian(values)
    return float(1.4826 * np.nanmedian(np.abs(values - median)))


def spike_mask(freq: np.ndarray, z: np.ndarray) -> np.ndarray:
    use = freq <= 50000
    logmag = np.log(np.abs(z[use]))
    phase = np.rad2deg(np.unwrap(np.angle(z[use])))
    mag_resid = logmag - rolling_median5(logmag)
    phase_resid = phase - rolling_median5(phase)
    core = np.ones(len(logmag), dtype=bool)
    core[:2] = False
    core[-2:] = False
    bad = core & ((np.abs(mag_resid) > max(6 * robust_sigma(mag_resid[core]), 0.06)) |
                  (np.abs(phase_resid) > max(6 * robust_sigma(phase_resid[core]), 4.0)))
    result = np.zeros(len(freq), dtype=bool)
    result[np.where(use)[0][bad]] = True
    return result


def aggregate_t2_with_qc(curves: Sequence[Curve], target: np.ndarray, names: Optional[Sequence[str]] = None):
    """T2(및 c0): 반복 RMS 이상치 제외 + 고립 스파이크 제거 + nan-중앙값. (z, 유지된 반복 수, 조치 목록)"""
    names = list(names) if names else [f"repeat{i + 1}" for i in range(len(curves))]
    if any(len(f) != T2_POINTS for f, _ in curves):
        raise TroponinInputError(f"T2 반복은 각각 {T2_POINTS}개 주파수점이어야 합니다.")
    if len(curves) < 2:
        raise TroponinInputError("T2 QC에는 최소 2회 반복이 필요합니다.")
    reference = curves[0][0]
    if any(not np.allclose(f, reference) for f, _ in curves[1:]):
        raise TroponinInputError("T2 반복 간 주파수 그리드가 다릅니다.")
    use = reference <= 50000
    stack = np.vstack([z[use] for _, z in curves])
    centre = np.median(stack.real, axis=0) + 1j * np.median(stack.imag, axis=0)
    denom = np.maximum(np.abs(centre), np.median(np.abs(centre)) * 0.02)
    rms = np.sqrt(np.mean(np.abs((stack - centre) / denom) ** 2, axis=1))
    kept, actions = [], []
    for name, (f, z), value in zip(names, curves, rms):
        if value > 0.08:
            actions.append(f"{name}: repeat 제외(complex RMS={value:.3f})")
            continue
        zz = z.astype(complex).copy()
        spikes = spike_mask(f, zz)
        zz[spikes] = np.nan + 1j * np.nan
        if np.any(spikes):
            actions.append(f"{name}: 고립점 {int(spikes.sum())}개 제외")
        kept.append(zz)
    if len(kept) < 2:
        raise TroponinInputError("T2 QC 후 남은 반복이 2개 미만입니다. 재측정하세요.")
    array = np.vstack(kept)
    median_curve = np.nanmedian(array.real, axis=0) + 1j * np.nanmedian(array.imag, axis=0)
    return interp_complex(reference, median_curve, target), len(kept), actions


# ---- 특징량 --------------------------------------------------------------------
def median_band(freq: np.ndarray, values: np.ndarray, low: float, high: float) -> float:
    mask = (freq >= low) & (freq <= high) & np.isfinite(values)
    if not np.any(mask):
        raise TroponinInputError(f"{low:g}–{high:g} Hz 구간 데이터가 없습니다.")
    return float(np.median(values[mask]))


def corrected_d(freq, z1, z3, model: dict, elapsed_min: Optional[float], rtia_ohm: float):
    relative = 100.0 * (z3 - z1) / np.abs(z1)
    d_raw = median_band(freq, relative.imag, 10.0, 50.0)

    phase_freq = np.asarray(model["phase_frequency_hz"], float)
    phase = np.rad2deg(np.angle(interp_complex(freq, z1, phase_freq)))
    phase_scaled = (phase - np.asarray(model["phase_robust_center"])) / np.asarray(model["phase_robust_scale"])
    pcs = (phase_scaled - np.asarray(model["pca_mean"])) @ np.asarray(model["pca_components"]).T
    pcs[0] *= float(model["pc1_sign"])

    elapsed = model["day1_elapsed"]
    elapsed_fraction = 0.0 if elapsed_min is None else (
        float(elapsed_min) - float(elapsed["median"])) / float(elapsed["iqr"])
    nuisance_raw = np.array([pcs[0], pcs[1], elapsed_fraction, np.log10(float(rtia_ohm))], dtype=float)
    nuisance_scaled = (nuisance_raw - np.asarray(model["nuisance_robust_center"], float)) / \
        np.asarray(model["nuisance_robust_scale"], float)
    nuisance = float(nuisance_scaled @ np.asarray(model["nuisance_regression_coef"], float)
                     - float(model["nuisance_component_median"]))
    d_corrected = d_raw - float(model["phase_correction_strength"]) * nuisance
    return d_raw, nuisance, d_corrected


def raw_t2_b(freq: np.ndarray, z2: np.ndarray) -> float:
    return median_band(freq, -z2.imag, 1000.0, 5000.0)


def predict_from_features(d_value: float, b_value: float, model: dict) -> dict:
    d_ok = float(model["D_gate_low"]) <= d_value <= float(model["D_gate_high"])
    b_ok = float(model["B_gate_low"]) <= b_value <= float(model["B_gate_high"])
    d_star = -(d_value - float(model["D_center"])) / float(model["D_scale"])
    b_star = (b_value - float(model["B_center"])) / float(model["B_scale"])
    score = float(model["weight_D"]) * d_star + float(model["weight_B"]) * b_star
    raw_prediction = float(model["intercept"]) + float(model["score_slope"]) * score
    prediction = float(np.clip(raw_prediction, 0.0, 41.0))
    return {
        "qc_pass": bool(d_ok and b_ok),
        "D_qc_pass": bool(d_ok),
        "B_qc_pass": bool(b_ok),
        "D_corrected": float(d_value),
        "B_normalized": float(b_value),
        "D_star": float(d_star),
        "B_star": float(b_star),
        "combined_score": score,
        "prediction_before_clipping": raw_prediction,
        "predicted_concentration": prediction if d_ok and b_ok else None,
        "model_range": [0.0, 41.0],
        "day1_loocv_mae": float(model["day1_loocv_mae"]),
    }


# ---- 전체 파이프라인 -------------------------------------------------------------
@dataclass
class TroponinResult:
    """모델 출력. `value` 는 QC 통과 시에만 있다. 단위는 아직 확정되지 않았다(숫자만 표시)."""
    value: Optional[float]
    qc_pass: bool
    d: float
    b: float
    score: float
    clipped: bool
    model_name: str
    model_version: str
    day1_loocv_mae: float
    warnings: List[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


class TroponinModel:
    def __init__(self, model: Optional[dict] = None, model_path: Path = DEFAULT_MODEL):
        self.model = model if model is not None else load_model(model_path)

    def predict_features(self, d_value: float, b_value: float) -> dict:
        return predict_from_features(d_value, b_value, self.model)

    def predict(self, t1: Sequence[Curve], t2: Sequence[Curve], t3: Sequence[Curve],
                t2_c0: Optional[Sequence[Curve]] = None, elapsed_min: Optional[float] = None,
                rtia_ohm: Optional[float] = None, names: Optional[dict] = None) -> TroponinResult:
        """T1/T2/T3(+c0) 곡선 목록(센서별 1개씩)에서 농도를 계산한다.

        names: {"t2": [...], "t2_c0": [...]} QC 메시지에 쓸 이름 (선택)
        """
        m = self.model
        names = names or {}
        warnings: List[str] = []
        for label, curves in (("T1", t1), ("T2", t2), ("T3", t3)):
            if len(curves) != 3:
                warnings.append(f"{label} 반복 수가 {len(curves)}개입니다(권장 3개).")

        freq, z1 = aggregate_repeats(t1)
        z2, t2_kept, t2_actions = aggregate_t2_with_qc(t2, freq, names.get("t2"))
        _, z3 = aggregate_repeats(t3, freq)
        rtia = float(rtia_ohm or m["default_rtia_ohm"])
        d_raw, nuisance, d_value = corrected_d(freq, z1, z3, m, elapsed_min, rtia)
        t2_raw = raw_t2_b(freq, z2)

        if t2_c0:
            if len(t2_c0) != 3:
                warnings.append(f"T2 c0 반복 수가 {len(t2_c0)}개입니다(권장 3개).")
            z2_c0, c0_kept, c0_actions = aggregate_t2_with_qc(t2_c0, freq, names.get("t2_c0"))
            anchor = raw_t2_b(freq, z2_c0)
            anchor_source = "same_batch_c0"
            t2_actions.extend(c0_actions)
        else:
            anchor = float(m["t2_day1_c0_anchor_ohm"])
            anchor_source = "historical_day1_c0"
            c0_kept = 0
            warnings.append("같은 배치 T2 c0가 없어 과거 Day 1 기준값을 사용했습니다.")
        b_value = (t2_raw - anchor) / float(m["t2_pooled_c0_iqr_ohm"])
        if elapsed_min is None:
            warnings.append("경과시간이 없어 Day 1 중앙시간(보정값 0)을 가정했습니다.")

        out = predict_from_features(d_value, b_value, m)
        return TroponinResult(
            value=out["predicted_concentration"], qc_pass=out["qc_pass"],
            d=d_value, b=b_value, score=out["combined_score"],
            clipped=out["prediction_before_clipping"] != float(np.clip(out["prediction_before_clipping"], 0.0, 41.0)),
            model_name=m["model_name"], model_version=m["model_version"],
            day1_loocv_mae=out["day1_loocv_mae"], warnings=warnings,
            details={**out, "D_raw": d_raw, "D_nuisance_component": nuisance,
                     "T2_neg_imag_raw_ohm": t2_raw, "T2_c0_anchor_ohm": anchor,
                     "T2_anchor_source": anchor_source, "rtia_ohm": rtia, "elapsed_min": elapsed_min,
                     "T2_kept": t2_kept, "T2_c0_kept": c0_kept, "T2_qc_actions": t2_actions},
        )
