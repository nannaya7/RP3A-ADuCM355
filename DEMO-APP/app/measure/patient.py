"""환자 프로필 (측정 화면 왼쪽 위). Qt 의존 없음.

필수: 성명, 성별, 나이, 몸무게. 옵션: 혈압(수축/이완), 혈당, 만성질환.
결과 파일(result.json / summary.json)에 함께 저장된다. 이름 등 개인정보가 들어가므로 results/ 폴더를 외부에 공유할 때 주의.
"""
from dataclasses import asdict, dataclass, field
from typing import List, Optional

SEXES = ("남성", "여성")
# 만성질환 선택지 (임시 목록 — 임상 담당자와 확정 필요)
CHRONIC_DISEASES = ("고혈압", "당뇨병", "이상지질혈증", "심부전", "만성신장질환", "관상동맥질환")

REQUIRED = (("name", "성명"), ("sex", "성별"), ("age", "나이"), ("weight", "몸무게"))


def _num(text: str) -> Optional[float]:
    try:
        return float(str(text).strip())
    except ValueError:
        return None


@dataclass
class PatientProfile:
    name: str = ""
    sex: str = ""                       # "" | 남성 | 여성
    age: Optional[int] = None           # 세
    weight: Optional[float] = None      # kg
    bp_sys: Optional[int] = None        # mmHg
    bp_dia: Optional[int] = None
    glucose: Optional[float] = None     # mg/dL
    chronic: List[str] = field(default_factory=list)

    @classmethod
    def from_texts(cls, name="", sex="", age="", weight="", bp_sys="", bp_dia="", glucose="", chronic=()):
        """입력란의 글자에서 만든다. 숫자가 아니거나 범위를 벗어나면 비어 있는 것으로 본다."""
        def ranged(text, lo, hi, as_int=False):
            v = _num(text)
            if v is None or not (lo <= v <= hi):
                return None
            return int(v) if as_int else v
        return cls(name=name.strip(), sex=sex if sex in SEXES else "", age=ranged(age, 0, 120, True),
                   weight=ranged(weight, 1, 400), bp_sys=ranged(bp_sys, 30, 300, True),
                   bp_dia=ranged(bp_dia, 20, 200, True), glucose=ranged(glucose, 10, 1500),
                   chronic=[c for c in chronic])

    def missing(self) -> List[str]:
        """비어 있는 필수 항목의 key 목록"""
        out = []
        if not self.name:
            out.append("name")
        if not self.sex:
            out.append("sex")
        if self.age is None:
            out.append("age")
        if self.weight is None:
            out.append("weight")
        return out

    def is_complete(self) -> bool:
        return not self.missing()

    def to_dict(self) -> dict:
        return asdict(self)


def missing_labels(keys) -> str:
    names = dict(REQUIRED)
    return ", ".join(names[k] for k in keys)
