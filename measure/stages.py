"""측정 단계 정의와 측정 설정. Qt 의존 없음.

화면에 보이는 단계 이름(label)은 모델과 무관한 공통 이름 "시료준비 → 혈액투입 → 세척후 검증" 이다.
내부 식별자(key, 결과 파일/로그에 남는 이름)는 T0/T1/T2, Troponin 모델 코드의 이름은 T1/T2/T3 이다 (docs/models_overview.md §0.05).
"""
from dataclasses import dataclass
from typing import Optional, Tuple

# 화면에 보이는 공통 단계 이름 (모델이 달라도 같은 이름을 쓴다. NT-proBNP 는 모델 담당자와 협의 후 확정)
STAGE_LABELS = ("시료준비", "혈액투입", "세척후 검증")


@dataclass(frozen=True)
class StageDef:
    key: str                  # 내부 식별자 (T0, T1, T2) — result.json / raw.log 에 남는다. 화면에는 label 을 쓴다
    code_name: str            # 모델 코드의 이름 (T1, T2, T3)
    title: str
    prompt: str               # 이 단계를 시작하기 전 사용자 안내
    wait_before_s: int = 0    # 시작 전 반응 대기(초). 끝나기 전에는 시작 버튼이 비활성
    auto_start: bool = False  # 직전 단계가 끝나면 자동 시작 (T2 자동/수동은 담당자와 협의 후 결정 → 기본 수동)
    label: str = ""           # 화면에 보이는 공통 단계 이름 (시료준비 / 혈액투입 / 세척후 검증)


@dataclass(frozen=True)
class MeasureSettings:
    start_hz: float = 10.0          # 확정: 10Hz ~ 200kHz, 101점
    stop_hz: float = 200000.0
    points: int = 101
    channels: Tuple[int, ...] = (0, 1, 2)   # 센서 0, 1, 2 (펌웨어 CH0~CH2)
    rtia_ohm: float = 1000.0
    elapsed_min: Optional[float] = None     # 배치 시작 후 경과 시간(분). 없으면 모델이 Day-1 중앙값을 가정하고 경고
    c0_source: str = "first"                # "first": c0 = 첫 측정(시료준비, 센서 0·1·2) 결과 / "none": 과거 Day-1 기준값 + 경고
    reaction_timer_start: str = "auto"      # "auto": 이전 단계가 끝나면 타이머 시작 / "manual": 사용자가 [혈액 투입 완료]를 누르면 시작


def troponin_stages(reaction_wait_s: int = 900, auto_start_last: bool = False):
    return [
        StageDef("T0", "T1", "1 · 시료준비",
                 "센서에 아무것도 올리지 않은 상태에서 [측정 시작]을 누르세요.\n센서 0 → 1 → 2 순서로 측정합니다.",
                 label=STAGE_LABELS[0]),
        StageDef("T1", "T2", "2 · 혈액투입",
                 "센서에 혈액을 투입하고 반응이 끝날 때까지 기다리세요.\n타이머가 끝나면 [측정 시작] 버튼이 활성화됩니다.",
                 wait_before_s=reaction_wait_s, label=STAGE_LABELS[1]),
        StageDef("T2", "T3", "3 · 세척후 검증",
                 "센서를 세척한 뒤 [측정 시작]을 누르세요.",
                 auto_start=auto_start_last, label=STAGE_LABELS[2]),
    ]
