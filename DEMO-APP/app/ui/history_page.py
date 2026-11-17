"""검사 이력 화면 ([검사이력] 탭). 지난 검사를 검색·필터·정렬해서 찾는다.

위에서부터: 뒤로/제목 · 검색창(이름·날짜·검사 항목·결과) · 검사 항목 칩(전체/Troponin/NT-proBNP) · 상태/정렬 버튼 · 건수 · 목록.
상태와 정렬 버튼은 누를 때마다 다음 항목으로 바뀐다 (터치 화면에서 목록 팝업 없이 쓰려고).
"""
from pathlib import Path
from typing import List

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.measure.history import SORTS, STATUSES, HistoryItem, find_history, load_history

from .dashboard_widgets import HistoryTable
from .widgets import Field

ASSAY_CHIPS = (("전체", ""), ("Troponin", "Troponin"), ("NT-proBNP", "NT-proBNP"))     # (화면 문구, 기록의 검사 항목 이름)
LOAD_LIMIT = 500                  # 한 번에 읽는 최대 기록 수 (오래된 것은 검색 대상에서 빠진다)


class HistoryPage(QWidget):
    backRequested = pyqtSignal()

    def __init__(self, results_dir, limit: int = LOAD_LIMIT):
        super().__init__()
        self.setObjectName("historyPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._dir, self._limit = Path(results_dir), limit
        self._items: List[HistoryItem] = []
        self._title = ""                 # 검사 항목 필터 ("" = 전체)
        self._status_i = 0               # STATUSES 의 위치
        self._sort_i = 0                 # SORTS 의 위치

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 14)
        root.setSpacing(8)

        top = QHBoxLayout()
        self.back_btn = QPushButton("← 뒤로", objectName="smallBtn")
        self.back_btn.setFixedSize(84, 40)
        self.back_btn.setFocusPolicy(Qt.NoFocus)
        self.back_btn.clicked.connect(self.backRequested)
        self.title = QLabel("검사 이력", objectName="profileTitle")
        top.addWidget(self.back_btn)
        top.addSpacing(12)
        top.addWidget(self.title)
        top.addStretch(1)
        root.addLayout(top)

        self.search = Field("이름 · 날짜 · 검사 항목 · 결과로 검색", height=44, large=True)
        self.search.edit.setClearButtonEnabled(True)
        self.search.edit.textChanged.connect(self._apply)
        root.addWidget(self.search)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.chips = []
        for text, key in ASSAY_CHIPS:
            b = QPushButton(text, objectName="modelTab")
            b.setFixedHeight(36)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, k=key: self._pick_title(k))
            chips.addWidget(b, 1)
            self.chips.append((key, b))
        root.addLayout(chips)

        opts = QHBoxLayout()
        opts.setSpacing(6)
        self.status_btn = QPushButton("", objectName="smallBtn")
        self.sort_btn = QPushButton("", objectName="smallBtn")
        self.reset_btn = QPushButton("초기화", objectName="smallBtn")
        self.reset_btn.setMinimumWidth(76)
        for b in (self.status_btn, self.sort_btn, self.reset_btn):
            b.setFixedHeight(38)
            b.setFocusPolicy(Qt.NoFocus)
        self.status_btn.clicked.connect(self._next_status)
        self.sort_btn.clicked.connect(self._next_sort)
        self.reset_btn.clicked.connect(self.reset_filters)
        opts.addWidget(self.status_btn, 1)
        opts.addWidget(self.sort_btn, 1)
        opts.addWidget(self.reset_btn)
        root.addLayout(opts)

        self.count = QLabel("", objectName="monStatus")
        root.addWidget(self.count)
        card = QWidget(objectName="dashCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(8, 8, 8, 8)
        self.table = HistoryTable(show_patient=True)
        cv.addWidget(self.table)
        root.addWidget(card, 1)
        self._pad = QWidget()                          # 키보드가 열리면 그 높이만큼 비워 목록이 가려지지 않게 한다
        self._pad.setFixedHeight(0)
        root.addWidget(self._pad)
        self._sync_buttons()

    # ---- 필터/정렬 조작 ----
    def _pick_title(self, key: str) -> None:
        self._title = key
        self._apply()

    def _next_status(self) -> None:
        self._status_i = (self._status_i + 1) % len(STATUSES)
        self._apply()

    def _next_sort(self) -> None:
        self._sort_i = (self._sort_i + 1) % len(SORTS)
        self._apply()

    def reset_filters(self) -> None:
        self.search.edit.blockSignals(True)
        self.search.edit.clear()
        self.search.edit.blockSignals(False)
        self._title, self._status_i, self._sort_i = "", 0, 0
        self._apply()

    @property
    def query(self) -> str:
        return self.search.text().strip()

    def _filtered(self) -> bool:
        return bool(self.query or self._title or self._status_i)

    def _sync_buttons(self) -> None:
        for key, b in self.chips:
            b.setProperty("active", key == self._title)
            b.style().unpolish(b)
            b.style().polish(b)
        self.status_btn.setText(f"상태: {STATUSES[self._status_i]}")
        self.sort_btn.setText(f"정렬: {SORTS[self._sort_i]}")
        self.reset_btn.setEnabled(self._filtered() or self._sort_i != 0)

    def _apply(self, *_args) -> None:
        shown = find_history(self._items, self.query, self._title,
                             "" if self._status_i == 0 else STATUSES[self._status_i], SORTS[self._sort_i])
        self.table.set_items(shown)
        self._sync_buttons()
        if not self._items:
            self.count.setText("아직 검사 이력이 없습니다.")
        elif self._filtered():
            self.count.setText(f"검색 결과 {len(shown)}건 (전체 {len(self._items)}건)" if shown
                               else f"조건에 맞는 기록이 없습니다. (전체 {len(self._items)}건)")
        else:
            self.count.setText(f"전체 {len(self._items)}건")

    # ---- 바깥에서 부르는 것 ----
    def refresh(self) -> None:
        self._items = load_history(self._dir, self._limit)
        self._apply()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        fmt = "%m. %d %H:%M" if self.width() < 600 else "%Y. %m. %d  %H:%M"      # 세로(좁은) 화면은 연도를 뺀다
        if fmt != self.table.date_format:
            self.table.date_format = fmt
            self._apply()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.refresh()

    def on_keyboard(self, visible: bool, height: int = 0) -> None:
        self._pad.setFixedHeight(height if visible else 0)
