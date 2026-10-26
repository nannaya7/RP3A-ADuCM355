"""세로(480x800) 측정 화면 — 프로필 선택 / 검사 결과 / 검사 진행(3단계 가로 줄) / 장비 상태 / 검사 이력 보기.

가로 화면(ui/dashboard_page.py)과 같은 컨트롤러·표시 로직(ui/dashboard_logic.py)을 쓰고 배치만 다르다.
환자 정보는 직접 입력하는 대신 저장된 프로필(가족 구성원)을 골라 쓴다 (measure/profiles.py).
공개 이름은 가로 화면과 같게 맞췄다: backRequested, monitorRequested, bind(), render(), primary_btn(현재 단계의 시작 버튼),
stop_btn / reset_btn / monitor_btn, clock, banner, tab_tro / tab_nt.
"""
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QScrollArea,
                             QScroller, QSizePolicy, QVBoxLayout, QWidget)

from app.measure.controller import MeasureController, State, ViewState
from app.measure.patient import PatientProfile
from app.measure.profiles import ProfileStore

from .dashboard_logic import (RunTracker, STEP_NAMES, DeviceView, ResultView, device_view, korean_datetime_2line,
                              ref_text, result_view, step_button, step_views)
from .dashboard_page import _set_prop, card
from .dashboard_widgets import DeviceStatusPanel, MiniIcon, ProfileCard, SectionIcon, StatusIcon, StepIllustration


class PortStepRow(QFrame):
    """검사 진행의 한 단계 줄: 번호 · 삽화 · 이름/상태/설명(또는 타이머) · 시작 버튼"""

    def __init__(self, index: int, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("stepCard")
        self.index = index
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)
        self.num = QLabel(str(index + 1), objectName="stepNum")
        self.num.setFixedSize(26, 26)
        self.num.setAlignment(Qt.AlignCenter)
        self.art = StepIllustration(index, 54)
        row.addWidget(self.num, 0, Qt.AlignTop)
        row.addWidget(self.art)

        col = QVBoxLayout()
        col.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.name = QLabel(f"{index + 1}단계. {name}", objectName="stepName")
        self.badge = QLabel("대기", objectName="stepBadge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedHeight(20)
        head.addWidget(self.name)
        head.addWidget(self.badge)
        head.addStretch(1)
        col.addLayout(head)
        self.desc = QLabel("", objectName="stepDesc", wordWrap=True)
        self.desc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        col.addWidget(self.desc, 1)
        self.prog = QWidget()
        pv = QVBoxLayout(self.prog)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(2)
        self.time = QLabel("", objectName="stepTime")
        self.bar = QProgressBar(objectName="stepBar")
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.pct = QLabel("", objectName="stepPct")
        bl = QHBoxLayout()
        bl.setSpacing(6)
        bl.addWidget(self.bar, 1)
        bl.addWidget(self.pct)
        pv.addWidget(self.time)
        pv.addLayout(bl)
        col.addWidget(self.prog)
        row.addLayout(col, 1)

        self.btn = QPushButton("", objectName="stepStartBtn")
        self.btn.setFixedSize(104, 40)
        self.btn.setFocusPolicy(Qt.NoFocus)
        row.addWidget(self.btn, 0, Qt.AlignVCenter)

    def update_row(self, sv, btn_text: str, btn_enabled: bool, btn_visible: bool) -> None:
        _set_prop(self, "active", sv.active)
        _set_prop(self, "status", sv.status)
        _set_prop(self.num, "status", sv.status)
        _set_prop(self.badge, "status", sv.status)
        self.badge.setText(sv.badge)
        self.art.set_state(done=sv.status == "done", dim=sv.status == "pending")
        show = sv.progress is not None
        self.prog.setVisible(show)
        self.desc.setVisible(not show)
        if show:
            self.time.setText(sv.time_text)
            self.bar.setValue(int(max(0.0, min(1.0, sv.progress)) * 1000))
            self.pct.setText(f"{int(round(sv.progress * 100))}%")
        else:
            self.desc.setText(sv.desc)
        self.btn.setVisible(btn_visible)
        self.btn.setText(btn_text)
        self.btn.setEnabled(btn_enabled)


class PortraitDashboard(QWidget):
    backRequested = pyqtSignal()
    monitorRequested = pyqtSignal()
    historyRequested = pyqtSignal()
    profileEditRequested = pyqtSignal(str)       # 프로필 id, "" = 새 프로필

    def __init__(self, cfg, store: ProfileStore, results_dir: Optional[Path] = None):
        super().__init__()
        self.setObjectName("dashPage")
        self.setProperty("compact", True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._cfg, self._store = cfg, store
        self._ctrl: Optional[MeasureController] = None
        self._view: Optional[ViewState] = None
        self._selected = ""
        self._cards: Dict[str, ProfileCard] = {}
        self._local_msg = ("", "info")
        self._run = RunTracker()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # ---- 상단: 뒤로 / 모델 탭 / 날짜·시간 (오른쪽 끝은 설정 버튼 자리) ----
        top = QHBoxLayout()
        top.setSpacing(6)
        self.back_btn = QPushButton("←", objectName="dashBack")
        self.back_btn.setFixedSize(36, 36)
        self.back_btn.setToolTip("로그인 화면으로")
        self.back_btn.setFocusPolicy(Qt.NoFocus)
        self.back_btn.clicked.connect(self.backRequested)
        self.tab_tro = QPushButton("Troponin", objectName="modelTab")
        self.tab_nt = QPushButton("NT-ProBNP", objectName="modelTab")
        for b, active in ((self.tab_tro, True), (self.tab_nt, False)):
            b.setFixedSize(98, 38)
            b.setFocusPolicy(Qt.NoFocus)
            b.setProperty("active", active)
        self.tab_nt.clicked.connect(lambda: self._flash("NT-ProBNP 모델은 준비 중입니다.", "info"))
        self.clock = QLabel("", objectName="dashClock")
        self.clock.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.back_btn)
        top.addSpacing(4)
        top.addWidget(self.tab_tro)
        top.addWidget(self.tab_nt)
        top.addStretch(1)
        top.addWidget(self.clock)
        top.addSpacing(54)                       # 우측 상단 설정 버튼 자리 (AppWindow 가 위에 얹는다)
        self._top_row = QWidget()
        self._top_row.setLayout(top)
        self._top_row.setFixedHeight(40)
        root.addWidget(self._top_row)

        self.banner = QLabel("", objectName="dashBanner", wordWrap=True)
        self.banner.hide()
        root.addWidget(self.banner)

        # 본문은 스크롤 영역 안에 둔다: 평소(화면에 다 들어갈 때)에는 그대로 보이고, 오류 배너가 떠서 넘치면 밀어서 본다.
        # (스크롤이 없으면 내용의 최소 높이가 창을 화면 밖으로 밀어내 아래쪽이 잘렸다)
        body = QWidget(objectName="dashBody")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(8)
        bv.addWidget(self._build_profiles())
        bv.addWidget(self._build_result())
        bv.addWidget(self._build_progress(), 1)
        bv.addLayout(self._build_bottom())
        self.body_scroll = QScrollArea(objectName="dashScroll")
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body_scroll.setFocusPolicy(Qt.NoFocus)
        self.body_scroll.setWidget(body)
        QScroller.grabGesture(self.body_scroll.viewport(), QScroller.LeftMouseButtonGesture)
        root.addWidget(self.body_scroll, 1)

        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._expire_flash)
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_clock()
        self.refresh_profiles()

    # ================= 만들기 =================
    def _build_profiles(self) -> QFrame:
        f, v, head = card("프로필", "person")
        f.setObjectName("dashCard")
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(6)
        self.profile_card_frame = f
        self.profile_hint = QLabel("● 가족 구성원을 선택하세요.", objectName="profileHint")
        self.edit_btn = QPushButton("편집", objectName="smallBtn")
        self.edit_btn.setFixedSize(54, 28)
        self.edit_btn.setFocusPolicy(Qt.NoFocus)
        self.edit_btn.clicked.connect(lambda: self._selected and self.profileEditRequested.emit(self._selected))
        head.addWidget(self.profile_hint)
        head.addWidget(self.edit_btn)

        self.profile_scroll = QScrollArea()
        self.profile_scroll.setObjectName("profileScroll")
        self.profile_scroll.setFrameShape(QFrame.NoFrame)
        self.profile_scroll.setWidgetResizable(True)
        self.profile_scroll.setFixedHeight(68)
        self.profile_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.profile_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        QScroller.grabGesture(self.profile_scroll.viewport(), QScroller.LeftMouseButtonGesture)
        self._cards_host = QWidget()
        self._cards_host.setObjectName("profileHost")
        self._cards_row = QHBoxLayout(self._cards_host)
        self._cards_row.setContentsMargins(0, 2, 0, 2)
        self._cards_row.setSpacing(8)
        self.profile_scroll.setWidget(self._cards_host)
        v.addWidget(self.profile_scroll)
        return f

    def _build_result(self) -> QFrame:
        f, v, head = card("검사 결과", "chart")
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(6)
        self.done_badge = QLabel("✓ 검증 완료", objectName="okBadge")
        self.done_badge.hide()
        head.addWidget(self.done_badge)

        panel = QFrame(objectName="resultPanel")
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(14, 8, 14, 8)
        pv.setSpacing(0)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.res_title = QLabel(self._cfg.result_title, objectName="resTitle")
        self.res_value = QLabel("—", objectName="resValue")
        self.res_unit = QLabel(self._cfg.result_unit, objectName="resUnit")
        self.res_unit.setVisible(bool(self._cfg.result_unit))
        self.res_status = QLabel("", objectName="resStatus")
        self.res_status.hide()
        row.addWidget(self.res_title, 0, Qt.AlignTop)
        row.addStretch(1)
        row.addWidget(self.res_value)
        row.addWidget(self.res_unit, 0, Qt.AlignBottom)
        row.addStretch(1)
        row.addWidget(self.res_status, 0, Qt.AlignTop)
        pv.addLayout(row)
        self.res_note = QLabel("검사가 끝나면 결과가 표시됩니다.", objectName="resNote", wordWrap=True)
        pv.addWidget(self.res_note)
        line = QFrame(objectName="hline")
        line.setFixedHeight(1)
        pv.addSpacing(2)
        pv.addWidget(line)
        ref = QHBoxLayout()
        ref.addWidget(QLabel("참고 범위 (Reference Range)", objectName="refLabel"))
        ref.addStretch(1)
        self.res_ref = QLabel(ref_text(self._cfg), objectName="refValue")
        ref.addWidget(self.res_ref)
        pv.addLayout(ref)
        v.addWidget(panel)

        info = QHBoxLayout()
        info.setSpacing(6)
        self.info_wait = QLabel("—", objectName="infoValue")
        self.info_done = QLabel("—", objectName="infoValue")
        self.info_method = QLabel(self._cfg.method, objectName="infoValue", wordWrap=True)
        for icon, name, w in (("clock", "측정 시간", self.info_wait), ("calendar", "검증 완료 시간", self.info_done),
                              ("doc", "검사 방법", self.info_method)):
            cell = QHBoxLayout()
            cell.setSpacing(6)
            cell.addWidget(MiniIcon(icon, 20), 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(QLabel(name, objectName="infoName"))
            col.addWidget(w)
            cell.addLayout(col, 1)
            info.addLayout(cell, 1)
        v.addLayout(info)
        return f

    def _build_progress(self) -> QFrame:
        f, v, head = card("검사 진행", "flask")
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(6)
        self.reset_btn = QPushButton("처음부터", objectName="smallBtn")
        self.stop_btn = QPushButton("중지", objectName="smallDanger")
        self.monitor_btn = QPushButton("모니터링", objectName="smallBtn")
        for b, w in ((self.reset_btn, 74), (self.stop_btn, 52), (self.monitor_btn, 78)):
            b.setFixedSize(w, 30)
            b.setFocusPolicy(Qt.NoFocus)
            head.addWidget(b)
        self.reset_btn.clicked.connect(self._on_reset)
        self.stop_btn.clicked.connect(lambda: self._ctrl and self._ctrl.stop())
        self.monitor_btn.clicked.connect(self.monitorRequested)

        self.steps = []
        for i, name in enumerate(STEP_NAMES):
            r = PortStepRow(i, name)
            r.btn.clicked.connect(lambda _=False, k=i: self._on_step_button(k))
            self.steps.append(r)
            v.addWidget(r, 1)
        return f

    def _build_bottom(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        f, v, _ = card("장비 상태", "device")
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(4)
        self.dev_panel = DeviceStatusPanel(40)
        v.addWidget(self.dev_panel)
        self.dev_icons, self.dev_labels, self.dev_module = self.dev_panel.icons, self.dev_panel.labels, self.dev_panel.module
        row.addWidget(f, 5)

        self.history_btn = QPushButton("", objectName="historyLink")
        hl = QHBoxLayout(self.history_btn)
        hl.setContentsMargins(12, 0, 12, 0)
        hl.setSpacing(8)
        icon = SectionIcon("doc", 30)
        icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        text = QLabel("검사 이력 보기  ›", objectName="historyLinkText", wordWrap=True)
        text.setAttribute(Qt.WA_TransparentForMouseEvents)
        hl.addWidget(icon)
        hl.addWidget(text, 1)
        self.history_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)     # 옆의 장비 상태 카드와 같은 높이
        self.history_btn.setFocusPolicy(Qt.NoFocus)
        self.history_btn.clicked.connect(self.historyRequested)
        row.addWidget(self.history_btn, 4)
        self._bottom_widgets = (f, self.history_btn)
        return row

    # ================= 프로필 =================
    def refresh_profiles(self, select: Optional[str] = None) -> None:
        """저장된 프로필 카드를 다시 만든다. select 가 있으면 그 프로필을 고른다. 선택한 프로필이 지워졌으면 선택을 푼다."""
        if select is not None:
            self._selected = select
        if self._selected and self._store.get(self._selected) is None:
            self._selected = ""
        while self._cards_row.count():
            w = self._cards_row.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._cards = {}
        for sp in self._store.all():
            c = ProfileCard(sp.id, sp.name)
            c.clicked.connect(self.select_profile)
            c.longPressed.connect(self.profileEditRequested)
            self._cards[sp.id] = c
            self._cards_row.addWidget(c)
        add = ProfileCard("", "추가", add=True)
        add.clicked.connect(lambda _pid: self.profileEditRequested.emit(""))
        self._cards_row.addWidget(add)
        self._cards_row.addStretch(1)
        self._apply_selection()

    def select_profile(self, pid: str) -> None:
        self._selected = pid if self._selected != pid else ""      # 한 번 더 누르면 선택 해제
        self._apply_selection()

    def _apply_selection(self) -> None:
        for pid, c in self._cards.items():
            c.set_selected(pid == self._selected)
        sp = self._store.get(self._selected) if self._selected else None
        self.edit_btn.setVisible(sp is not None)
        self.profile_hint.setText(f"● {sp.name} 님으로 검사합니다." if sp else "● 가족 구성원을 선택하세요.")
        _set_prop(self.profile_card_frame, "error", False)
        if self._ctrl is not None:
            self._ctrl.patient = sp.profile.to_dict() if sp else {}
        if sp is not None and self._local_msg[0].startswith("프로필"):
            self._flash("", "info")

    def selected_profile(self) -> Optional[PatientProfile]:
        sp = self._store.get(self._selected) if self._selected else None
        return sp.profile if sp else None

    def clear_selection(self) -> None:
        self._selected = ""
        self._apply_selection()

    # ================= 동작 =================
    def primary_btn_for(self, i: int) -> QPushButton:
        return self.steps[i].btn

    @property
    def primary_btn(self) -> QPushButton:
        """현재 단계의 시작 버튼 (가로 화면의 주 버튼에 해당)"""
        i = self._view.stage_index if self._view is not None else 0
        return self.steps[min(i, len(self.steps) - 1)].btn

    def _need_profile(self) -> bool:
        v = self._view
        return bool(self._cfg.require_patient and v is not None and v.state == State.READY and v.stage_index == 0
                    and not (self._ctrl and self._ctrl._done))

    def _on_step_button(self, i: int) -> None:
        if self._ctrl is None or self._view is None or i != self._view.stage_index:
            return
        if self._need_profile() and self.selected_profile() is None:
            _set_prop(self.profile_card_frame, "error", True)
            self._flash("프로필을 선택해 주세요. (없으면 [+ 추가] 로 만드세요.)", "warn", 0)
            return
        was_done = self._view.state == State.DONE
        self._ctrl.primary()
        if was_done:                                   # 새 측정: 이전 사람 정보를 남기지 않는다
            self.clear_selection()

    def _on_reset(self) -> None:
        if self._ctrl is None:
            return
        if self._ctrl.state == State.DONE or QMessageBox.question(
                self, "처음부터", "지금까지 측정한 단계가 모두 지워집니다. 처음부터 다시 할까요?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self._ctrl.restart()

    def _flash(self, text: str, level: str = "info", ms: int = 3500) -> None:
        self._local_msg = (text, level)
        self._show_banner()
        if text and ms:
            self._flash_timer.start(ms)
        else:
            self._flash_timer.stop()

    def _expire_flash(self) -> None:
        self._local_msg = ("", "info")
        self._show_banner()

    def _show_banner(self) -> None:
        text, level = self._local_msg
        if not text and self._view is not None:
            text, level = self._view.banner, self._view.banner_level
        self.banner.setVisible(bool(text))
        self.banner.setText(text)
        _set_prop(self.banner, "level", level)

    # ================= 컨트롤러 연결 / 그리기 =================
    def bind(self, ctrl: MeasureController) -> None:
        self._ctrl = ctrl
        ctrl.meta = {"title": self._cfg.result_title, "unit": self._cfg.result_unit,
                     "ref_low": self._cfg.ref_low, "ref_high": self._cfg.ref_high}
        sp = self.selected_profile()
        ctrl.patient = sp.to_dict() if sp else {}
        ctrl.viewChanged.connect(self.render)
        self.render(ctrl.snapshot())

    def _tick_clock(self) -> None:
        self.clock.setText(korean_datetime_2line(datetime.now()))

    def render(self, v: ViewState) -> None:
        self._view = v
        self._run.update(v, bool(self._ctrl and self._ctrl._done))
        self._show_banner()
        for i, (row, sv) in enumerate(zip(self.steps, step_views(v))):
            text, enabled, visible = step_button(v, i)
            row.update_row(sv, text, enabled, visible)
        self._render_device(device_view(v))
        self._render_result(result_view(self._cfg, v, self._run.wait_seen, self._run.finished_at))
        self.stop_btn.setEnabled(v.stop_enabled)
        self.reset_btn.setEnabled(v.reset_enabled)

    def _render_device(self, d: DeviceView) -> None:
        self.dev_panel.render(d)

    def _render_result(self, r: ResultView) -> None:
        self.done_badge.setVisible(r.verified)
        _set_prop(self.res_value, "ready", r.ready)
        self.res_value.setText(r.value_text)
        self.res_note.setText(r.note)
        self.res_status.setVisible(bool(r.status_text))
        if r.status_text:
            self.res_status.setText(r.status_text)
            _set_prop(self.res_status, "kind", r.status_kind)
        self.info_wait.setText(r.info_wait)
        self.info_done.setText(r.info_done)

    def on_keyboard(self, visible: bool, height: int = 0) -> None:
        pass            # 이 화면에는 입력란이 없다 (프로필 입력은 별도 화면)
