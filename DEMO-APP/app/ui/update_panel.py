"""설정 > 정보: 앱 버전 (데모 앱은 업데이트 기능이 없다)."""
from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class UpdatePanel(QWidget):
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
        col.addWidget(self.version)
        col.addWidget(QLabel("DEMO — 1 kHz ~ 10 kHz, 10점, 센서 3개", objectName="devInfo"))
        root.addWidget(card)
        root.addStretch(1)

    # ---- 설정 탭 공통 인터페이스 ----
    def open(self) -> None:
        pass

    def on_keyboard(self, visible: bool) -> None:
        pass

    def set_info(self, version: str) -> None:
        self.version.setText(version)
