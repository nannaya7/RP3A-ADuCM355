"""설정 > 정보: 앱 버전과 업데이트. 확인·설치는 요청(신호)만 하고, 실제 일은 UpdateController 가 한다."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.update.controller import AVAILABLE, CHECKING, DOWNLOADING, ERROR, INSTALLED


class UpdatePanel(QWidget):
    checkRequested = pyqtSignal()
    installRequested = pyqtSignal()

    def __init__(self, portrait: bool = False):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10 if portrait else 16)

        card = QFrame(objectName="devDetail")
        col = QVBoxLayout(card)
        col.setContentsMargins(*((18, 16, 18, 16) if portrait else (24, 20, 24, 20)))
        col.setSpacing(6)
        col.addWidget(QLabel("앱 버전", objectName="devTitle"))
        self.version = QLabel("-", objectName="devInfo")
        self.server = QLabel("", objectName="devInfo", wordWrap=True)
        col.addWidget(self.version)
        col.addWidget(self.server)
        root.addWidget(card)

        self.msg = QLabel("", objectName="netMsg", wordWrap=True)
        self.msg.hide()
        root.addWidget(self.msg)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.check_btn = QPushButton("업데이트 확인", objectName="ghostBtn")
        self.install_btn = QPushButton("설치", objectName="primaryBtn")
        for b in (self.check_btn, self.install_btn):
            b.setFocusPolicy(Qt.NoFocus)
            b.setFixedHeight(52 if portrait else 56)
        self.install_btn.hide()
        self.check_btn.clicked.connect(self.checkRequested)
        self.install_btn.clicked.connect(self.installRequested)
        row.addWidget(self.check_btn, 1)
        row.addWidget(self.install_btn, 1)
        root.addLayout(row)
        root.addStretch(1)

    # ---- 설정 탭 공통 인터페이스 ----
    def open(self) -> None:
        pass

    def on_keyboard(self, visible: bool) -> None:
        pass

    # ---- 바깥에서 부르는 것 ----
    def set_info(self, version: str, server: str) -> None:
        self.version.setText(version)
        self.server.setText(f"업데이트 서버: {server}" if server else "업데이트 서버가 설정되어 있지 않습니다.")

    def set_state(self, state: str, text: str) -> None:
        self.msg.setText(text)
        self.msg.setVisible(bool(text))
        self.msg.setProperty("level", "error" if state == ERROR else "ok")
        self.msg.style().unpolish(self.msg)
        self.msg.style().polish(self.msg)
        busy = state in (CHECKING, DOWNLOADING, INSTALLED)
        self.check_btn.setEnabled(not busy)
        self.install_btn.setVisible(state == AVAILABLE)
        self.install_btn.setEnabled(state == AVAILABLE)
