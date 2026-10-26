"""측정 화면(가로/세로 대시보드)이 같이 쓰는 표시 로직. Qt 위젯을 모르고, ViewState 에서 "무엇을 보일지"만 계산한다.

가로(ui/dashboard_page.py)와 세로(ui/dashboard_portrait.py)는 배치만 다르고 상태·문구·판정은 여기서 하나로 정한다.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from measure.controller import State, ViewState, fmt_mmss
from measure.history import classify, format_value

WEEKDAYS = "월화수목금토일"
STEP_NAMES = ("시료준비", "혈액투입", "세척후 검증")
STEP_PENDING = ("센서에 아무것도 올리지 않은 상태에서 시작합니다.",
                "센서에 혈액을 투입하고 반응이 끝날 때까지 기다립니다.",
                "센서를 세척한 뒤 검증 측정을 합니다.")
STEP_DONE = ("시료 준비가 완료되었습니다.",
             "혈액 반응 측정이 완료되었습니다.",
             "세척 및 검증이 완료되었습니다.\n검사 결과가 표시됩니다.")
MEASURING = (State.CONFIGURING, State.MEASURING, State.STOPPING)


def korean_datetime(now: datetime) -> str:
    ampm = "오전" if now.hour < 12 else "오후"
    h = now.hour % 12 or 12
    return f"{now.year}년 {now.month}월 {now.day}일 ({WEEKDAYS[now.weekday()]})  {ampm} {h:02d}:{now.minute:02d}"


def korean_datetime_2line(now: datetime) -> str:
    """세로 화면 상단용: 날짜와 시각을 두 줄로"""
    ampm = "오전" if now.hour < 12 else "오후"
    h = now.hour % 12 or 12
    return f"{now.year}년 {now.month}월 {now.day}일 ({WEEKDAYS[now.weekday()]})\n{ampm} {h:02d}:{now.minute:02d}"


# ---------------- 단계 ----------------
def badge_text(v: ViewState, i: int, status: str) -> str:
    if status == "done":
        return "검증 완료" if i == 2 else "완료"
    if status == "error":
        return "오류"
    if status == "pending":
        return "대기"
    st = v.state
    if st == State.DISCONNECTED:
        return "연결 안 됨"
    if st == State.NO_MODULE:
        return "모듈 없음"
    if st == State.CHECKING:
        return "모듈 확인"
    if st in MEASURING:
        return "측정 중"
    if st == State.COMPUTING:
        return "계산 중"
    return "반응 중" if v.waiting else "시작 대기"


@dataclass
class StepView:
    status: str                  # pending | active | done | error
    badge: str
    active: bool
    desc: str
    time_text: str = ""
    progress: Optional[float] = None


def step_views(v: ViewState) -> List[StepView]:
    out = []
    for i, chip in enumerate(v.stages):
        status = chip.status
        desc = {"done": STEP_DONE[i], "pending": STEP_PENDING[i]}.get(status, v.instruction or STEP_PENDING[i])
        time_text, progress = "", None
        if status == "active":
            if v.state in MEASURING or v.state == State.COMPUTING:
                progress, time_text = v.progress, v.progress_text
            elif v.state == State.READY and v.waiting and v.wait_total_s:
                progress = v.progress
                time_text = f"{fmt_mmss(v.progress * v.wait_total_s)} / {fmt_mmss(v.wait_total_s)}"
                desc = "혈액이 분석되고 있습니다.\n타이머가 끝나면 측정을 시작할 수 있습니다."
        out.append(StepView(status, badge_text(v, i, status), status in ("active", "error"), desc, time_text,
                            progress))
    return out


def step_button(v: ViewState, i: int) -> tuple:
    """세로 화면의 단계별 시작 버튼 (표시 글자, 활성, 보임). 현재 단계만 컨트롤러의 주 버튼이고, 끝난 단계는 숨긴다."""
    chip_status = v.stages[i].status
    if chip_status == "done" and not (v.state == State.DONE and i == v.stage_index):
        return "", False, False
    if i != v.stage_index:
        return f"{i + 1}단계 시작", False, True
    if v.state == State.READY:
        label = v.primary_label
        return (f"{i + 1}단계 시작" if label == "측정 시작" else label), v.primary_enabled, True
    return v.primary_label, v.primary_enabled, True


# ---------------- 장비 상태 ----------------
@dataclass
class DeviceView:
    state_text: str
    done: int
    total: int
    kit_text: str
    kit_kind: str                # ok | warn | bad
    sensors_done: int
    sensors_total: int
    module_text: str
    device_ok: bool              # 모듈이 응답하고 있다
    link_ok: bool                # UART 포트가 열려 있다


def device_view(v: ViewState) -> DeviceView:
    done = sum(1 for c in v.stages if c.status == "done")
    total = max(1, len(v.stages))
    names = {State.DONE: "검사 완료", State.COMPUTING: "계산 중", State.ERROR: "오류", State.NO_MODULE: "모듈 없음",
             State.DISCONNECTED: "연결 안 됨", State.CHECKING: "모듈 확인 중"}
    if v.state in MEASURING:
        text = "측정 중"
    elif v.state == State.READY:
        text = "반응 중" if v.waiting else ("대기" if done == 0 else "다음 단계 대기")
    else:
        text = names.get(v.state, "")
    sensors_done = sum(1 for s in v.sensors if s.text == "완료")
    sat = sum(s.sat for s in v.sensors)
    if v.state in (State.DISCONNECTED, State.NO_MODULE):
        kit, kind = "확인 불가", "bad"
    elif v.state == State.ERROR:
        kit, kind = "오류", "bad"
    elif sat:
        kit, kind = "신호 포화 주의", "warn"
    else:
        kit, kind = "정상", "ok"
    return DeviceView(text, done, total, kit, kind, sensors_done, len(v.sensors), v.module_text,
                      device_ok=v.state not in (State.DISCONNECTED, State.NO_MODULE),
                      link_ok=v.state != State.DISCONNECTED)


# ---------------- 결과 ----------------
@dataclass
class ResultView:
    done: bool = False
    value_text: str = "—"
    ready: bool = False          # 값이 있다 (색을 진하게)
    note: str = "검사가 끝나면 결과가 표시됩니다."
    status_text: str = ""        # "✓ 정상" / "! 주의" / "" (참고 범위가 있을 때만)
    status_kind: str = ""        # ok | warn
    verified: bool = False       # 헤더의 '검증 완료' 배지
    info_wait: str = "—"
    info_done: str = "—"


def ref_text(cfg) -> str:
    lo, hi, unit = cfg.ref_low, cfg.ref_high, cfg.result_unit
    if lo is None and hi is None:
        return "미설정"
    a = format_value(lo if lo is not None else 0.0)
    b = format_value(hi) if hi is not None else "—"
    return f"{a} – {b}" + (f" {unit}" if unit else "")


def result_view(cfg, v: ViewState, wait_seen: int, finished_at: Optional[datetime]) -> ResultView:
    r = v.result
    if r is None or v.state != State.DONE:
        return ResultView()
    out = ResultView(done=True, value_text=format_value(r.value), ready=r.value is not None,
                     verified=r.value is not None)
    if r.value is None:
        warn = r.warnings[0] if r.warnings else ""
        out.note = "QC 불합격: 결과를 표시하지 않습니다. 마지막 단계를 다시 측정하세요." + (f"\n{warn}" if warn else "")
    else:
        out.note = "QC 통과" + (" · 모델 범위 상한으로 제한됨" if r.clipped else "")
        status = classify(r.value, cfg.ref_low, cfg.ref_high)
        if status in ("정상", "주의"):
            out.status_text = ("✓ " if status == "정상" else "! ") + status
            out.status_kind = "ok" if status == "정상" else "warn"
    out.info_wait = f"{fmt_mmss(wait_seen)} ({wait_seen // 60}분)" if wait_seen else "—"
    out.info_done = finished_at.strftime("%Y. %m. %d  %H:%M") if finished_at else "—"
    return out


class RunTracker:
    """한 번의 검사 동안 '실제로 기다린 반응 시간'과 '끝난 시각'을 기억한다 (결과 카드의 측정 시간/검증 완료 시간)."""

    def __init__(self):
        self.wait_seen = 0
        self.finished_at: Optional[datetime] = None
        self._was_done = False

    def update(self, v: ViewState, has_progress: bool) -> None:
        done = v.state == State.DONE
        if v.wait_total_s:
            self.wait_seen = max(self.wait_seen, v.wait_total_s)
        if done and not self._was_done:
            self.finished_at = datetime.now()
        if not done and v.state in (State.READY, State.DISCONNECTED, State.NO_MODULE) and not has_progress:
            self.wait_seen, self.finished_at = 0, None
        self._was_done = done
