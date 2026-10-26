"""지난 검사 이력 (results/ 폴더의 summary.json 을 읽는다). Qt 의존 없음.

각 검사 폴더(예: 20261025_093000_troponin)에는 검사가 끝날 때 summary.json 이 저장된다. 끝나지 않은 검사(summary.json 이 없는 폴더)는 이력에 넣지 않는다.
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HistoryItem:
    when: datetime
    title: str
    value: Optional[float]       # QC 불합격이면 None
    status: str                  # 정상 | 주의 | 판정불가 | "" (기준이 없으면 빈 문자열)
    unit: str = ""


def classify(value: Optional[float], ref_low: Optional[float], ref_high: Optional[float]) -> str:
    """참고 범위가 설정되어 있을 때만 정상/주의를 판정한다. 값이 없으면(QC 불합격) 판정불가, 범위가 없으면 빈 문자열."""
    if value is None:
        return "판정불가"
    if ref_high is None and ref_low is None:
        return ""
    if (ref_high is not None and value > ref_high) or (ref_low is not None and value < ref_low):
        return "주의"
    return "정상"


def format_value(value: Optional[float]) -> str:
    """값 크기에 맞춰 자릿수를 정한다 (0.042 → 0.042, 3.456 → 3.46, 123.4 → 123.4)."""
    if value is None:
        return "—"
    a = abs(value)
    return f"{value:.3f}" if a < 1 else (f"{value:.2f}" if a < 10 else f"{value:.1f}")


def load_history(results_dir, limit: int = 20) -> List[HistoryItem]:
    base = Path(results_dir)
    out: List[HistoryItem] = []
    try:
        dirs = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)
    except OSError:
        return out
    for d in dirs:
        f = d / "summary.json"
        if not f.is_file():
            continue
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
            when = datetime.fromisoformat(s["finished_at"])
            value = s.get("value")
            out.append(HistoryItem(when, s.get("title", "Troponin"), value,
                                   classify(value, s.get("ref_low"), s.get("ref_high")), s.get("unit", "") or ""))
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("cannot read the history file (%s): %s", f, e)
        if len(out) >= limit:
            break
    return out
