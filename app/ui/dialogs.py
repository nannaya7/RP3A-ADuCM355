"""확인/안내 팝업. 아이콘 없이 가운데 정렬한 문구와 큰 버튼을 쓰고, 색은 theme.qss 의 #popup 을 따른다.
창 틀은 쓰지 않고(라즈베리 파이 창 틀은 한글 제목이 깨지고 모서리도 각진다) 둥근 모서리의 자체 틀을 그린다."""
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class _Popup(QDialog):
    def __init__(self, parent, text: str, buttons):
        """buttons: [(문구, 강조 여부)] — 눌린 버튼의 위치를 self.choice 에 남긴다."""
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setObjectName("popup")
        self.setAttribute(Qt.WA_TranslucentBackground, True)         # 바깥 네모를 투명하게 해 둥근 모서리만 보이게 한다
        self.setWindowTitle(" ")
        self.setModal(True)
        self.choice = -1
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bar = QFrame(objectName="popupBar")                          # 위쪽 회색 띠 (오른쪽 × 는 취소)
        bar.setFixedHeight(34)
        bar_row = QHBoxLayout(bar)
        bar_row.setContentsMargins(8, 0, 10, 0)
        bar_row.addStretch(1)
        close = QPushButton("✕", objectName="popupClose")
        close.setFixedSize(32, 28)
        close.setFocusPolicy(Qt.NoFocus)
        close.clicked.connect(self.reject)
        bar_row.addWidget(close)
        outer.addWidget(bar)
        body = QFrame(objectName="popupBody")
        outer.addWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 28, 28, 24)
        root.setSpacing(24)
        label = QLabel(text, objectName="popupText")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        root.addWidget(label)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.buttons = []
        for i, (caption, primary) in enumerate(buttons):
            b = QPushButton(caption, objectName="popupBtn")
            b.setProperty("primary", primary)
            b.setFixedHeight(48)
            b.setMinimumWidth(110)
            b.setAutoDefault(False)
            b.clicked.connect(lambda _=False, n=i: self._pick(n))
            row.addWidget(b, 1)
            self.buttons.append(b)
        root.addLayout(row)
        self.setMinimumWidth(340)

    def _pick(self, n: int) -> None:
        self.choice = n
        self.accept()


def _run(parent, text: str, buttons) -> int:
    box = _Popup(parent, text, buttons)
    box.exec_()
    choice = box.choice
    box.deleteLater()
    return choice


def confirm(parent, title: str, text: str, yes: str = "예", no: str = "아니오") -> bool:
    """예/아니오 확인. 왼쪽이 실행(강조색), 오른쪽이 취소이고 Esc·닫기는 취소로 본다. title 은 호출부 기록용이라 화면에 쓰지 않는다."""
    return _run(parent, text, [(yes, True), (no, False)]) == 0


def notify(parent, text: str, ok: str = "확인") -> None:
    """알림 (버튼 하나)."""
    _run(parent, text, [(ok, True)])
