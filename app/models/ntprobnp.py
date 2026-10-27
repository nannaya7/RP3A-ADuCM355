"""NT-proBNP EIS 정량 모델 (POCT V18, numpy 포팅). 연구개발용이다 — 임상적으로 검증되지 않았다.

원본/변환본: refer/POCT_V18_NumPy_Ready_261027/poct_numpy/ (가중치는 app/models/ntprobnp_v18/ 로 복사)
  - 추론: numpy_inference.py, numpy_rescue_inference.py 와 같은 계산 (numpy 만 사용)
  - 특징량 정의: v18_exact_features.py  /  등가회로 피팅: eis_fit_bridge.py (scipy, 지연 import)

입력은 (주파수, 복소 임피던스) 곡선 세 개다.
  blood : 혈액(시료) 스펙트럼 — HF/비율/위상 특징과 Blood CPE 피팅에 쓴다 (학습 엑셀의 `B…-Re/Im`)
  redox : redox probe 스펙트럼 (목표 농도) — Redox CPE/Rct 피팅
  zero  : 같은 키트의 농도 0 redox 스펙트럼 — delta_Rct 기준

원본에 없어서 **추정으로 채운 부분**(결과에 warnings 로 남긴다):
  - Blood 피팅의 LF_Branch(2/3) 선택 규칙: 시정수 R·Q^(1/n) 가 큰(저주파) 가지를 고른다.
  - 피팅에 쓰는 주파수 구간: 입력 전체.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

MODEL_DIR = Path(__file__).resolve().parent / "ntprobnp_v18"
EPS = 1e-12
Curve = Tuple[np.ndarray, np.ndarray]   # (freq_hz, z complex)
FEATURES = ("HF_Zmag_mean", "HF_Zmag_CV", "log_CPE_Yratio_10Hz",
            "CPE_phase_difference_rad", "logZratio_10k_1k", "delta_Rct_Ohm")


class NtProBnpInputError(ValueError):
    """입력 데이터가 모델 요구를 만족하지 못함 (재측정 필요)."""


# ---- V18 추론 (numpy_inference.V18NumPy) ----------------------------------------------
def _tree(p, prefix: str, x) -> float:
    x = np.asarray(x, dtype=np.float32)
    left, right = p[prefix + ".children_left"], p[prefix + ".children_right"]
    feat, thr = p[prefix + ".feature"], p[prefix + ".threshold"]
    node = 0
    while left[node] != right[node]:
        node = int(left[node] if x[int(feat[node])] <= thr[node] else right[node])
    return float(p[prefix + ".value"][node].reshape(-1)[0])


class V18:
    def __init__(self, directory: Path = MODEL_DIR):
        directory = Path(directory)
        self.p = np.load(directory / "v18_parameters.npz", allow_pickle=False)
        self.meta = json.loads((directory / "v18_metadata.json").read_text(encoding="utf-8"))

    def _std(self, name, x):
        return (np.asarray(x, dtype=np.float64) - self.p[f"{name}.mean_"]) / self.p[f"{name}.scale_"]

    def _gate_parts(self, i, nf, f, candidate=None):
        """(base, nf, f) 로짓. candidate 가 없으면 base 는 None."""
        w = lambda k: self.p[f"gate_{i}.{k}"]
        lin = lambda name, x, act: (np.tanh if act else (lambda v: v))(x @ w(name + ".weight").T + w(name + ".bias"))
        base = None if candidate is None else float(lin("base_head", candidate, False)[0])
        n = lin("nf_encoder.2", lin("nf_encoder.0", nf, True), True)
        n = float(np.tanh(n @ w("nf_head.weight").T)[0]) * self.meta["nf_logit_scale"]
        g = lin("f_encoder.2", lin("f_encoder.0", f, True), True)
        g = float(np.tanh(g @ w("f_head.weight").T)[0]) * self.meta["f_logit_scale"]
        return base, n, g

    def old_nff(self, values: dict) -> Tuple[float, float]:
        """게이트의 NF/F 변조 로짓을 5개 시드에서 평균 (구제 모델이 쓴다)."""
        m = self.meta
        nf = self._std("nf_scaler", [values[k] for k in m["nf_features"]]).astype(np.float32)
        f = self._std("f_scaler", [values[k] for k in m["f_features"]]).astype(np.float32)
        parts = [self._gate_parts(i, nf, f) for i in range(m["gate_count"])]
        return float(np.mean([a[1] for a in parts])), float(np.mean([a[2] for a in parts]))

    def predict(self, features: dict) -> dict:
        m, p = self.meta, self.p
        missing = [k for k in m["all_features"] if k not in features]
        if missing:
            raise NtProBnpInputError(f"특징량 누락: {missing}")
        values = {k: float(features[k]) for k in m["all_features"]}
        if not np.isfinite(list(values.values())).all():
            raise NtProBnpInputError("특징량에 NaN/inf 가 있습니다.")
        outside = [k for k, v in values.items()
                   if not (m["training_ranges"][k]["min"] <= v <= m["training_ranges"][k]["max"])]
        x = np.array([values[k] for k in m["matrix_features"]], dtype=np.float64)
        primary_log = float(p["matrix_model.init_constant"].reshape(-1)[0])
        primary_log += m["tree_learning_rate"] * sum(_tree(p, f"tree_{i:03d}", x) for i in range(m["n_trees"]))
        primary_log += m["selected_bias"]
        primary = max(float(np.expm1(primary_log)), 0.0)

        if primary < m["deploy_min_conc"]:
            direction, p_up, source = 1, 1.0, "Range_Low"
        elif primary > m["deploy_max_conc"]:
            direction, p_up, source = 0, 0.0, "Range_High"
        elif m["direction_constant"] is not None:
            direction = int(m["direction_constant"])
            p_up, source = float(direction), "Constant"
        else:
            d = self._std("direction_scaler", x)
            logit = float(np.dot(p["direction_model.coef_"].reshape(-1), d)
                          + p["direction_model.intercept_"].reshape(-1)[0])
            p_up = float(1 / (1 + np.exp(-logit)))
            direction, source = int(p_up >= 0.5), "Matrix_Logistic"
        confidence = abs(2 * p_up - 1)
        mg_x = self._std("magnitude_scaler", [primary_log])
        mg_log = float(np.dot(p["magnitude_model.coef_"].reshape(-1), mg_x)
                       + p["magnitude_model.intercept_"].reshape(-1)[0])
        magnitude = min(max(float(np.expm1(mg_log)), 0.0), m["magnitude_cap"])
        delta = confidence * (1 if direction else -1) * magnitude
        candidate = self._std("candidate_scaler", [primary_log, p_up, confidence, magnitude, delta,
                                                   abs(delta)]).astype(np.float32)
        nf = self._std("nf_scaler", [values[k] for k in m["nf_features"]]).astype(np.float32)
        f = self._std("f_scaler", [values[k] for k in m["f_features"]]).astype(np.float32)
        logits = []
        for i in range(m["gate_count"]):
            base, n, g = self._gate_parts(i, nf, f, candidate)
            logits.append(base + n + g)
        probs = 1 / (1 + np.exp(-np.asarray(logits, dtype=np.float64)))
        p_apply = float(probs.mean())
        final = max(float(np.expm1(primary_log + p_apply * delta)), 0.0)
        within = m["deploy_min_conc"] <= final <= m["deploy_max_conc"]
        return {
            "concentration_pg_mL": final, "primary_concentration_pg_mL": primary,
            "p_apply": p_apply, "p_apply_ensemble_sd": float(np.std(probs, ddof=1)) if len(probs) > 1 else 0.0,
            "direction": "UP" if direction else "DOWN", "direction_source": source,
            "p_up": p_up, "direction_confidence": confidence, "candidate_delta_log": delta,
            "out_of_training_range_features": outside, "within_output_quant_range": within,
            "qc_warning": bool(outside or not within),
        }


# ---- C6 보조 모델 + 구제 (numpy_rescue_inference.V18C6Rescue) ---------------------------
class Rescue:
    def __init__(self, v18: V18, directory: Path = MODEL_DIR):
        directory = Path(directory)
        self.v18 = v18
        self.p = np.load(directory / "v18_c6_rescue_parameters.npz", allow_pickle=False)
        self.meta = json.loads((directory / "v18_c6_rescue_metadata.json").read_text(encoding="utf-8"))

    def predict(self, features: dict, frozen: Optional[dict] = None) -> dict:
        c6 = np.asarray([float(features[k]) for k in self.meta["secondary_features"]], dtype=np.float64)
        if not np.isfinite(c6).all():
            raise NtProBnpInputError("C6 특징량에 NaN/inf 가 있습니다.")
        frozen = frozen or self.v18.predict(features)
        primary, original = frozen["primary_concentration_pg_mL"], frozen["concentration_pg_mL"]
        dn, df = self.v18.old_nff({k: float(features[k]) for k in self.v18.meta["all_features"]})
        c6_log = float(self.p["c6.init_constant"].reshape(-1)[0])
        c6_log += self.meta["c6_learning_rate"] * sum(
            _tree(self.p, f"c6_tree_{i:03d}", c6) for i in range(self.meta["c6_n_trees"]))
        c6_log += self.meta["c6_bias"]
        secondary = max(float(np.expm1(c6_log + dn + df)), 0.0)
        matrix = np.asarray([float(features[k]) for k in self.meta["matrix_features"]])
        maxz = float(np.max(abs((matrix - self.p["matrix_mean"]) / self.p["matrix_scale"])))
        by_range = bool(primary < self.meta["deploy_min_conc"] or primary > self.meta["deploy_max_conc"])
        by_z = bool(maxz > self.meta["maxz_threshold"])
        rescue = by_range or by_z
        return {"secondary_pg_mL": secondary, "matrix_maxz": maxz, "rescue_by_range": by_range,
                "rescue_by_maxz": by_z, "rescue": rescue, "final_pg_mL": secondary if rescue else original}


# ---- 곡선 준비 / 특징량 ------------------------------------------------------------------
def make_curve(freq_hz, magnitude_ohm, phase_deg) -> Curve:
    f = np.asarray(freq_hz, float)
    mag = np.asarray(magnitude_ohm, float)
    ph = np.asarray(phase_deg, float)
    ok = np.isfinite(f) & np.isfinite(mag) & np.isfinite(ph) & (f > 0)
    f, z = f[ok], mag[ok] * np.exp(1j * np.deg2rad(ph[ok]))
    order = np.argsort(f)
    return f[order], z[order]


def _nearest(freq: np.ndarray, values: np.ndarray, target: float) -> float:
    return float(values[np.argmin(abs(np.log10(freq) - np.log10(target)))])


def raw_features(curve: Curve) -> dict:
    """v18_exact_features.raw_features + v18_rescue_c6.matrix_c6 와 같은 공식."""
    f, z = curve
    if len(f) < 5:
        raise NtProBnpInputError("스펙트럼 점이 5개 미만입니다.")
    zmag = np.abs(z)
    hf = (f >= 1e4) & (f <= 1e5)
    if not hf.any():
        raise NtProBnpInputError("10k–100kHz 구간 데이터가 없습니다.")
    mean = float(np.mean(zmag[hf]))
    cv = float(np.std(zmag[hf]) / (abs(mean) + EPS))
    phase = np.degrees(np.arctan2(z.imag, z.real))
    out = {"HF_Zmag_mean": mean, "HF_Zmag_CV": cv,
           "logZratio_10k_1k": float(np.log((_nearest(f, zmag, 1e4) + EPS) / (_nearest(f, zmag, 1e3) + EPS))),
           "phase_30000Hz": _nearest(f, phase, 3e4)}
    if hf.sum() < 3:
        raise NtProBnpInputError("10k–100kHz 구간 점이 3개 미만입니다.")
    out["HF_10k_100k_phase_mean"] = float(np.mean(phase[hf]))
    return out


# ---- 등가회로 피팅 (eis_fit_bridge) — scipy 는 여기서만, 지연 import -----------------------
def _redox_z(w, Rs, Rct, Q, n, Aw):
    jw = 1j * w
    return Rs + 1 / (1 / (1 / (Q * jw ** n)) + 1 / (Rct + Aw / np.sqrt(jw)))


def _blood_z(w, R1, R2, Q2, n2, R3, Q3, n3):
    jw = 1j * w
    return R1 + 1 / (1 / R2 + Q2 * jw ** n2) + 1 / (1 / R3 + Q3 * jw ** n3)


_BOUNDS = {
    "redox": (["Rs", "Rct", "Q", "n", "Aw"], _redox_z, ([0, 0, 1e-10, .5, 0], [1e4, 1e6, 1e-3, 1., 1e6])),
    "blood": (["R1", "R2", "Q2", "n2", "R3", "Q3", "n3"], _blood_z,
              ([0, 0, 1e-10, .5, 0, 1e-10, .5], [5e3, 1e7, 1e-3, 1., 1e8, 1e-3, 1.])),
}


def fit_circuit(curve: Curve, circuit: str) -> dict:
    from scipy.optimize import curve_fit        # Pi 에 python3-scipy 가 필요하다 (NT-proBNP 만 사용)
    freq, z = curve
    if len(freq) < 7:
        raise NtProBnpInputError("피팅에는 7점 이상이 필요합니다.")
    keys, fn, bounds = _BOUNDS[circuit]
    if circuit == "redox":
        rs = max(float(z.real.min()), 1e-3)
        p0 = [rs, max(float(z.real.max()) - rs, 100), 1e-6, .9, 1000]
    else:
        p0 = [max(float(z.real.min()), 50), 500, 1e-6, .8, 300000, 5e-7, .95]
    lower, upper = map(np.asarray, bounds)
    p0 = np.clip(p0, lower + 1e-15, upper - 1e-15)
    sigma = np.concatenate([np.maximum(abs(z), 1e-12)] * 2)
    target = np.concatenate([z.real, z.imag])

    def model(w, *params):
        pred = fn(w, *params)
        return np.concatenate([pred.real, pred.imag])

    try:
        popt, _ = curve_fit(model, 2 * np.pi * freq, target, p0=p0, bounds=bounds, sigma=sigma, maxfev=20000)
    except (RuntimeError, ValueError) as e:
        raise NtProBnpInputError(f"{circuit} 등가회로 피팅 실패: {e}") from e
    return dict(zip(keys, map(float, popt)))


def blood_lf_branch(fit: dict) -> int:
    """LF_Branch 추정: 시정수 R·Q^(1/n) 가 큰 가지(저주파 쪽)."""
    tau = {b: fit[f"R{b}"] * fit[f"Q{b}"] ** (1.0 / fit[f"n{b}"]) for b in (2, 3)}
    return 2 if tau[2] >= tau[3] else 3


def fit_features(blood_fit: dict, redox_fit: dict, zero_fit: dict, branch: Optional[int] = None) -> dict:
    """v18_exact_features.combine_features 의 공식 (CPE 위상차, 10Hz Y 비, ΔRct)."""
    branch = branch or blood_lf_branch(blood_fit)
    bq, bn = blood_fit[f"Q{branch}"], blood_fit[f"n{branch}"]
    rq, rn = redox_fit["Q"], redox_fit["n"]
    return {"CPE_phase_difference_rad": (rn - bn) * np.pi / 2,
            "log_CPE_Yratio_10Hz": float(np.log(max(rq, EPS)) - np.log(max(bq, EPS))
                                         + (rn - bn) * np.log(2 * np.pi * 10)),
            "delta_Rct_Ohm": redox_fit["Rct"] - zero_fit["Rct"]}


# ---- 전체 파이프라인 -----------------------------------------------------------------------
@dataclass
class NtProBnpResult:
    """`value` 는 pg/mL. 정량 범위(50–1600) 밖이면 None(QC 불합격)이고 계산값은 details["raw_value"] 에 있다. 연구용."""
    value: Optional[float]
    qc_pass: bool
    rescued: bool
    features: dict
    model_name: str
    model_version: str
    warnings: List[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


class NtProBnpModel:
    # 앱의 3단계(시료준비 → 혈액투입 → 세척후 검증)와의 대응 (Troponin 과 같은 순서의 측정, 사용자 확인):
    #   단계 0 시료준비  = redox probe, 키트에 시료 없음  → 농도 0 기준 (delta_Rct 의 기준)
    #   단계 1 혈액투입  = 혈액 스펙트럼                  → Blood 피팅, HF/비율/위상 특징
    #   단계 2 세척후    = 세척 후 redox probe            → 목표 Redox 피팅
    # 각 단계의 센서 0·1·2 곡선은 복소 평균해 한 곡선으로 합친다.
    def __init__(self, directory: Path = MODEL_DIR, use_rescue: bool = True):
        self.v18 = V18(directory)
        self.rescue = Rescue(self.v18, directory) if use_rescue else None

    def predict_features(self, features: dict) -> NtProBnpResult:
        warnings: List[str] = []
        frozen = self.v18.predict(features)
        raw, rescued, details = frozen["concentration_pg_mL"], False, {"v18": frozen}
        if self.rescue is not None:
            r = self.rescue.predict(features, frozen)
            details["rescue"] = r
            raw, rescued = r["final_pg_mL"], r["rescue"]
            if rescued:
                warnings.append("구제(C6) 보조 모델 값을 사용했습니다 (1차 예측이 범위 밖이거나 매트릭스 특징이 학습 분포에서 멀음).")
        if frozen["out_of_training_range_features"]:
            warnings.append("학습 범위를 벗어난 특징: " + ", ".join(frozen["out_of_training_range_features"]))
        lo, hi = self.v18.meta["deploy_min_conc"], self.v18.meta["deploy_max_conc"]
        in_range = bool(np.isfinite(raw) and lo <= raw <= hi)
        if not in_range:
            warnings.append(f"정량 범위({lo:g}–{hi:g} pg/mL) 밖의 값입니다.")
        details["raw_value"] = raw
        return NtProBnpResult(value=raw if in_range else None, qc_pass=in_range, rescued=rescued,
                              features=dict(features), model_name=self.v18.meta["artifact_version"],
                              model_version="V18+C6" if self.rescue is not None else "V18",
                              warnings=warnings, details=details)

    def predict_curves(self, zero: Curve, blood: Curve, redox: Curve) -> NtProBnpResult:
        feats = raw_features(blood)
        b, r, z = fit_circuit(blood, "blood"), fit_circuit(redox, "redox"), fit_circuit(zero, "redox")
        branch = blood_lf_branch(b)
        feats.update(fit_features(b, r, z, branch))
        res = self.predict_features(feats)
        res.warnings.append(f"Blood LF_Branch={branch} 는 시정수 기준 추정값입니다 (원본 규칙 미확인).")
        res.details["fits"] = {"blood": b, "redox": r, "zero": z, "lf_branch": branch}
        return res

    def predict(self, t1: Sequence[Curve], t2: Sequence[Curve], t3: Sequence[Curve], t2_c0=None,
                elapsed_min=None, rtia_ohm=None, names=None) -> NtProBnpResult:
        """Troponin 모델과 같은 호출 형태 (MeasureController 가 그대로 부른다). t1/t2/t3 = 단계 0/1/2 의 센서별 곡선."""
        from app.models.troponin import TroponinInputError, aggregate_repeats
        try:
            zero, blood, redox = (aggregate_repeats(c) for c in (t1, t2, t3))
        except TroponinInputError as e:
            raise NtProBnpInputError(str(e)) from e
        res = self.predict_curves(zero, blood, redox)
        res.warnings.insert(0, "연구개발용 모델입니다. 임상 판정에 쓰지 마세요.")
        return res
