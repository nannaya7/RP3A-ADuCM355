# 진단 모델 ② NT-proBNP — POCT V18 추론 패키지 분석

> 분석 대상: `refer/NT-PROBNP_POCT_V18_Inference_Package/`
> - `poct_v18.py` (173줄) — 추론 코드
> - `V18_deployment_bundle.joblib` (94KB) — scikit-learn 모델·스케일러·설정
> - `V18_gate_ensemble.pt` (17KB) — PyTorch 신경망 5개 가중치
> - `example_V18_features.csv` — 입력 예시 (합성값)
> - `README_POCT_V18.txt`
>
> 관련: [models_overview.md](models_overview.md), [model_troponin_eis.md](model_troponin_eis.md)

## 0. 분석 범위와 한계 (먼저 읽기)

| 항목 | 상태 |
|---|---|
| `poct_v18.py`, README, 예시 CSV | ✅ 전체를 읽음 |
| `.joblib` / `.pt` 내부 | **로드(실행)하지 않았다.** pickle 기반이라 신뢰되지 않은 코드 실행 위험이 있고(README도 경고), 이 PC에는 `scikit-learn`, `torch`, `joblib`이 설치되어 있지 않다. 대신 **파일의 문자열·opcode를 정적으로 읽어** 구조(키 이름, 클래스, 일부 상수)를 확인했다. |
| 확인된 클래스 | 정적 점검에서 보인 것은 `sklearn`(GradientBoostingRegressor, DecisionTreeRegressor, StandardScaler, LogisticRegression, Ridge, DummyRegressor, 손실/링크 클래스), `numpy`, `joblib.numpy_pickle`, `torch`(텐서 재구성), `collections.OrderedDict` 뿐이다. (joblib 파일은 배열 바이너리가 중간에 섞여 있어 **끝까지 스캔하지는 못했다**) |
| 읽지 못한 값 | 스케일러 평균/분산, `magnitude_cap`, `nf_logit_scale`, `f_logit_scale`, `direction_constant`, `training_ranges`의 각 최소·최대, 신경망 가중치, 학습 샘플 수 등 → **모델을 실제로 로드해야 알 수 있다.** |
| 실행/검증 | **하지 못함** (패키지 미설치). 실제 동작 확인은 §9의 절차로 |

## 1. 한눈에 보기

| 항목 | 내용 |
|---|---|
| 모델 이름 | `V18_AdditivePhysicsModulated_SoftGate_Deployment_v1` |
| 입력 | **이미 추출된 6개 EIS 특징량** (원시 주파수/실수/허수 임피던스가 **아님**) |
| 출력 | **NT-proBNP 농도, pg/mL** + 중간값·QC 플래그. 배포 정량 구간 **50 ~ 1600 pg/mL** |
| 성격 | 연구용. README: "임상/장치 수준으로 검증되지 않음", QC 플래그는 "범위 휴리스틱일 뿐" |
| 의존 | `numpy`, `pandas`, `scipy`, **`scikit-learn==1.7.0`**(저장 시 버전), `torch`, `joblib` |
| 모델 구성 | ① GradientBoosting 회귀(주 예측) ② 방향 분류(로지스틱) ③ 보정 크기 회귀(릿지) ④ **신경망 게이트 5개 앙상블**(보정을 얼마나 적용할지) |

## 2. 입력 특징량 6개

| 순서 | 이름 | 사용처 | 비고(이름에서 읽히는 의미 — **추정**) |
|---|---|---|---|
| 1 | `HF_Zmag_mean` | matrix 특징 (GBR, 방향 분류) | 고주파(HF) 구간 |Z| 평균 |
| 2 | `HF_Zmag_CV` | matrix 특징 | 같은 구간 |Z|의 변동계수(CV) |
| 3 | `log_CPE_Yratio_10Hz` | nf 특징 (게이트 NN) | CPE 어드미턴스 비율의 로그, 10Hz |
| 4 | `CPE_phase_difference_rad` | nf 특징 | CPE 위상 차(라디안) |
| 5 | `logZratio_10k_1k` | nf 특징 | log(Z(10kHz)/Z(1kHz)) |
| 6 | `delta_Rct_Ohm` | f 특징 (게이트 NN) | 전하전달저항 Rct 변화량(Ω) |

- `matrix_features` = [1, 2] (GBR의 `n_features_in_ = 2`로 확인), `nf_features` = [3, 4, 5], `f_features` = [6].
- 모든 값은 **유한한 숫자**여야 하며 하나라도 없거나 NaN/inf이면 오류.
- **특징 추출 정의(소스)는 패키지에 없다.** README: "추출 정의/소스가 없으면 하드웨어 배포 전에 원본 전처리 구현과 일치시켜야 한다."
  - CPE 피팅, Rct 추출은 등가회로 피팅이 필요해 보이며, **어떤 주파수 구간(HF)·어떤 회로 모델·어떤 측정 단계(delta_Rct의 기준)** 인지 알 수 없다. → **이 모델은 현재 상태로는 GUI에 연결할 수 없다.** (§8)

## 3. 추론 알고리즘 (`POCTV18.predict_one`)

```
입력 6개 → 유한성/누락 검사 → training_ranges 대비 범위 밖 특징 목록 작성

[1] 주 예측 (matrix 모델)
    matrix_log   = GradientBoostingRegressor( [HF_Zmag_mean, HF_Zmag_CV] )
    primary_log  = matrix_log + selected_bias           # selected_bias = 0.95 (로그 단위)
    primary_conc = max(expm1(primary_log), 0)

[2] 방향 결정 (하이브리드 규칙)
    primary_conc < deploy_min(50)   → UP,   p_up=1, source='Range_Low'
    primary_conc > deploy_max(1600) → DOWN, p_up=0, source='Range_High'
    direction_constant 가 있으면    → 그 값(상수), source='Constant'
    그 외                           → LogisticRegression(scaled matrix) → p_up, UP if p_up ≥ 0.5, source='Matrix_Logistic'
    confidence = |2·p_up − 1|

[3] 보정 크기
    magnitude_log1p = Ridge( scaler( [primary_log] ) )
    magnitude       = clip( expm1(magnitude_log1p), 0, magnitude_cap )
    candidate_delta = confidence × (+1 if UP else −1) × magnitude      # 로그 단위

[4] 게이트 입력(candidate state, 6차원)
    [primary_log, p_up, confidence, magnitude, candidate_delta, |candidate_delta|]

[5] 신경망 게이트 (AdditivePhysicsGate × 5, 시드 앙상블)
    logit = base_head(candidate)
          + nf_logit_scale · tanh( nf_head( nf_encoder(nf) ) )      # nf: 3특징 → 4 → 2(tanh)
          + f_logit_scale  · tanh( f_head ( f_encoder (f ) ) )      # f : 1특징 → 2 → 1(tanh)
    p_apply = mean_over_5( sigmoid(logit) )

[6] 최종
    final_log     = primary_log + p_apply × candidate_delta
    concentration = max( expm1(final_log), 0 )                 # pg/mL
    within_output_quant_range = 50 ≤ concentration ≤ 1600
    qc_warning = (특징 범위 밖 존재) or (정량 범위 밖)
```
- 각 스케일러(`direction_scaler`, `magnitude_scaler`, `nf_scaler`, `f_scaler`, `candidate_scaler`)는 `StandardScaler`.
- **Hill 보정은 적용하지 않는다** (Hill 파라미터/학습 흔적이 없음, README 명시).
- 한 줄 요약: **고주파 |Z|의 평균·변동만으로 1차 농도를 구하고(GBR), 나머지 4개 특징(CPE·비율·ΔRct)이 "그 1차 값에 얼마나 보정(위/아래)을 적용할지"를 신경망이 확률로 결정**하는 구조다.

## 4. 번들/가중치 구성 (정적 확인)

`V18_deployment_bundle.joblib` (dict) 키:

| 키 | 설명 |
|---|---|
| `artifact_version` | `V18_AdditivePhysicsModulated_SoftGate_Deployment_v1` — `.pt`의 값과 **반드시 일치**해야 로드됨 |
| `all_features`, `matrix_features`, `nf_features`, `f_features` | 특징량 목록 |
| `candidate_state_columns` | `Primary_Log, P_UP, Direction_Confidence, Predicted_Magnitude_Log, Candidate_Delta_Log, Abs_Candidate_Delta_Log` |
| `deploy_min_conc` = **50.0**, `deploy_max_conc` = **1600.0**, `selected_bias` = **0.95** | 확인된 상수 |
| `matrix_model` | `GradientBoostingRegressor` — **huber 손실, 120 트리, learning_rate 0.03, max_depth 2, subsample 0.8, min_samples_leaf 2, alpha 0.9, random_state 42**, 초기 추정기 `DummyRegressor(constant)` |
| `direction_training_source` (`InRange_Meta`), `direction_constant`, `direction_scaler`, `direction_model` | 방향 분류. 모델은 `LogisticRegression(liblinear, class_weight=balanced)` |
| `magnitude_scaler`, `magnitude_model`(`Ridge`, solver cholesky), `magnitude_alpha`, `magnitude_cap` | 보정 크기 |
| `nf_scaler`, `f_scaler`, `candidate_scaler` | 게이트 입력 스케일러 |
| `training_ranges` | 특징별 학습 범위 {min, max} — 범위 밖 판정에 사용 |
| `encoder_seeds` | NN 시드 목록 — `.pt`와 일치해야 함, **개수 = 앙상블 크기(5)** |
| `nf_hidden`(4), `nf_latent`(2), `f_hidden`(2), `f_latent`(1), `nf_logit_scale`, `f_logit_scale` | NN 구조·스케일 (괄호는 `poct_v18.py` 기본값/가중치 이름에서 확인한 구조) |
| `historical_n`, `gate_training_n`, `gate_apply_n`, `gate_reject_n` | 학습 샘플 수 통계(값은 미확인) |
| `_sklearn_version` | 저장 시 scikit-learn 버전 (README: **1.7.0 권장**) |

`V18_gate_ensemble.pt`: `torch.save` 형식(`weights_only=True`로 로드), `state_dicts` 5개(각각 `base_head`, `nf_encoder.0/2`, `nf_head`, `f_encoder.0/2`, `f_head` 가중치), `artifact_version`, `encoder_seeds`. 총 17KB로 매우 작다.

## 5. 출력 필드 (`predict_one`의 반환)

| 필드 | 의미 |
|---|---|
| **`concentration_pg_mL`** | **최종 농도(pg/mL)** |
| `primary_concentration_pg_mL` | 보정 전(GBR+bias) 농도 |
| `candidate_concentration_pg_mL` | 보정 100% 적용 시 농도 |
| `p_apply`, `p_apply_ensemble_sd` | 보정 적용 확률(5개 평균)과 앙상블 표준편차 — **불확실성 지표로 쓸 수 있음** |
| `direction`, `direction_source`, `p_up`, `direction_confidence` | 방향 결정 근거 |
| `predicted_magnitude_log`, `candidate_delta_log` | 보정 크기 |
| `base_logit_mean`, `delta_nf_logit_mean`, `delta_f_logit_mean` | 게이트 로짓 구성 |
| `out_of_training_range_features` | 학습 범위를 벗어난 입력 특징 이름 |
| `within_output_quant_range`, `quant_range_pg_mL` | 정량 범위(50~1600) 내 여부 |
| **`qc_warning`** | 범위 밖 특징 또는 정량 범위 밖이면 True |

## 6. CLI / API

```bash
python poct_v18.py --input-csv example_V18_features.csv --output-csv predicted.csv
python poct_v18.py --features-json '{"HF_Zmag_mean": ..., ...}'
```
```python
model = POCTV18('V18_deployment_bundle.joblib', 'V18_gate_ensemble.pt')
result = model.predict_one({...6개...})
```
- 예시 CSV의 값은 **학습 범위 평균 같은 합성값(실측 아님)** 이다 — 이 값으로 나온 결과를 "정상 동작 기준"으로 삼으면 안 된다.

## 7. 실행 환경 이슈 (Pi 3A+, Python 3.13.5, Trixie)

| 이슈 | 내용 | 대응 |
|---|---|---|
| **메모리** | `torch` import만으로도 수백 MB가 필요해 **RAM 512MB**의 Pi 3A+에 GUI와 함께 올리기 부담 | 신경망이 **극소형**(5개 × 선형 3~4층, 수십 개 가중치)이므로 **numpy로 직접 구현**하고 가중치를 JSON/npz로 내보내는 방식을 권장 |
| scikit-learn 버전 | pickle은 **저장 시 버전(1.7.0)** 과 맞지 않으면 경고/오류 가능 | Trixie apt의 scikit-learn 버전 확인 필요. 또는 아래처럼 sklearn 의존 제거 |
| sklearn 의존 제거 | 필요한 연산이 GBR(깊이 2 트리 120개 합), `StandardScaler`, 로지스틱 회귀, 릿지뿐 → 모두 **배열 연산**으로 환원 가능 | 트리(`children_left/right`, `feature`, `threshold`, `value`)와 계수를 한 번 추출(PC에서)해 Pi에서는 numpy만 사용 |
| pickle 보안 | joblib/pt는 **신뢰된 출처만** 로드. 실행 코드가 들어갈 수 있다 | 변환 스크립트로 한 번 추출한 뒤 Pi에는 **JSON/npz만** 배포, 원본 파일의 해시를 기록 |
| 패리티 | 변환 후 원본과 수치가 같은지 확인 필수 | 알려진 입력 몇 개(가능하면 검증 샘플)로 원본/포팅 출력 비교 (README도 권고) |

## 8. 이 모델을 GUI에 연결하기 위한 선결 조건 (⚠️ 현재 불가)

1. **특징 추출 코드/정의** — `HF_Zmag_mean/CV`의 HF 범위, `CPE` 피팅 방식(등가회로, 피팅 주파수 구간, 초기값), `delta_Rct_Ohm`의 기준(어느 측정 대비 변화인지), `logZratio_10k_1k`(10kHz/1kHz 정확한 주파수점), `log_CPE_Yratio_10Hz`의 정의. **원본 전처리 구현과 일치해야 한다는 것이 README의 명시 사항**이다.
2. 측정 프로토콜: 몇 단계·몇 회·무슨 반응 시간 (Troponin과 비슷한 전/후 단계인지는 `delta_Rct`로 **추정**만 가능)
3. 사용 스윕 범위/점 수/채널
4. 검증용 실측 특징량 + 정답 농도 샘플 (포팅 패리티·합격 기준)

## 9. 실제 확인 절차 (PC에 패키지 설치 후)

신뢰할 수 있는 출처의 파일임을 확인한 뒤, **모델 변환용 PC에서 일회성으로** 수행한다. 이 패키지(torch, scikit-learn)는 Pi 실행 환경에 설치하지 않는다(§7). 개발 방침상 venv는 쓰지 않으므로 변환 전용 PC 또는 별도 머신을 사용한다.
```bash
pip install numpy pandas scipy scikit-learn==1.7.0 torch joblib      # 변환 전용 PC
python poct_v18.py --input-csv example_V18_features.csv --output-csv predicted.csv
```
1. 예시 CSV 실행 → 출력 필드 확인 (값은 합성이라 의미 없음)
2. `bundle` 안의 스케일러 평균, `magnitude_cap`, `direction_constant`, `training_ranges`, 로짓 스케일을 출력해 **이 문서의 §4 빈칸을 채운다**
3. numpy 포팅 구현과 원본의 출력 비교 (다수 무작위 입력으로 허용 오차 이내 확인)

## 10. 미확인·질문
1. 특징 추출 원본 코드(§8-1)와 정의 문서
2. 실측 샘플(특징량 6개 + 참 농도)
3. 단위·구간의 임상 해석 (50~1600 pg/mL가 NT-proBNP의 의사결정 구간을 덮는지, 컷오프)
4. 보정 `selected_bias=0.95`의 의미(학습 중 선택된 편향 보정으로 추정)와 재학습 계획
5. 모델 버전 관리(현재 `V18`) 및 향후 갱신 시 배포 방식

## 11. 갱신 (2026-10-27) — NumPy 변환 패키지 수령

> 위치: `refer/POCT_V18_NumPy_Ready_261027/poct_numpy/` (요청해서 다시 받은 NumPy 변환본)

### 11.1 해결된 항목
| 항목 | 상태 |
|---|---|
| 모델 가중치 | ✅ `v18_parameters.npz`(스케일러, 트리 120개, 로지스틱, 릿지, 게이트 NN 5개) + `v18_metadata.json`. §0·§4의 "읽지 못한 값"이 채워짐 |
| Pi 추론 | ✅ `numpy_inference.py` — NumPy만 사용 (torch/sklearn 불필요). 예시 입력 → 211.77 pg/mL 로 오류 없이 동작 (이 PC에서 확인) |
| 확인된 수치 | `direction_constant`=null, `magnitude_cap`=2.1998, `nf_logit_scale`=`f_logit_scale`=1.0, `selected_bias`=0.95, `training_ranges` 6개(메타데이터에 있음) |
| 특징 정의 | ✅ `v18_exact_features.py` (§11.2) |

### 11.2 확정된 특징량 정의
| 특징 | 정의 |
|---|---|
| `HF_Zmag_mean` | 10,000~100,000Hz(양끝 포함) 구간 \|Z\|=sqrt(Re²+Im²)의 평균 |
| `HF_Zmag_CV` | 같은 구간 \|Z\|의 표준편차(ddof=0) / (\|평균\|+1e-12) |
| `logZratio_10k_1k` | ln((Z(10k)+1e-12)/(Z(1k)+1e-12)), 로그 주파수 거리가 가장 가까운 점 사용(보간 없음) |
| `CPE_phase_difference_rad` | (Redox_n − Blood_n)·π/2 |
| `log_CPE_Yratio_10Hz` | ln(max(Redox_Q,1e-12)) − ln(max(Blood_Q,1e-12)) + (Redox_n − Blood_n)·ln(2π·10) |
| `delta_Rct_Ohm` | Redox_Rct(목표 농도) − Redox_Rct(**농도 0**), 같은 Sample 번호끼리 |

- Blood_Q/Blood_n 은 Blood 피팅의 `LF_Branch`(2→Q2/n2, 3→Q3/n3)로 고른다. 그 외 값은 무효.
- 이전 추정과 달라진 점: `delta_Rct` 는 반응 전후가 아니라 **농도 0 기준 키트와의 차이**. 따라서 기준(농도 0) 측정이 필요하다.

### 11.3 추가된 보조 모델 (C6 + 구제 rescue)
- `numpy_rescue_inference.py`(`V18C6Rescue`) + `v18_c6_rescue_parameters.npz/json`. 위상 특징 2개(`phase_30000Hz`, `HF_10k_100k_phase_mean`)로 보조 GBR(120 트리)을 돌린다.
  - `phase_30000Hz`: 30kHz에 가장 가까운 점의 위상(°), `HF_10k_100k_phase_mean`: 10k~100kHz 위상 평균(°) (`atan2(Im,Re)`).
- 구제 조건: 1차 예측이 50~1600 pg/mL 밖이거나, 매트릭스 특징의 최대 z > 1.60174 이면 `secondary_pg_mL`을 최종값으로 쓴다. 아니면 기존 V18 값.
- 보정 근거는 과거 16건 + 신규 5건(샘플 3=100 pg/mL 한 점 기준)으로 **작다**. 연구용.

### 11.4 남은 문제
1. **등가회로 피팅 필요**: Redox(Rs,Rct,Q,n,Aw) / Blood(R1,R2,Q2,n2,R3,Q3,n3)를 `scipy.curve_fit`으로 피팅해야 CPE·Rct 3개 특징이 나온다. `eis_fit_bridge.py`가 근사 구현이나 README가 "원래 전체 피팅 과정이 아님"이라 밝힌다. **LF_Branch 선택 규칙은 코드에 없다.** Pi에 scipy(`python3-scipy`) 필요.
2. **측정 단계**: Blood 스펙트럼 + Redox 스펙트럼 + Redox 농도 0 기준이 모두 필요 → 프로토콜 확정 필요.
3. **입력 형식**: 학습은 `B농도-샘플-Re/Im` 열. 장비 출력(SHORT 보정 후 R/X)과 같은 기준인지 확인 필요.
4. **검증**: 원래 PyTorch 게이트 ↔ NumPy 게이트 일치는 **미검증**(README 명시). 실측 검증 샘플(요청 R4)도 패키지에 없음. 구제 모델은 NumPy ↔ 보정된 sklearn 재구성과는 5건에서 일치.
5. 학습·재보정 스크립트(`v18_rescue_c6.py`)는 pandas/sklearn/joblib 이 필요한 PC 전용이다.

### 11.5 앱 연동 (연구개발용, 2026-10-27)
- 코드 `app/models/ntprobnp.py`, 가중치 `app/models/ntprobnp_v18/`, 시험 `tests/test_ntprobnp.py`(변환본 `numpy_rescue_inference` 와 무작위 입력 20건 비교 포함).
- 선택: `config.ini [measure] assay = ntprobnp` (기본 `troponin`). 표시 이름·단위는 `[result] title = NT-proBNP`, `unit = pg/mL` 로 따로 설정.
- 측정은 Troponin 과 같은 3단계, 단계마다 센서 0·1·2 (사용자 확인). 대응(**추정**):
  | 단계 | 모델 입력 |
  |---|---|
  | 0 시료준비 | 농도 0 redox 기준 (delta_Rct 기준) |
  | 1 혈액투입 | Blood 스펙트럼 (HF/비율/위상 특징 + Blood 피팅) |
  | 2 세척후 검증 | 목표 redox 스펙트럼 (Redox 피팅) |
  센서 3개 곡선은 복소 평균해 한 곡선으로 합친다(별도 이상치 제거 없음).
- 정량 범위(50–1600 pg/mL) 밖이면 값을 숨기고 QC 불합격(계산값은 result.json `details.raw_value`). 모든 결과에 "연구개발용" 경고가 붙는다.
- Pi 에는 `python3-scipy` 가 추가로 필요하다(피팅에만 사용, 해당 단계에서 지연 import).
- 위 대응과 LF_Branch 선택(시정수 기준 추정)은 실측 검증 전이다.
