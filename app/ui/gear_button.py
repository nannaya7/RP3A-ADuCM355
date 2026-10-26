"""우측 상단 설정(톱니바퀴) 버튼. 아이콘 파일 없이 직접 그린다 (SVG 플러그인 유무와 무관)."""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QTransform
from PyQt5.QtWidgets import QAbstractButton, QSizePolicy


def gear_path(cx: float, cy: float, r_out: float, teeth: int = 8) -> QPainterPath:
    """톱니 8개 + 가운데 구멍인 톱니바퀴 경로."""
    body_r = r_out * 0.78
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), body_r, body_r)
    tw, th = r_out * 0.36, r_out - body_r + 1.0
    for i in range(teeth):
        tooth = QPainterPath()
        tooth.addRoundedRect(QRectF(-tw / 2, -r_out, tw, th + 1.5), tw * 0.18, tw * 0.18)
        tr = QTransform().translate(cx, cy).rotate(360.0 / teeth * i)
        path = path.united(tr.map(tooth))
    hole = QPainterPath()
    hole.addEllipse(QPointF(cx, cy), r_out * 0.32, r_out * 0.32)
    return path.subtracted(hole)


class GearButton(QAbstractButton):
    def __init__(self, parent=None, size: int = 48):
        super().__init__(parent)
        self.setObjectName("gearBtn")
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)               # 입력란의 포커스(터치 키보드)를 빼앗지 않는다
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setToolTip("설정")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        w = self.width()
        rect = QRectF(0.5, 0.5, w - 1, w - 1)
        p.setBrush(QColor(233, 241, 237, 235) if self.isDown() else QColor(255, 255, 255, 215))
        p.setPen(QPen(QColor("#C9D8D1"), 1))
        p.drawEllipse(rect)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2B2B2B" if self.isDown() else "#424242"))
        p.drawPath(gear_path(w / 2, w / 2, w * 0.30))
