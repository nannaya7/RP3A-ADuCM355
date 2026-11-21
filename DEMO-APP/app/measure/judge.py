"""데모 판정: 채널별 평균 임피던스(|Z|)로 결과를 정한다. Qt 의존 없음.

채널별 평균 |Z| 가 2 kΩ 를 경계로 이하이면 0 Ω(쇼트), 초과(이상)이면 9.1 kΩ 으로 본다.
센서 3개(CH0~CH2 = 화면의 1~3번 채널) 중 하나만 9.1 kΩ 이고 나머지 둘이 0 Ω 이면:
    1번 채널(나머지 둘이 0 Ω) → Troponin 50 pg/mL  + NT-proBNP 400 pg/mL  의 ±4 % 안에서 무작위 값
    2번 채널(나머지 둘이 0 Ω) → Troponin 300 pg/mL + NT-proBNP 50 pg/mL   의 ±4 % 안에서 무작위 값
    3번 채널(나머지 둘이 0 Ω) → 항상 정량실패 (두 항목 모두, 값 없음)
그 밖의 조합은 판정하지 않는다 (matched_ch = None).
"""
import random
from dataclasses import dataclass
from typing import Dict, Optional

ZERO_MAX_OHM = 2000.0             # 경계: 이 값(2 kΩ) 이하는 0 Ω(쇼트), 넘으면 9.1 kΩ
RESULT_TOLERANCE = 0.04           # 1·2번 채널 결과: 지정값의 ±4 % (총 8 %) 안에서 무작위
UNIT = "pg/mL"
# 9.1 kΩ 이 걸린 채널 번호(0부터) → (Troponin, NT-proBNP). None = 정량실패
CASES = {0: (50.0, 400.0), 1: (300.0, 50.0), 2: (None, None)}


@dataclass(frozen=True)
class Verdict:
    matched_ch: Optional[int]     # 9.1 kΩ 이 확인된 채널 (조건에 맞지 않으면 None)
    troponin: Optional[float]     # None: 정량실패 또는 판정 안 함
    ntprobnp: Optional[float]
    failed: bool                  # 정량실패
    summary: str                  # 측정값 요약 (화면 안내문)

    @property
    def decided(self) -> bool:
        return self.matched_ch is not None


def is_ref(ohm: float) -> bool:
    return ohm > ZERO_MAX_OHM            # 경계(2 kΩ) 를 넘으면 9.1 kΩ


def is_zero(ohm: float) -> bool:
    return ohm <= ZERO_MAX_OHM


def _fmt(ohm: float) -> str:
    return f"{ohm / 1000:.2f} kΩ" if ohm >= 1000 else f"{ohm:.0f} Ω"


def _spread(value: float, rng: random.Random) -> float:
    """지정값 ±RESULT_TOLERANCE 안의 무작위 값 (정수 pg/mL 로 반올림)."""
    return float(round(value * (1.0 + rng.uniform(-RESULT_TOLERANCE, RESULT_TOLERANCE))))


def judge(mean_ohm: Dict[int, float], rng: Optional[random.Random] = None) -> Verdict:
    """mean_ohm: 채널 번호(0..2) → 평균 |Z| (Ω)."""
    rng = rng or random
    summary = " / ".join(f"{ch + 1}번 {_fmt(mean_ohm[ch])}" for ch in sorted(mean_ohm))
    chans = sorted(mean_ohm)
    for ch in chans:                                      # 9.1 kΩ 이 한 채널에만 있고 나머지가 모두 0 Ω 일 때만
        others = [c for c in chans if c != ch]
        if ch in CASES and is_ref(mean_ohm[ch]) and others and all(is_zero(mean_ohm[c]) for c in others):
            if ch == 2:                                   # 3번 채널: 항상 정량실패
                return Verdict(ch, None, None, True, summary)
            t, n = CASES[ch]
            return Verdict(ch, _spread(t, rng), _spread(n, rng), False, summary)
    return Verdict(None, None, None, False, summary)
