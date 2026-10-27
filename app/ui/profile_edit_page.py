"""프로필 추가/편집 화면 (세로 화면에서 프로필 카드를 길게 누르거나 [편집], [+ 추가] 를 눌렀을 때).

필수: 성명, 성별, 나이, 몸무게 / 옵션: 혈압, 혈당, 만성질환. 저장하면 data/profiles.json 에 들어간다.
"""
from typing import Optional

from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QDoubleValidator, QIntValidator
from PyQt5.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
                             QScroller, QVBoxLayout, QWidget)

from app.measure.patient import CHRONIC_DISEASES, SEXES, PatientProfile, missing_labels
from app.measure.profiles import ProfileStore

from . import dialogs
from .dashboard_widgets import ChipSelect
from .dashboard_page import SuffixEdit, _set_prop


class ProfileEditPage(QWidget):
    saved = pyqtSignal(str)          # 저장한 프로필 id
    deleted = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, store: ProfileStore):
        super().__init__()
        self.setObjectName("profilePage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._store = store
        self._pid = ""                              # "" = 새 프로필
        self._marked = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.back_btn = QPushButton("← 취소", objectName="smallBtn")
        self.back_btn.setFixedSize(84, 40)
        self.back_btn.setFocusPolicy(Qt.NoFocus)
        self.back_btn.clicked.connect(self.cancelled)
        self.title = QLabel("프로필 추가", objectName="profileTitle")
        top.addWidget(self.back_btn)
        top.addSpacing(12)
        top.addWidget(self.title)
        top.addStretch(1)
        root.addLayout(top)

        self.msg = QLabel("", objectName="dashBanner", wordWrap=True)
        self.msg.hide()
        root.addWidget(self.msg)

        # 입력란은 스크롤 영역 안에 둔다 (터치 키보드가 열리면 아래 여백을 늘려 끝 항목까지 올려 볼 수 있다)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setObjectName("profileScroll")
        QScroller.grabGesture(self.scroll.viewport(), QScroller.LeftMouseButtonGesture)
        body = QWidget()
        body.setObjectName("profileBody")
        self._bv = QVBoxLayout(body)
        self._bv.setContentsMargins(0, 0, 0, 0)
        self._bv.setSpacing(10)

        self.f_name = QLineEdit(objectName="textInput")
        self.f_name.setPlaceholderText("성명")
        self.f_name.setClearButtonEnabled(True)
        self.f_sex = QComboBox(objectName="comboInput")
        self.f_sex.addItems(["선택"] + list(SEXES))
        self.f_age = SuffixEdit("세", QIntValidator(0, 120), "0")
        self.f_weight = SuffixEdit("kg", QDoubleValidator(1.0, 400.0, 1), "0")
        self.f_sys = QLineEdit(objectName="textInput")
        self.f_dia = QLineEdit(objectName="textInput")
        for e, ph in ((self.f_sys, "120"), (self.f_dia, "80")):
            e.setValidator(QIntValidator(0, 300))
            e.setPlaceholderText(ph)
        self.f_glu = QLineEdit(objectName="textInput")
        self.f_glu.setValidator(QDoubleValidator(0.0, 1500.0, 1))
        self.f_glu.setPlaceholderText("98")
        self.f_chronic = ChipSelect(CHRONIC_DISEASES, "선택")
        for w in (self.f_name, self.f_sex, self.f_sys, self.f_dia, self.f_glu, self.f_chronic):
            w.setFixedHeight(48)
        for w in (self.f_age, self.f_weight):
            w.setFixedHeight(48)

        self._section("필수", "이 프로필로 검사하려면 모두 입력해야 합니다.")
        self._field("성명", self.f_name, True)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self._wrap("성별", self.f_sex, True), 1)
        row.addWidget(self._wrap("나이", self.f_age, True), 1)
        row.addWidget(self._wrap("몸무게(kg)", self.f_weight, True), 1)
        self._bv.addLayout(row)
        self._section("옵션", "입력하면 더 정확한 해석에 도움이 됩니다.")
        bp = QHBoxLayout()
        bp.setSpacing(6)
        bp.addWidget(self.f_sys)
        bp.addWidget(QLabel("/", objectName="inputUnit"))
        bp.addWidget(self.f_dia)
        w = QWidget()
        w.setLayout(bp)
        self._field("혈압(mmHg)", w)
        self._field("혈당(mg/dL)", self.f_glu)
        self._field("만성질환", self.f_chronic)
        self._pad = QWidget()
        self._pad.setFixedHeight(0)
        self._bv.addWidget(self._pad)
        self._bv.addStretch(1)
        self.scroll.setWidget(body)
        root.addWidget(self.scroll, 1)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.delete_btn = QPushButton("삭제", objectName="smallDanger")
        self.save_btn = QPushButton("저장", objectName="dashPrimary")
        for b in (self.delete_btn, self.save_btn):
            b.setFixedHeight(50)
            b.setFocusPolicy(Qt.NoFocus)
        row.addWidget(self.delete_btn, 1)
        row.addWidget(self.save_btn, 2)
        self.actions = QWidget()
        self.actions.setLayout(row)
        root.addWidget(self.actions)

        self.save_btn.clicked.connect(self._save)
        self.delete_btn.clicked.connect(self._delete)
        for e in (self.f_name, self.f_age.edit, self.f_weight.edit):
            e.textChanged.connect(self._clear_marks)
        self.f_sex.currentIndexChanged.connect(self._clear_marks)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._scroll_to_focus)

    # ---- 만들기 보조 ----
    def _section(self, title: str, hint: str) -> None:
        row = QHBoxLayout()
        t = QLabel(title, objectName="subPanelTitle")
        t.setProperty("accent", "blue")
        row.addWidget(t)
        row.addWidget(QLabel(hint, objectName="subPanelHint"))
        row.addStretch(1)
        self._bv.addLayout(row)

    def _wrap(self, label: str, widget: QWidget, required: bool = False) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(QLabel(label + (' <span style="color:#E04848;">●</span>' if required else ""),
                           objectName="fieldLabel", textFormat=Qt.RichText))
        v.addWidget(widget)
        return w

    def _field(self, label: str, widget: QWidget, required: bool = False) -> None:
        self._bv.addWidget(self._wrap(label, widget, required))

    # ---- 열기 ----
    def open_new(self) -> None:
        self._pid = ""
        self.title.setText("프로필 추가")
        self._fill(PatientProfile())
        self.delete_btn.hide()
        self._open_common()

    def open_edit(self, pid: str) -> bool:
        sp = self._store.get(pid)
        if sp is None:
            return False
        self._pid = pid
        self.title.setText("프로필 편집")
        self._fill(sp.profile)
        self.delete_btn.show()
        self._open_common()
        return True

    def _open_common(self) -> None:
        self.msg.hide()
        self._marked = set()
        self._set_marks()
        self.scroll.verticalScrollBar().setValue(0)

    def _fill(self, p: PatientProfile) -> None:
        self.f_name.setText(p.name)
        self.f_sex.setCurrentIndex(SEXES.index(p.sex) + 1 if p.sex in SEXES else 0)
        self.f_age.edit.setText("" if p.age is None else str(p.age))
        self.f_weight.edit.setText("" if p.weight is None else f"{p.weight:g}")
        self.f_sys.setText("" if p.bp_sys is None else str(p.bp_sys))
        self.f_dia.setText("" if p.bp_dia is None else str(p.bp_dia))
        self.f_glu.setText("" if p.glucose is None else f"{p.glucose:g}")
        self.f_chronic.set_selected(p.chronic)

    def current(self) -> PatientProfile:
        return PatientProfile.from_texts(self.f_name.text(), self.f_sex.currentText(), self.f_age.text(),
                                         self.f_weight.text(), self.f_sys.text(), self.f_dia.text(), self.f_glu.text(),
                                         self.f_chronic.selected())

    # ---- 동작 ----
    def _save(self) -> None:
        p = self.current()
        miss = p.missing()
        if miss:
            self._marked = set(miss)
            self._set_marks()
            self._show(f"필수 정보를 입력해 주세요: {missing_labels(miss)}")
            return
        dup = next((x for x in self._store.all() if x.name == p.name and x.id != self._pid), None)
        if dup is not None:
            self._marked = {"name"}
            self._set_marks()
            self._show("같은 이름의 프로필이 이미 있습니다.")
            return
        pid = self._pid
        if pid:
            self._store.update(pid, p)
        else:
            pid = self._store.add(p)
        self.saved.emit(pid)

    def _delete(self) -> None:
        if not self._pid:
            return
        name = self.f_name.text()
        if dialogs.confirm(self, "프로필 삭제", f"'{name}' 프로필을 삭제할까요?\n이미 저장된 검사 결과는 지워지지 않습니다.",
                           yes="삭제", no="취소"):
            pid, self._pid = self._pid, ""
            self._store.delete(pid)
            self.deleted.emit(pid)

    def _show(self, text: str) -> None:
        self.msg.setText(text)
        self.msg.setVisible(bool(text))

    def _set_marks(self) -> None:
        for k, w in (("name", self.f_name), ("sex", self.f_sex), ("age", self.f_age), ("weight", self.f_weight)):
            _set_prop(w, "error", k in self._marked)

    def _clear_marks(self, *_) -> None:
        if self._marked:
            self._marked = set(self.current().missing()) & self._marked
            self._set_marks()
            if not self._marked:
                self._show("")

    # ---- 키보드 ----
    def on_keyboard(self, visible: bool, height: int = 0) -> None:
        """키보드가 열리면 아래에 키보드 높이만큼 빈 칸을 늘려, 마지막 입력란도 키보드 위로 올려 볼 수 있게 한다."""
        self._pad.setFixedHeight(height if visible else 0)
        self.actions.setVisible(not visible)
        if visible:
            self._scroll_timer.start(80)

    def _scroll_to_focus(self) -> None:
        w = self.focusWidget()
        if w is not None and self.scroll.isAncestorOf(w):
            self.scroll.ensureWidgetVisible(w, 0, 40)
