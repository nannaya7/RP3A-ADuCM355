"""측정 단계 정의와 측정 설정. Qt 의존 없음.

화면에 보이는 단계 이름(label)은 모델과 무관한 공통 이름 "시료준비 → 혈액투입 → 세척후 검증" 이다.
내부 식별자(key, 결과 파일/로그에 남는 이름)는 T0/T1/T2, Troponin 모델 코드의 이름은 T1/T2/T3 이다 (docs/models_overview.md §0.05).
"""
from dataclasses import dataclass
from typing import Optional, Tuple

# 화면에 보이는 공통 단계 이름 (모델이 달라도 같은 이름을 쓴다. NT-proBNP 는 모델 담당자와 협의 후 확정)
STAGE_LABELS = ("시료준비", "혈액투입")


@dataclass(frozen=True)
class StageDef:
    key: str                  # 내부 식별자 (T0, T1, T2) — result.json / raw.log 에 남는다. 화면에는 label 을 쓴다
    code_name: str            # 모델 코드의 이름 (T1, T2, T3)
    title: str
    prompt: str               # 이 단계를 시작하기 전 사용자 안내
    wait_before_s: int = 0    # 시작 전 반응 대기(초). 끝나기 전에는 시작 버튼이 비활성
    auto_start: bool = False  # 직전 단계가 끝나면 자동 시작 (T2 자동/수동은 담당자와 협의 후 결정 → 기본 수동)
    label: str = ""           # 화면에 보이는 공통 단계 이름 (시료준비 / 혈액투입 / 세척후 검증)
    measure: bool = True      # False: 측정하지 않는 단계 (검사 시작을 누르면 바로 다음 단계로 넘어간다)
    cycles: int = 1           # 이 단계에서 반복해서 측정하는 횟수 (START <cycles>). 센서마다 points × cycles 점


@dataclass(frozen=True)
class MeasureSettings:
    start_hz: float = 1000.0        # 데모: 1kHz ~ 10kHz, 10점
    stop_hz: float = 10000.0
    points: int = 10
    channels: Tuple[int, ...] = (0, 1, 2)   # 센서 0, 1, 2 (펌웨어 CH0~CH2)
    rtia: str = "AUTO"               # RTIA: AUTO(자동 레인지) 또는 옴 값 (측정 시작 전에 RTIA 명령으로 보낸다)
    elapsed_min: Optional[float] = None     # 배치 시작 후 경과 시간(분). 없으면 모델이 Day-1 중앙값을 가정하고 경고
    reaction_timer_start: str = "auto"      # "auto": 이전 단계가 끝나면 타이머 시작 / "manual": 사용자가 [혈액 투입 완료]를 누르면 시작


def troponin_stages(reaction_wait_s: int = 900, auto_start_last: bool = False):
    return [
        StageDef("T0", "T1", "1 · 시료준비",
                 "시료가 준비되면 검사시작을 누르세요.",
                 label=STAGE_LABELS[0], measure=False),                    # 1단계는 측정 없음: [검사 시작] → 바로 2단계
        StageDef("T1", "T2", "2 · 혈액투입",
                 "센서에 혈액을 투입하고 반응이 끝날 때까지 기다리세요.\n타이머가 끝나면 [검사 시작] 버튼이 활성화됩니다.",
                 wait_before_s=reaction_wait_s, auto_start=True, label=STAGE_LABELS[1],
                 cycles=3),                                                # 2단계에서 3번 측정: 센서 3개 × 10점 × 3 = 90점
    ]
