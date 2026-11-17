"""설정 > 정보: 제품 이름·버전, 펌웨어 버전, 장치 이름, 저작권 안내 (업데이트 기능은 없다)."""
import socket

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from app.version import COPYRIGHT, NOTICE, PRODUCT


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
        self.title = QLabel(PRODUCT, objectName="devTitle")          # "nformare  V.x.xx.xxx"
        col.addWidget(self.title)
        self.firmware = QLabel("펌웨어: 확인 안 됨", objectName="devInfo")
        self.device = QLabel(f"장치 이름: {self._hostname()}", objectName="devInfo")
        col.addWidget(self.firmware)
        col.addWidget(self.device)
        col.addSpacing(8)
        line = QFrame(objectName="hline")
        line.setFixedHeight(1)
        col.addWidget(line)
        col.addSpacing(4)
        for text in (COPYRIGHT, NOTICE):
            lb = QLabel(text, objectName="devInfo", wordWrap=True)
            lb.setTextInteractionFlags(Qt.NoTextInteraction)
            col.addWidget(lb)
        root.addWidget(card)
        root.addStretch(1)

    @staticmethod
    def _hostname() -> str:
        try:
            return socket.gethostname() or "-"
        except OSError:
            return "-"

    # ---- 설정 탭 공통 인터페이스 ----
    def open(self) -> None:
        pass

    def on_keyboard(self, visible: bool) -> None:
        pass

    # ---- 바깥에서 부르는 것 ----
    def set_info(self, version: str) -> None:
        self.title.setText(f"{PRODUCT}  {version}")

    def set_firmware(self, fw: str) -> None:
        self.firmware.setText(f"펌웨어: {fw}" if fw else "펌웨어: 확인 안 됨")
