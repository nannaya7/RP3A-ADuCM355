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
    patient: str = ""            # 검사받은 사람 이름 (검색용). 없으면 빈 문자열


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
                                   classify(value, s.get("ref_low"), s.get("ref_high")), s.get("unit", "") or "",
                                   str((s.get("patient") or {}).get("name", "") or "").strip()))
        except (OSError, ValueError, KeyError, TypeError) as e:
            log.warning("cannot read the history file (%s): %s", f, e)
        if len(out) >= limit:
            break
    return out


# ---- 찾기: 검색 / 필터 / 정렬 (화면 없이 시험할 수 있게 여기에 둔다) ----
SORTS = ("최신순", "오래된순", "결과 높은순", "결과 낮은순")
STATUSES = ("전체", "정상", "주의", "판정불가")


def _haystack(it: HistoryItem) -> str:
    """검색 대상 문자열: 이름, 검사 항목, 상태, 결과값, 날짜(여러 표기)."""
    w = it.when
    return " ".join([it.patient, it.title, it.status, format_value(it.value), it.unit,
                     w.strftime("%Y-%m-%d %H:%M"), w.strftime("%Y. %m. %d"), f"{w.year}년 {w.month}월 {w.day}일",
                     f"{w.month}월 {w.day}일", f"{w.month}/{w.day}"]).lower()


def find_history(items: List[HistoryItem], query: str = "", title: str = "", status: str = "",
                 sort: str = "최신순") -> List[HistoryItem]:
    """query: 공백으로 나눈 낱말이 모두 들어 있는 기록 / title: 검사 항목(빈 문자열 = 전체) / status: 정상·주의·판정불가(빈 = 전체).
    정렬: 결과순은 값이 없는(QC 불합격) 기록을 맨 뒤로 보낸다."""
    words = query.lower().split()
    out = [it for it in items
           if (not title or it.title.lower() == title.lower())
           and (not status or it.status == status)
           and all(w in _haystack(it) for w in words)]
    if sort == "오래된순":
        return sorted(out, key=lambda it: it.when)
    if sort in ("결과 높은순", "결과 낮은순"):
        has = [it for it in out if it.value is not None]
        none = sorted((it for it in out if it.value is None), key=lambda it: it.when, reverse=True)
        return sorted(has, key=lambda it: it.value, reverse=(sort == "결과 높은순")) + none
    return sorted(out, key=lambda it: it.when, reverse=True)
