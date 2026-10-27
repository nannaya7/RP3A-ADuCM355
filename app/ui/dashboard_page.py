"""가로(1280x800) 측정 화면 — 환자 프로필 / 검사 결과 / 검사 진행(3단계) / 장비 상태 / 검사 이력.

세로(480x800) 측정 화면은 별도 시안을 받은 뒤 만든다 (그때까지는 ui/measure_page.py 의 임시 배치를 쓴다).
이 화면은 MeasureController 의 ViewState 만 그린다 (측정 로직은 모른다). 공개 이름은 MeasurePage 와 같게 맞췄다:
backRequested, monitorRequested, bind(), render(), primary_btn / stop_btn / reset_btn / monitor_btn.
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QDoubleValidator, QIntValidator
from PyQt5.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar,
                             QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from app.measure.controller import MeasureController, State, ViewState, fmt_mmss
from app.measure.history import classify, format_value, load_history
from app.measure.patient import CHRONIC_DISEASES, SEXES, PatientProfile, missing_labels

from .dashboard_logic import (MEASURING, STEP_NAMES, DeviceView, ResultView, RunTracker, device_view, korean_datetime,
                              ref_text, result_view, step_views)
from .dashboard_widgets import ChipSelect, DeviceStatusPanel, HistoryTable, SectionIcon, StepCard

def _set_prop(w: QWidget, name: str, value) -> None:
    w.setProperty(name, value)
    w.style().unpolish(w)
    w.style().polish(w)


def card(title: str, icon: str, sub: str = "") -> tuple:
    """제목 줄이 있는 카드. (카드, 본문 레이아웃, 제목 줄 레이아웃) 을 돌려준다."""
    f = QFrame(objectName="dashCard")
    v = QVBoxLayout(f)
    v.setContentsMargins(18, 14, 18, 14)
    v.setSpacing(10)
    head = QHBoxLayout()
    head.setSpacing(10)
    head.addWidget(SectionIcon(icon))
    head.addWidget(QLabel(title, objectName="cardHeadTitle"))
    if sub:
        head.addWidget(QLabel(sub, objectName="cardHeadSub"))
    head.addStretch(1)
    v.addLayout(head)
    return f, v, head


class SuffixEdit(QFrame):
    """값 + 단위(세, kg 등)가 한 칸에 있는 입력란"""

    def __init__(self, suffix: str, validator, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("inputFrame")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setObjectName("inputInner")
        self.edit.setValidator(validator)
        self.edit.setPlaceholderText(placeholder)
        self.unit = QLabel(suffix, objectName="inputUnit")
        row.addWidget(self.edit, 1)
        row.addWidget(self.unit)
        self.setFixedHeight(44)

    def text(self) -> str:
        return self.edit.text()

    def clear(self) -> None:
        self.edit.clear()


class DashboardPage(QWidget):
    backRequested = pyqtSignal()
    monitorRequested = pyqtSignal()
    historyRequested = pyqtSignal()               # [검사이력] 탭
    assayRequested = pyqtSignal(str)             # troponin / ntprobnp (탭을 눌렀을 때)

    def __init__(self, cfg, results_dir: Optional[Path] = None):
        super().__init__()
        self.setObjectName("dashPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._cfg = cfg
        self._results_dir = Path(results_dir) if results_dir else Path(cfg.results_dir)
        self._ctrl: Optional[MeasureController] = None
        self._view: Optional[ViewState] = None
        self._local_msg = ("", "info")
        self._run = RunTracker()
        self._marked: set = set()
        # 화면에 묶인 일회용 타이머. QTimer.singleShot(람다) 는 화면이 먼저 사라져도 나중에 실행되어 PyQt 가 프로그램을 종료시킨다.
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._expire_flash)
        self._hist_timer = QTimer(self)
        self._hist_timer.setSingleShot(True)
        self._hist_timer.timeout.connect(self.refresh_history)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 10, 20, 14)
        root.setSpacing(10)

        # ---- 상단: 뒤로 / 모델 탭 / 날짜·시간 (오른쪽 끝은 설정 버튼 자리) ----
        top = QHBoxLayout()
        top.setSpacing(12)
        self.back_btn = QPushButton("←", objectName="dashBack")
        self.back_btn.setFixedSize(44, 44)
        self.back_btn.setToolTip("로그인 화면으로")
        self.back_btn.setFocusPolicy(Qt.NoFocus)
        self.back_btn.clicked.connect(self.backRequested)
        self.tab_tro = QPushButton("Troponin", objectName="modelTab")
        self.tab_nt = QPushButton("NT-ProBNP", objectName="modelTab")
        self.tab_hist = QPushButton("검사이력", objectName="modelTab")      # 화면 전환(검사 항목이 아님): 눌러도 활성 표시는 바뀌지 않는다
        for b, active in ((self.tab_tro, True), (self.tab_nt, False), (self.tab_hist, False)):
            b.setFixedSize(220 if b is not self.tab_hist else 160, 46)
            b.setFocusPolicy(Qt.NoFocus)
            b.setProperty("active", active)
        self.tab_tro.clicked.connect(lambda: self.assayRequested.emit("troponin"))
        self.tab_nt.clicked.connect(lambda: self.assayRequested.emit("ntprobnp"))
        self.tab_hist.clicked.connect(self.historyRequested)
        self.clock = QLabel("", objectName="dashClock")
        top.addWidget(self.back_btn)
        top.addSpacing(6)
        top.addWidget(self.tab_tro)
        top.addWidget(self.tab_nt)
        top.addWidget(self.tab_hist)
        top.addStretch(1)
        top.addWidget(self.clock)
        top.addSpacing(64)                      # 우측 상단 설정 버튼 자리 (AppWindow 가 위에 얹는다)
        root.addLayout(top)

        self.banner = QLabel("", objectName="dashBanner", wordWrap=True)
        self.banner.hide()
        root.addWidget(self.banner)

        # ---- 윗줄: 환자 프로필 | 검사 결과 ----
        row1 = QHBoxLayout()
        row1.setSpacing(14)
        row1.addWidget(self._build_patient(), 5)
        row1.addWidget(self._build_result(), 3)
        root.addLayout(row1, 10)

        # ---- 아랫줄: 검사 진행 | (장비 상태 / 검사 이력) ----
        row2 = QHBoxLayout()
        row2.setSpacing(14)
        row2.addWidget(self._build_progress(), 15)
        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(self._build_device(), 10)
        right.addWidget(self._build_history(), 11)
        row2.addLayout(right, 9)                 # 윗줄(5 : 3)과 같은 비율(15 : 9)이라 오른쪽 카드들의 왼쪽 끝이 맞는다
        root.addLayout(row2, 10)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_clock()
        self.refresh_history()

    # ================= 만들기 =================
    def _labeled(self, label: str, widget: QWidget, required: bool = False) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(QLabel(label + (' <span style="color:#E04848;">●</span>' if required else ""),
                           objectName="fieldLabel", textFormat=Qt.RichText))
        v.addWidget(widget)
        return w

    def _panel(self, title: str, hint: str, accent: str) -> tuple:
        f = QFrame(objectName="subPanel")
        v = QVBoxLayout(f)
        v.setContentsMargins(14, 8, 14, 12)
        v.setSpacing(6)
        head = QHBoxLayout()
        t = QLabel(title, objectName="subPanelTitle")
        t.setProperty("accent", accent)
        head.addWidget(t)
        head.addWidget(QLabel(hint, objectName="subPanelHint"))
        head.addStretch(1)
        v.addLayout(head)
        return f, v

    def _build_patient(self) -> QFrame:
        f, v, _ = card("환자 프로필", "person")
        v.setSpacing(8)
        req, rv = self._panel("필수", "검사에 필요한 필수 정보를 입력하세요.", "blue")
        row = QHBoxLayout()
        row.setSpacing(12)
        self.f_name = QLineEdit(objectName="textInput")
        self.f_name.setPlaceholderText("성명")
        self.f_name.setClearButtonEnabled(True)
        self.f_name.setFixedHeight(44)
        self.f_sex = QComboBox(objectName="comboInput")
        self.f_sex.addItems(["선택"] + list(SEXES))
        self.f_sex.setFixedHeight(44)
        self.f_age = SuffixEdit("세", QIntValidator(0, 120), "0")
        self.f_weight = SuffixEdit("kg", QDoubleValidator(1.0, 400.0, 1), "0")
        for label, w, stretch in (("성명", self.f_name, 5), ("성별", self.f_sex, 3), ("나이", self.f_age, 3),
                                  ("몸무게(kg)", self.f_weight, 3)):
            row.addWidget(self._labeled(label, w, required=True), stretch)
        rv.addLayout(row)
        v.addWidget(req)

        opt, ov = self._panel("옵션", "추가 정보를 입력하면 더 정확한 해석에 도움이 됩니다.", "blue")
        row = QHBoxLayout()
        row.setSpacing(12)
        bp = QWidget()
        bl = QHBoxLayout(bp)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        self.f_sys = QLineEdit(objectName="textInput")
        self.f_dia = QLineEdit(objectName="textInput")
        for e, ph in ((self.f_sys, "120"), (self.f_dia, "80")):
            e.setValidator(QIntValidator(0, 300))
            e.setPlaceholderText(ph)
            e.setFixedHeight(44)
        bl.addWidget(self.f_sys)
        bl.addWidget(QLabel("/", objectName="inputUnit"))
        bl.addWidget(self.f_dia)
        self.f_glu = QLineEdit(objectName="textInput")
        self.f_glu.setValidator(QDoubleValidator(0.0, 1500.0, 1))
        self.f_glu.setPlaceholderText("98")
        self.f_glu.setFixedHeight(44)
        self.f_chronic = ChipSelect(CHRONIC_DISEASES, "선택")
        self.f_chronic.setFixedHeight(44)
        row.addWidget(self._labeled("혈압(mmHg)", bp), 4)
        row.addWidget(self._labeled("혈당(mg/dL)", self.f_glu), 3)
        row.addWidget(self._labeled("만성질환", self.f_chronic), 5)
        ov.addLayout(row)
        v.addWidget(opt)
        v.addStretch(1)

        for e in (self.f_name, self.f_age.edit, self.f_weight.edit, self.f_sys, self.f_dia, self.f_glu):
            e.textChanged.connect(self._on_profile_changed)
        self.f_sex.currentIndexChanged.connect(self._on_profile_changed)
        self.f_chronic.changed.connect(self._on_profile_changed)
        return f

    def _build_result(self) -> QFrame:
        f, v, head = card("검사 결과", "chart")
        self.done_badge = QLabel("✓ 검증 완료", objectName="okBadge")
        self.done_badge.hide()
        head.addWidget(self.done_badge)

        panel = QFrame(objectName="resultPanel")
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(20, 14, 20, 14)
        pv.setSpacing(2)
        top = QHBoxLayout()
        self.res_title = QLabel(self._cfg.result_title, objectName="resTitle")
        self.res_status = QLabel("", objectName="resStatus")
        self.res_status.hide()
        top.addWidget(self.res_title)
        top.addStretch(1)
        top.addWidget(self.res_status)
        pv.addLayout(top)
        val = QHBoxLayout()
        val.setSpacing(8)
        self.res_value = QLabel("—", objectName="resValue")
        self.res_unit = QLabel(self._cfg.result_unit, objectName="resUnit")
        self.res_unit.setVisible(bool(self._cfg.result_unit))
        val.addWidget(self.res_value)
        val.addWidget(self.res_unit, 0, Qt.AlignBottom)
        val.addStretch(1)
        pv.addLayout(val)
        self.res_note = QLabel("검사가 끝나면 결과가 표시됩니다.", objectName="resNote", wordWrap=True)
        pv.addWidget(self.res_note)
        line = QFrame(objectName="hline")
        line.setFixedHeight(1)
        pv.addSpacing(4)
        pv.addWidget(line)
        ref = QHBoxLayout()
        ref.addWidget(QLabel("참고 범위 (Reference Range)", objectName="refLabel"))
        ref.addStretch(1)
        self.res_ref = QLabel(ref_text(self._cfg), objectName="refValue")
        ref.addWidget(self.res_ref)
        pv.addLayout(ref)
        v.addWidget(panel, 1)

        info = QFrame(objectName="infoPanel")
        il = QHBoxLayout(info)
        il.setContentsMargins(14, 10, 14, 10)
        il.setSpacing(10)
        self.info_wait = QLabel("—", objectName="infoValue")
        self.info_done = QLabel("—", objectName="infoValue")
        self.info_method = QLabel(self._cfg.method, objectName="infoValue", wordWrap=True)
        for name, w in (("측정 시간", self.info_wait), ("검증 완료 시간", self.info_done), ("검사 방법", self.info_method)):
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(QLabel(name, objectName="infoName"))
            col.addWidget(w)
            il.addLayout(col, 1)
        v.addWidget(info)
        return f

    def _build_progress(self) -> QFrame:
        f, v, head = card("검사 진행", "flask", "센서 3개 · 0 → 1 → 2 순서")
        self.reset_btn = QPushButton("처음부터", objectName="smallBtn")
        self.stop_btn = QPushButton("중지", objectName="smallDanger")
        self.monitor_btn = QPushButton("모니터링", objectName="smallBtn")
        self.primary_btn = QPushButton("", objectName="dashPrimary")
        for b, w in ((self.reset_btn, 86), (self.stop_btn, 64), (self.monitor_btn, 90), (self.primary_btn, 150)):
            b.setFixedSize(w, 38 if b is not self.primary_btn else 40)
            b.setFocusPolicy(Qt.NoFocus)
            head.addWidget(b)
        self.reset_btn.clicked.connect(self._on_reset)
        self.stop_btn.clicked.connect(lambda: self._ctrl and self._ctrl.stop())
        self.monitor_btn.clicked.connect(self.monitorRequested)
        self.primary_btn.clicked.connect(self._on_primary)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.steps = []
        for i, name in enumerate(STEP_NAMES):
            sc = StepCard(i, name)
            self.steps.append(sc)
            row.addWidget(sc, 1)
            if i < 2:
                row.addWidget(QLabel("›", objectName="stepArrow"))
        v.addLayout(row, 1)
        return f

    def _build_device(self) -> QFrame:
        f, v, _ = card("장비 상태", "device")
        v.setSpacing(6)
        # 세로 화면과 같은 아이콘 3개(장비 / 키트 / 연결)와 한 줄 문구
        self.dev_panel = DeviceStatusPanel(56)
        v.addStretch(1)
        v.addWidget(self.dev_panel)
        v.addStretch(1)
        self.dev_icons, self.dev_labels, self.dev_module = self.dev_panel.icons, self.dev_panel.labels, self.dev_panel.module
        return f

    def _build_history(self) -> QFrame:
        f, v, head = card("검사 이력", "doc")
        v.setSpacing(4)
        self.history = HistoryTable()
        v.addWidget(self.history, 1)
        return f

    # ================= 입력 / 검증 =================
    def profile(self) -> PatientProfile:
        sex = self.f_sex.currentText()
        return PatientProfile.from_texts(self.f_name.text(), sex, self.f_age.text(), self.f_weight.text(),
                                         self.f_sys.text(), self.f_dia.text(), self.f_glu.text(),
                                         self.f_chronic.selected())

    def clear_profile(self) -> None:
        for e in (self.f_name, self.f_age.edit, self.f_weight.edit, self.f_sys, self.f_dia, self.f_glu):
            e.clear()
        self.f_sex.setCurrentIndex(0)
        self.f_chronic.set_selected([])

    def _on_profile_changed(self, *_) -> None:
        p = self.profile()
        if self._ctrl is not None:
            self._ctrl.patient = p.to_dict()
        self._mark_missing([k for k in ("name", "sex", "age", "weight")
                            if k in self._marked and k in p.missing()])
        if p.is_complete() and self._local_msg[0].startswith("필수 정보"):
            self._flash("", "info")

    def _mark_missing(self, keys) -> None:
        self._marked = set(keys)
        for k, w in (("name", self.f_name), ("sex", self.f_sex), ("age", self.f_age), ("weight", self.f_weight)):
            _set_prop(w, "error", k in self._marked)

    def _need_patient(self) -> bool:
        v = self._view
        return bool(self._cfg.require_patient and v is not None and v.state == State.READY and v.stage_index == 0
                    and not self._ctrl_has_progress())

    def _ctrl_has_progress(self) -> bool:
        return bool(self._ctrl and self._ctrl._done)

    def _on_primary(self) -> None:
        if self._ctrl is None:
            return
        v = self._view
        if self._need_patient():
            p = self.profile()
            if not p.is_complete():
                self._marked = set(p.missing())
                self._mark_missing(p.missing())
                self._flash(f"필수 정보를 입력해 주세요: {missing_labels(p.missing())}", "warn", 0)
                return
        if v is not None and v.state == State.DONE:             # 새 측정: 이전 환자 정보를 남기지 않는다
            self._ctrl.primary()
            self.clear_profile()
            self._ctrl.patient = self.profile().to_dict()
            return
        self._ctrl.primary()

    def _on_reset(self) -> None:
        if self._ctrl is None:
            return
        if self._ctrl.state == State.DONE or QMessageBox.question(
                self, "처음부터", "지금까지 측정한 단계가 모두 지워집니다. 처음부터 다시 할까요?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self._ctrl.restart()

    def _flash(self, text: str, level: str = "info", ms: int = 3500) -> None:
        """컨트롤러 안내보다 우선하는 화면 자체 안내. ms=0 이면 조건이 풀릴 때까지 유지."""
        self._local_msg = (text, level)
        self._show_banner()
        if text and ms:
            self._flash_timer.start(ms)                 # 화면이 사라지면 타이머도 함께 사라진다
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

    def set_assay(self, key: str, cfg) -> None:
        """검사 항목(모델)을 바꿨을 때 탭과 결과 카드의 제목·단위·참고 범위를 맞춘다. 컨트롤러 전환은 AppWindow 가 먼저 한다."""
        self._cfg = cfg
        _set_prop(self.tab_tro, "active", key == "troponin")
        _set_prop(self.tab_nt, "active", key == "ntprobnp")
        self.res_title.setText(cfg.result_title)
        self.res_unit.setText(cfg.result_unit)
        self.res_unit.setVisible(bool(cfg.result_unit))
        self.res_ref.setText(ref_text(cfg))
        if self._ctrl is not None:
            self.render(self._ctrl.snapshot())

    def assay_blocked(self, text: str) -> None:
        self._flash(text, "warn")

    # ================= 컨트롤러 연결 / 그리기 =================
    def bind(self, ctrl: MeasureController) -> None:
        self._ctrl = ctrl
        ctrl.meta = {"title": self._cfg.result_title, "unit": self._cfg.result_unit,
                     "ref_low": self._cfg.ref_low, "ref_high": self._cfg.ref_high}
        ctrl.patient = self.profile().to_dict()
        ctrl.finished.connect(self._on_finished)
        ctrl.viewChanged.connect(self.render)
        self.render(ctrl.snapshot())

    def _on_finished(self, _result) -> None:
        self._hist_timer.start(300)                     # 결과 파일이 쓰인 뒤에 이력을 다시 읽는다

    def refresh_history(self) -> None:
        self.history.set_items(load_history(self._results_dir))

    def _tick_clock(self) -> None:
        self.clock.setText(korean_datetime(datetime.now()))

    def render(self, v: ViewState) -> None:
        self._view = v
        self._run.update(v, bool(self._ctrl and self._ctrl._done))

        self._show_banner()
        for sc, sv in zip(self.steps, step_views(v)):
            sc.update_card(sv.status, sv.badge, sv.active, sv.desc, sv.time_text, sv.progress)
        self._render_device(device_view(v))
        self._render_result(result_view(self._cfg, v, self._run.wait_seen, self._run.finished_at))

        self.primary_btn.setText(v.primary_label)
        self.primary_btn.setEnabled(v.primary_enabled)
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
        pass            # 입력란이 모두 화면 위쪽(키보드 위)에 있어서 배치를 바꿀 필요가 없다
