"""측정 단계 컨트롤러 (UI 비의존 로직).

UI 는 `viewChanged(ViewState)` 를 받아 그리기만 하고, 버튼은 아래 메서드만 호출한다:
    primary()  주 버튼(상태에 따라 시작/재시도/새 측정)    stop()  중지    restart()  처음부터

흐름 (Troponin, 화면 단계명 시료준비 → 혈액투입 → 세척후 검증 = 내부 T0 → T1 → T2):
    확인(ENV 응답으로 모듈 확인, STATUS/CALSTATUS 는 정보) → READY → [측정 시작] → 센서 0,1,2 측정(START 1) → 단계 완료
    → (혈액투입 단계는 반응 대기 타이머가 끝나야 버튼 활성) → [측정 시작] → … → [측정 시작] → … → 계산 → 결과
각 단계는 사용자가 수락(버튼)해야 시작된다. 자동 진행은 StageDef.auto_start 로만 켠다.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from app.comm import protocol as p
from app.comm.firmware_client import FirmwareClient

if TYPE_CHECKING:       # numpy 가 들어 있는 모델은 처음 쓸 때 불러온다 (앱 시작을 늦추지 않도록)
    from app.models.troponin import TroponinModel, TroponinResult

from .stages import MeasureSettings, StageDef
from .store import SessionStore

log = logging.getLogger(__name__)


class State:
    DISCONNECTED = "disconnected"   # 포트 연결 안 됨
    CHECKING = "checking"           # 모듈 확인 중
    NO_MODULE = "no_module"         # 연결은 됐지만 모듈이 ENV 에 응답하지 않음
    READY = "ready"                 # 단계 시작 대기 (반응 대기 타이머가 돌 수 있음)
    CONFIGURING = "configuring"     # SWEEP/CHAN/VERB/START 전송 중
    MEASURING = "measuring"
    STOPPING = "stopping"
    COMPUTING = "computing"
    DONE = "done"
    ERROR = "error"


@dataclass
class SensorView:
    ch: int
    text: str            # 대기 / 측정 중 / 완료 / 부족 …
    done: int
    total: int
    sat: int = 0


@dataclass
class StageChip:
    key: str
    title: str
    status: str          # pending | active | done | error
    label: str = ""      # 공통 단계 이름 (시료준비 / 혈액투입 / 세척후 검증)


@dataclass
class ViewState:
    state: str
    stage_index: int
    stage_title: str
    instruction: str
    primary_label: str
    primary_enabled: bool
    stop_enabled: bool
    reset_enabled: bool
    timer_label: str
    timer_text: str
    progress: float                  # 0..1
    progress_text: str
    sensors: List[SensorView]
    stages: List[StageChip]
    banner: str = ""
    banner_level: str = "info"       # info | warn | error
    module_text: str = ""
    result: Optional[TroponinResult] = None
    waiting: bool = False            # 반응 대기 타이머가 진행 중
    wait_total_s: int = 0


def fmt_mmss(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60:02d}:{s % 60:02d}"


class MeasureController(QObject):
    viewChanged = pyqtSignal(object)    # ViewState
    stageCompleted = pyqtSignal(int)    # 완료한 단계 인덱스
    finished = pyqtSignal(object)       # TroponinResult

    def __init__(self, client: FirmwareClient, settings: MeasureSettings, stages: List[StageDef],
                 model: Optional[TroponinModel] = None, store: Optional[SessionStore] = None,
                 clock: Callable[[], float] = time.monotonic, tick_ms: int = 200,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self.client = client
        self.settings = settings
        self.stages = stages
        self._model = model
        self.store = store
        self._clock = clock
        self.patient: dict = {}             # 환자 프로필 (화면이 채운다). 결과 파일에 함께 저장
        self.assay = "troponin"             # 계산 모델: troponin | ntprobnp (config.ini [measure] assay)
        self.meta: dict = {}                # 결과 표시 정보 (title, unit, ref_low, ref_high). 이력 판정에 쓴다

        self._state = State.DISCONNECTED
        self._idx = 0
        self._cur: Dict[int, List[p.MeasRecord]] = {}
        self._done: Dict[int, Dict[int, List[p.MeasRecord]]] = {}
        self._last_counts: Dict[int, int] = {}
        self._last_sat: Dict[int, int] = {}
        self._stage_t0: Optional[float] = None
        self._wait_t0: Optional[float] = None
        self._wait_s = 0
        self._wait_unstarted = False        # reaction_timer_start == "manual" 에서 [혈액 투입 완료] 대기
        self._cycle_done = False
        self._stage_error: Optional[str] = None
        self._error_kind = ""               # "link": 통신 문제 → 재시도는 모듈 확인부터 / "stage": 같은 단계 재측정 / "compute": 마지막 단계 재측정
        self._banner = ("", "info")
        self._result: Optional[TroponinResult] = None
        self._chain: Optional[dict] = None
        self._module = {"fw": "", "cal": "", "board": ""}
        self._dirty = False
        self._session_open = False

        c = client
        c.connectionChanged.connect(self._on_connection)
        c.commandFinished.connect(self._on_cmd_finished)
        c.recordReceived.connect(self._on_record)
        c.rawLine.connect(self._on_raw)
        c.measurementStarted.connect(self._on_started)
        c.cycleDone.connect(self._on_cycle_done)
        c.measurementStopped.connect(self._on_stopped)
        c.measurementFailed.connect(self._on_failed)
        c.firmwareError.connect(self._on_fw_error)
        c.watchdogExpired.connect(self._on_watchdog)
        c.moduleRestarted.connect(self._on_module_restarted)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self._timer.start(tick_ms)
        if client.connected:
            QTimer.singleShot(0, self.begin)

    # ================= UI 가 호출하는 동작 =================
    def primary(self) -> None:
        st = self._state
        if st in (State.DISCONNECTED, State.NO_MODULE):
            self.begin()
        elif st == State.READY:
            if self._wait_unstarted:
                self._start_wait_timer()
            elif self._wait_remaining() <= 0:
                self.start_stage()
        elif st == State.ERROR:
            self.retry()
        elif st == State.DONE:
            self.restart()

    def stop(self) -> None:
        if self._state in (State.CONFIGURING, State.MEASURING):
            self._chain = None
            self._set_state(State.STOPPING)
            self._set_banner("측정을 중지하는 중입니다…", "info")
            self.client.stop()

    def restart(self) -> None:
        """처음부터 다시 (측정 중에는 무시)."""
        if self._state in (State.CONFIGURING, State.MEASURING, State.STOPPING, State.COMPUTING):
            return
        self._reset_session()
        self.begin()

    def retry(self) -> None:
        if self._state != State.ERROR:
            return
        if self._error_kind == "link":
            self.begin()
        else:                                   # 계산 실패 포함: 직전 단계를 다시 측정
            self._done.pop(self._idx, None)
            self._set_banner("", "info")
            self._set_state(State.READY)
            self.start_stage()

    # ================= 모듈 확인 =================
    def begin(self) -> None:
        if not self.client.connected:
            self._set_banner("UART 포트에 연결되지 않았습니다.", "warn")
            self._set_state(State.DISCONNECTED)
            return
        self._set_state(State.CHECKING)
        self._set_banner("모듈을 확인하는 중입니다…", "info")
        # 모듈이 살아 있는지는 ENV 응답으로 확인한다 ("ENV not available" 도 응답이므로 살아 있는 것). 나머지는 정보용.
        self._run_chain([p.CMD_ENV, p.CMD_STATUS, p.CMD_CALSTATUS], self._check_done, self._check_failed,
                        tolerant=(p.CMD_STATUS, p.CMD_CALSTATUS))

    def _check_done(self) -> None:
        cal = self.client.cal_status
        self._module["fw"] = self._module["fw"] or ""
        self._module["cal"] = "보정 있음" if cal.get("VALID") == "1" else "보정 없음"
        self._module["board"] = cal.get("BOARD_ID", "")
        if cal.get("VALID") != "1":
            self._set_banner("이 모듈에는 SHORT 보정이 저장되어 있지 않습니다. 측정값에 보드 오프셋이 포함됩니다.", "warn")
        else:
            self._set_banner("", "info")
        self._enter_ready()

    def _check_failed(self, msg: str) -> None:
        self._error_kind = "link"
        self._set_banner(f"모듈이 응답하지 않습니다 ({msg}). 배선과 전원을 확인하세요.", "error")
        self._set_state(State.NO_MODULE)

    def _enter_ready(self) -> None:
        self._set_state(State.READY)
        self._arm_wait_for_current_stage()

    # ================= 단계 실행 =================
    def start_stage(self) -> None:
        if self._state != State.READY:
            return
        if not self._session_open and self.store is not None:
            self.store.open()
            self.store.note(f"session start settings={self.settings}")
            self._session_open = True
        stage = self.stages[self._idx]
        s = self.settings
        self._cur = {}
        self._cycle_done = False
        self._stage_error = None
        self._error_kind = ""
        self._stage_t0 = self._clock()
        self._set_banner("", "info")
        self._set_state(State.CONFIGURING)
        if self.store:
            self.store.note(f"stage {stage.key} configure")
        self._run_chain(
            [p.cmd_sweep(s.start_hz, s.stop_hz, s.points), p.cmd_chan(s.channels), p.cmd_verb("FULL"),
             p.cmd_start(1)],
            on_ok=lambda: None, on_fail=self._config_failed)

    def _config_failed(self, msg: str) -> None:
        self._fail_stage(f"측정 시작 실패: {msg}", "link")

    def _on_started(self) -> None:
        if self._state == State.CONFIGURING:
            self._set_state(State.MEASURING)

    def _on_record(self, rec) -> None:
        if isinstance(rec, p.HeaderRecord):
            self._module["fw"] = rec.fw
            return
        if isinstance(rec, p.MeasRecord) and self._state in (State.CONFIGURING, State.MEASURING):
            self._cur.setdefault(rec.ch, []).append(rec)
            self._dirty = True

    def _on_raw(self, line: str) -> None:
        if self.store is not None and self._session_open:
            self.store.log_line(line)

    def _on_cycle_done(self, _n: int) -> None:
        self._cycle_done = True

    def _on_fw_error(self, msg: str) -> None:
        if self._state in (State.CONFIGURING, State.MEASURING):
            self._stage_error = f"펌웨어 오류: {msg}"       # client 가 자동 STOP 을 보냈으므로 stopped 가 이어서 온다

    def _on_watchdog(self) -> None:
        if self._state in (State.CONFIGURING, State.MEASURING):
            self._stage_error = "모듈에서 오래 응답이 없어 측정을 중단했습니다."

    def _on_failed(self, reason: str) -> None:
        if self._state in (State.CONFIGURING, State.MEASURING, State.STOPPING):
            self._fail_stage(f"측정이 중단되었습니다: {reason}", "link")

    def _on_module_restarted(self) -> None:
        if self._state in (State.CHECKING, State.READY, State.NO_MODULE):
            self.begin()

    def _on_stopped(self) -> None:
        st = self._state
        if st == State.STOPPING:
            self._cur = {}
            self._set_banner("측정을 중지했습니다. 이 단계를 처음부터 다시 시작할 수 있습니다.", "warn")
            self._set_state(State.READY)
        elif st in (State.CONFIGURING, State.MEASURING):
            if self._stage_error:
                self._fail_stage(self._stage_error, "stage")    # 펌웨어 오류/무응답: 같은 단계를 바로 재측정
            elif self._cycle_done:
                self._finish_stage()
            else:
                self._fail_stage("측정이 예상보다 일찍 끝났습니다.", "stage")

    def _finish_stage(self) -> None:
        s = self.settings
        problems = []
        for ch in s.channels:
            n = len(self._cur.get(ch, []))
            if n != s.points:
                problems.append(f"센서 {ch}: {n}/{s.points}점")
        if problems:
            self._fail_stage("점 수가 부족합니다 — " + ", ".join(problems), "stage")
            return
        stage = self.stages[self._idx]
        self._done[self._idx] = self._cur
        self._last_counts = {ch: len(v) for ch, v in self._cur.items()}
        self._last_sat = {ch: sum(1 for r in v if r.sat) for ch, v in self._cur.items()}
        elapsed = self._clock() - (self._stage_t0 or self._clock())
        if self.store:
            self.store.note(f"stage {stage.key} done in {elapsed:.1f}s counts={self._last_counts} sat={self._last_sat}")
        sat_total = sum(self._last_sat.values())
        warn = f"{stage.label or stage.key}: SAT(신호 포화) {sat_total}점 — 결과를 신중히 보세요." if sat_total else ""
        self.stageCompleted.emit(self._idx)
        if self._idx + 1 >= len(self.stages):
            self._set_banner(warn, "warn" if warn else "info")
            self._compute()
            return
        self._idx += 1
        self._set_banner(warn, "warn" if warn else "info")
        self._set_state(State.READY)
        self._arm_wait_for_current_stage()
        nxt = self.stages[self._idx]
        if nxt.auto_start and nxt.wait_before_s == 0:
            self.start_stage()

    def _fail_stage(self, msg: str, kind: str) -> None:
        self._cur = {}
        self._error_kind = kind
        self._chain = None
        if self.store:
            self.store.note(f"ERROR {msg}")
        self._set_banner(msg, "error")
        self._set_state(State.ERROR)

    # ================= 계산 =================
    @property
    def model(self) -> "TroponinModel":
        if self._model is None:
            if self.assay == "ntprobnp":
                from app.models.ntprobnp import NtProBnpModel
                self._model = NtProBnpModel()
            else:
                from app.models.troponin import TroponinModel
                self._model = TroponinModel()
        return self._model

    @model.setter
    def model(self, value: "TroponinModel") -> None:
        self._model = value

    def _curves(self, stage_index: int):
        from app.models.troponin import make_curve
        out = []
        for ch in self.settings.channels:
            recs = self._done[stage_index][ch]
            out.append(make_curve([r.freq_hz for r in recs], [r.mag_ohm for r in recs],
                                  [r.phase_deg for r in recs]))
        return out

    def _compute(self) -> None:
        self._set_state(State.COMPUTING)
        try:
            names = {"t2": [f"센서{c}" for c in self.settings.channels]}
            # c0 = 첫 측정(시료준비, 센서 0·1·2)의 결과 (모델 담당자 피드백). "none" 이면 과거 Day-1 기준값 + 경고.
            c0 = self._curves(0) if self.settings.c0_source == "first" else None
            if c0:
                names["t2_c0"] = [f"센서{c} (첫 측정)" for c in self.settings.channels]
            res = self.model.predict(self._curves(0), self._curves(1), self._curves(2), c0,
                                     elapsed_min=self.settings.elapsed_min,
                                     rtia_ohm=self.settings.rtia_ohm, names=names)
        except ValueError as e:                       # TroponinInputError / NtProBnpInputError
            self._error_kind = "compute"
            self._set_banner(f"계산할 수 없습니다: {e} 마지막 단계를 다시 측정하세요.", "error")
            if self.store:
                self.store.note(f"compute failed: {e}")
            self._set_state(State.ERROR)
            return
        self._result = res
        if self.store:
            self.store.write_json("result.json", self._result_json(res))
            self.store.write_json("summary.json", self._summary_json(res))
            self.store.note("session done")
        self._set_banner("", "info")
        self._set_state(State.DONE)
        self.finished.emit(res)

    def _summary_json(self, res: TroponinResult) -> dict:
        """이력 화면이 읽는 작은 요약 (곡선 없이)."""
        m = self.meta
        return {"schema": 1, "finished_at": datetime.now().isoformat(timespec="seconds"),
                "title": m.get("title", "Troponin"), "value": res.value, "qc_pass": res.qc_pass,
                "unit": m.get("unit", ""), "ref_low": m.get("ref_low"), "ref_high": m.get("ref_high"),
                "patient": dict(self.patient)}

    def _result_json(self, res: TroponinResult) -> dict:
        return {
            "schema": 1,
            "patient": dict(self.patient),
            "model": {"name": res.model_name, "version": res.model_version, "research_use_only": True},
            "firmware": dict(self._module),
            "settings": {"start_hz": self.settings.start_hz, "stop_hz": self.settings.stop_hz,
                         "points": self.settings.points, "channels": list(self.settings.channels),
                         "rtia_ohm": self.settings.rtia_ohm, "elapsed_min": self.settings.elapsed_min,
                         "c0_source": self.settings.c0_source},
            "stages": {self.stages[i].key: {"code_name": self.stages[i].code_name,
                                            "counts": {ch: len(v) for ch, v in d.items()}}
                       for i, d in self._done.items()},
            "result": {"value": res.value, "unit": None, "qc_pass": res.qc_pass, "D": getattr(res, "d", None), "B": getattr(res, "b", None),
                       "score": getattr(res, "score", None), "clipped": getattr(res, "clipped", False),
                       "loocv_mae": getattr(res, "day1_loocv_mae", None),
                       "warnings": res.warnings, "details": res.details},
            "curves": {self.stages[i].key: {str(ch): [[r.freq_hz, r.mag_ohm, r.phase_deg, r.r_ohm, r.x_ohm,
                                                       r.status] for r in recs] for ch, recs in d.items()}
                       for i, d in self._done.items()},
        }

    # ================= 명령 체인 =================
    def _run_chain(self, cmds, on_ok, on_fail, tolerant=()) -> None:
        self._chain = {"cmds": list(cmds), "i": 0, "ok": on_ok, "fail": on_fail, "tolerant": set(tolerant)}
        self.client.send_command(cmds[0])

    def _on_cmd_finished(self, text: str, ok: bool, msg: str) -> None:
        if text == p.CMD_STOP:
            if self._state == State.STOPPING and ok and msg == "실행 중이 아님":
                self._cur = {}
                self._set_banner("측정을 중지했습니다.", "warn")
                self._set_state(State.READY)
            return
        ch = self._chain
        if ch is None or ch["i"] >= len(ch["cmds"]) or text != ch["cmds"][ch["i"]]:
            return
        alive = ok or (text == p.CMD_ENV and msg.startswith("ENV not available"))     # 센서가 없다는 답도 모듈의 응답
        if not alive and text not in ch["tolerant"]:
            self._chain = None
            ch["fail"](f"{text.split()[0]}: {msg}")
            return
        ch["i"] += 1
        if ch["i"] < len(ch["cmds"]):
            self.client.send_command(ch["cmds"][ch["i"]])
        else:
            self._chain = None
            ch["ok"]()

    def _on_connection(self, ok: bool) -> None:
        if ok:
            if self._state in (State.DISCONNECTED, State.NO_MODULE):
                self.begin()
        elif self._state in (State.CHECKING, State.READY, State.NO_MODULE):
            self._chain = None
            self._set_banner("UART 연결이 끊겼습니다.", "warn")
            self._set_state(State.DISCONNECTED)

    # ================= 반응 대기 타이머 =================
    def _arm_wait_for_current_stage(self) -> None:
        stage = self.stages[self._idx]
        self._wait_t0, self._wait_s, self._wait_unstarted = None, 0, False
        if stage.wait_before_s > 0:
            self._wait_s = stage.wait_before_s
            if self.settings.reaction_timer_start == "manual":
                self._wait_unstarted = True
            else:
                self._wait_t0 = self._clock()
        self._emit()

    def _start_wait_timer(self) -> None:
        self._wait_t0 = self._clock()
        self._wait_unstarted = False
        self._emit()

    def _wait_remaining(self) -> float:
        if self._wait_s <= 0:
            return 0.0
        if self._wait_t0 is None:
            return float(self._wait_s)
        return max(0.0, self._wait_s - (self._clock() - self._wait_t0))

    # ================= 상태/뷰 =================
    def _reset_session(self) -> None:
        if self.store:
            self.store.close()
            self.store.dir = None
        self._session_open = False
        self._idx = 0
        self._cur, self._done = {}, {}
        self._last_counts, self._last_sat = {}, {}
        self._result = None
        self._wait_t0, self._wait_s, self._wait_unstarted = None, 0, False
        self._error_kind = ""
        self._set_banner("", "info")

    def _set_state(self, st: str) -> None:
        self._state = st
        self._emit()

    def _set_banner(self, text: str, level: str) -> None:
        self._banner = (text, level)

    def tick(self) -> None:
        """주기 갱신 (타이머/진행률). 테스트에서는 직접 호출."""
        active = self._state in (State.CONFIGURING, State.MEASURING, State.STOPPING) or \
            (self._state == State.READY and self._wait_t0 is not None)
        if self._dirty or active:
            self._dirty = False
            self._emit()
        if self._state == State.READY and self._wait_t0 is not None and self._wait_remaining() <= 0:
            nxt = self.stages[self._idx]
            if nxt.auto_start:
                self.start_stage()

    def _emit(self) -> None:
        self.viewChanged.emit(self.snapshot())

    @property
    def state(self) -> str:
        return self._state

    @property
    def result(self) -> Optional[TroponinResult]:
        return self._result

    def snapshot(self) -> ViewState:
        st = self._state
        s = self.settings
        stage = self.stages[min(self._idx, len(self.stages) - 1)]
        total = s.points * len(s.channels)
        got = sum(len(v) for v in self._cur.values())
        measuring = st in (State.CONFIGURING, State.MEASURING, State.STOPPING)
        remaining = self._wait_remaining()
        waiting = st == State.READY and self._wait_s > 0 and (self._wait_unstarted or remaining > 0)

        # 주 버튼
        label, enabled = "", False
        if st in (State.DISCONNECTED, State.NO_MODULE):
            label, enabled = "모듈 다시 확인", True
        elif st == State.CHECKING:
            label = "모듈 확인 중…"
        elif st == State.READY:
            if self._wait_unstarted:
                label, enabled = "혈액 투입 완료 (타이머 시작)", True
            else:
                label, enabled = "측정 시작", remaining <= 0
        elif measuring:
            label = "측정 중…"
        elif st == State.COMPUTING:
            label = "계산 중…"
        elif st == State.ERROR:
            label, enabled = "다시 시도", True
        elif st == State.DONE:
            label, enabled = "새 측정", True

        # 타이머
        if measuring:
            t_label = "경과 시간"
            t_text = fmt_mmss(self._clock() - (self._stage_t0 or self._clock()))
        elif st == State.READY and self._wait_s > 0:
            t_label = "반응 대기 — 남은 시간" if remaining > 0 or self._wait_unstarted else "반응 대기 완료"
            t_text = fmt_mmss(remaining)
        else:
            t_label, t_text = "", ""

        # 진행률
        if measuring:
            progress, ptxt = (got / total if total else 0.0), f"{got} / {total} 점"
        elif st == State.READY and self._wait_s > 0:
            progress = 1.0 - remaining / self._wait_s
            ptxt = "반응 대기"
        elif st in (State.COMPUTING, State.DONE):
            progress, ptxt = 1.0, ""
        else:
            progress, ptxt = 0.0, ""

        # 센서
        sensors = []
        for ch in s.channels:
            if measuring:
                n = len(self._cur.get(ch, []))
                sat = sum(1 for r in self._cur.get(ch, []) if r.sat)
                text = "대기" if n == 0 else ("완료" if n >= s.points else "측정 중")
            else:
                n = self._last_counts.get(ch, 0)
                sat = self._last_sat.get(ch, 0)
                text = "완료" if n else "대기"
                if st == State.ERROR:
                    text = "—"
            sensors.append(SensorView(ch, text, n, s.points, sat))

        # 단계 칩
        chips = []
        for i, sd in enumerate(self.stages):
            if i in self._done:
                status = "done"
            elif i == self._idx:
                status = "error" if st == State.ERROR else "active"
            else:
                status = "pending"
            chips.append(StageChip(sd.key, sd.title, status, sd.label))

        # 안내
        if st == State.READY:
            instr = stage.prompt
        elif measuring:
            instr = "센서 0 → 1 → 2 순서로 측정 중입니다. 키트를 움직이지 마세요."
        elif st == State.CHECKING:
            instr = "모듈과 통신을 확인하고 있습니다."
        elif st == State.DONE:
            instr = "모든 단계가 끝났습니다."
        else:
            instr = ""
        module = " · ".join(x for x in (f"FW {self._module['fw']}" if self._module["fw"] else "",
                                        self._module["cal"],
                                        f"보드 {self._module['board']}" if self._module["board"] not in ("", "UNSET") else "")
                            if x)
        text, level = self._banner
        return ViewState(
            state=st, stage_index=self._idx, stage_title=stage.title, instruction=instr,
            primary_label=label, primary_enabled=enabled,
            stop_enabled=st in (State.CONFIGURING, State.MEASURING),
            reset_enabled=st in (State.READY, State.ERROR, State.DONE, State.NO_MODULE) and
            (bool(self._done) or st in (State.ERROR, State.DONE)),
            timer_label=t_label, timer_text=t_text, progress=max(0.0, min(1.0, progress)),
            progress_text=ptxt, sensors=sensors, stages=chips, banner=text, banner_level=level,
            module_text=module, result=self._result, waiting=waiting, wait_total_s=self._wait_s)
