"""시작 화면: 무거운 모듈을 불러오고 화면을 만드는 동안 먼저 띄우는 가벼운 창 (PyQt 만 사용)."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt5.QtWidgets import QWidget

from .theme import ASSETS

BG = QColor("#E9F1ED")                  # 로그인/기본 페이지 배경과 같은 색


class StartupSplash(QWidget):
    def __init__(self, size, fullscreen: bool, screen=None):
        super().__init__()
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._logo = QPixmap(str(ASSETS / "wordmark.png"))
        if screen is not None:
            self.move(screen.geometry().topLeft())
        if fullscreen:
            self.showFullScreen()
        else:
            self.setFixedSize(size)
            self.show()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), BG)
        cy = self.height() * 0.45
        if not self._logo.isNull():
            logo = self._logo.scaledToWidth(int(min(self.width() * 0.5, 360)), Qt.SmoothTransformation)
            p.drawPixmap(int((self.width() - logo.width()) / 2), int(cy - logo.height() / 2), logo)
            cy += logo.height() / 2
        f = QFont("Pretendard")
        f.setPixelSize(16)
        p.setFont(f)
        p.setPen(QColor("#5B6B64"))
        p.drawText(0, int(cy + 24), self.width(), 28, Qt.AlignCenter, "시작하는 중…")
