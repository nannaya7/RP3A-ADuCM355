"""Cortisol 자리표시 모델 (검토 중). 화면만 먼저 만든 단계라 계산하지 않는다.

측정 흐름(3단계, 센서 0·1·2)은 Troponin 과 같게 돌릴 수 있고, 끝나면 결과 없이 "모델 미연결" 안내만 남긴다.
실제 모델이 정해지면 이 파일을 대체한다 (MeasureController.model 이 assay = cortisol 일 때 불러온다).
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class CortisolResult:
    value: None = None
    qc_pass: bool = False
    model_name: str = "Cortisol (모델 미연결)"
    model_version: str = ""
    pending: bool = True                       # 화면이 "모델 미연결" 문구를 쓰게 하는 표시
    warnings: List[str] = field(default_factory=lambda: ["Cortisol 계산 모델이 아직 연결되지 않았습니다."])
    details: dict = field(default_factory=dict)


class CortisolModel:
    def predict(self, t1, t2, t3, t2_c0=None, elapsed_min=None, rtia_ohm=None, names=None) -> CortisolResult:
        return CortisolResult()
