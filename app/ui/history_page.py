"""검사 이력 화면 (세로 화면의 [검사 이력 보기]). 최근 검사 목록을 크게 보여 준다."""
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.measure.history import load_history

from .dashboard_widgets import HistoryTable


class HistoryPage(QWidget):
    backRequested = pyqtSignal()

    def __init__(self, results_dir, limit: int = 50):
        super().__init__()
        self.setObjectName("historyPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._dir, self._limit = Path(results_dir), limit
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 14)
        root.setSpacing(10)
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
        self.count = QLabel("", objectName="monStatus")
        root.addWidget(self.count)
        card = QWidget(objectName="dashCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(12, 10, 12, 10)
        self.table = HistoryTable()
        cv.addWidget(self.table)
        root.addWidget(card, 1)

    def refresh(self) -> None:
        items = load_history(self._dir, self._limit)
        self.table.set_items(items)
        self.count.setText(f"최근 {len(items)}건" if items else "아직 검사 이력이 없습니다.")

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.refresh()

    def on_keyboard(self, visible: bool, height: int = 0) -> None:
        pass
