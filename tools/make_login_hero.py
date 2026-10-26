"""세로 로그인 화면 위쪽 빈 공간에 넣을 일러스트(assets/login-hero-portrait.png)를 그린다.

PyQt5 의 QPainter 만 사용한다 (추가 패키지 없음). 배경은 투명이라 페이지 배경(#E9F1ED) 위에 그대로 얹을 수 있다.
    python tools/make_login_hero.py            # assets/login-hero-portrait.png (960x840 = 480x420 @2x)
    python tools/make_login_hero.py --preview 시안.png   # 시안 위쪽에 얹은 미리보기도 저장
"""
import argparse
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                         QRadialGradient, QTransform)
from PyQt5.QtWidgets import QApplication

W, H = 960, 840                      # 2x (논리 크기 480x420)
GREEN = QColor("#2FAF87")
DEEP = QColor("#0C8444")
MINT = QColor("#D3EADF")
MINT2 = QColor("#BFE3D1")
INK = QColor("#2B3A34")
CORAL = QColor("#EE7B72")


def rgba(c: QColor, a: int) -> QColor:
    return QColor(c.red(), c.green(), c.blue(), a)


def blob(p: QPainter, cx, cy, r, color, alpha=170):
    g = QRadialGradient(QPointF(cx, cy), r)
    g.setColorAt(0.0, rgba(color, alpha))
    g.setColorAt(0.7, rgba(color, int(alpha * 0.55)))
    g.setColorAt(1.0, rgba(color, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(g))
    p.drawEllipse(QPointF(cx, cy), r, r)


def leaf(p: QPainter, x, y, size, angle, color, alpha=230):
    path = QPainterPath()
    path.moveTo(0, 0)
    path.quadTo(size * 0.55, -size * 0.15, size, -size * 0.55)
    path.quadTo(size * 0.35, -size * 0.75, 0, 0)
    t = QTransform().translate(x, y).rotate(angle)
    p.setPen(Qt.NoPen)
    p.setBrush(rgba(color, alpha))
    p.drawPath(t.map(path))
    p.setPen(QPen(rgba(QColor("white"), 160), 2.2, cap=Qt.RoundCap))
    vein = QPainterPath()
    vein.moveTo(0, 0)
    vein.quadTo(size * 0.45, -size * 0.28, size * 0.88, -size * 0.52)
    p.drawPath(t.map(vein))


def plus(p: QPainter, x, y, s, color, alpha=200, w=7):
    p.setPen(QPen(rgba(color, alpha), w, cap=Qt.RoundCap))
    p.drawLine(QPointF(x - s, y), QPointF(x + s, y))
    p.drawLine(QPointF(x, y - s), QPointF(x, y + s))


def droplet(p: QPainter, x, y, s, color):
    path = QPainterPath()
    path.moveTo(x, y - s * 1.25)
    path.cubicTo(x + s * 0.2, y - s * 0.7, x + s * 0.95, y - s * 0.1, x + s * 0.95, y + s * 0.38)
    path.arcTo(QRectF(x - s * 0.95, y - s * 0.57, s * 1.9, s * 1.9), 0, -180)
    path.cubicTo(x - s * 0.95, y - s * 0.1, x - s * 0.2, y - s * 0.7, x, y - s * 1.25)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPath(path)
    p.setBrush(QColor(255, 255, 255, 120))
    p.drawEllipse(QPointF(x - s * 0.35, y + s * 0.15), s * 0.16, s * 0.28)


def shadow_rect(p: QPainter, rect: QRectF, radius, layers=14, spread=2.2, alpha=9):
    p.setPen(Qt.NoPen)
    for i in range(layers, 0, -1):
        grow = i * spread
        p.setBrush(QColor(20, 70, 50, alpha))
        p.drawRoundedRect(rect.adjusted(-grow, -grow * 0.6 + 14, grow, grow * 1.4 + 14), radius + grow, radius + grow)


def draw_hero() -> QImage:
    img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

    # 1) 부드러운 배경 덩어리
    blob(p, 480, 430, 400, QColor("white"), 215)
    blob(p, 250, 250, 250, MINT2, 150)
    blob(p, 730, 560, 270, MINT, 190)
    blob(p, 560, 170, 170, QColor("#C9EBDD"), 120)

    # 2) 임피던스(Nyquist) 반원 호와 측정 주파수 점
    cx, cy = 480, 585
    for r, a, w in ((385, 70, 5), (300, 110, 6)):
        p.setPen(QPen(rgba(GREEN, a), w, cap=Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), 8 * 16, 164 * 16)
    for i in range(13):
        ang = math.radians(8 + i * (164 / 12))
        r = 385
        x, y = cx + r * math.cos(ang), cy - r * math.sin(ang)
        size = 9 + 6 * math.sin(i / 12 * math.pi)
        p.setPen(QPen(rgba(GREEN, 230), 4))
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(x, y), size, size)
    for i in range(7):
        ang = math.radians(14 + i * (152 / 6))
        r = 300
        x, y = cx + r * math.cos(ang), cy - r * math.sin(ang)
        p.setPen(Qt.NoPen)
        p.setBrush(rgba(DEEP, 200))
        p.drawEllipse(QPointF(x, y), 7, 7)

    # 3) 심전도(펄스) 선 — 키트 뒤에서 좌우로 지나감
    ecg = QPainterPath()
    ecg.moveTo(40, 640)
    ecg.lineTo(250, 640)
    ecg.lineTo(292, 640)
    ecg.lineTo(318, 600)
    ecg.lineTo(348, 668)
    ecg.lineTo(368, 640)
    ecg.lineTo(592, 640)
    ecg.lineTo(628, 640)
    ecg.lineTo(650, 566)
    ecg.lineTo(684, 724)
    ecg.lineTo(708, 640)
    ecg.lineTo(920, 640)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(rgba(GREEN, 55), 18, cap=Qt.RoundCap, join=Qt.RoundJoin))
    p.drawPath(ecg)
    p.setPen(QPen(GREEN, 7, cap=Qt.RoundCap, join=Qt.RoundJoin))
    p.drawPath(ecg)

    # 4) 진단키트: 센서 3개 어레이
    p.save()
    p.translate(480, 395)
    p.rotate(-7)
    kit = QRectF(-150, -235, 300, 470)
    shadow_rect(p, kit, 44)
    body = QLinearGradient(0, kit.top(), 0, kit.bottom())
    body.setColorAt(0, QColor("#FFFFFF"))
    body.setColorAt(1, QColor("#F1F8F4"))
    p.setPen(QPen(QColor("#D4E6DD"), 3))
    p.setBrush(QBrush(body))
    p.drawRoundedRect(kit, 44, 44)

    # 윗부분 라벨 영역 + 리브
    p.setPen(Qt.NoPen)
    p.setBrush(MINT)
    p.drawRoundedRect(QRectF(-100, -200, 200, 34), 17, 17)
    p.setBrush(rgba(GREEN, 200))
    p.drawRoundedRect(QRectF(-100, -200, 78, 34), 17, 17)
    p.setBrush(rgba(DEEP, 140))
    for i in range(3):
        p.drawEllipse(QPointF(50 + i * 22, -183), 5, 5)

    # 센서 3개
    for i, cyy in enumerate((-95, 10, 115)):
        p.setPen(QPen(rgba(GREEN, 70), 12))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, cyy), 41, 41)
        p.setPen(QPen(GREEN, 6))
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(0, cyy), 35, 35)
        g = QRadialGradient(QPointF(-8, cyy - 8), 32)
        g.setColorAt(0, QColor("#6FD3B0"))
        g.setColorAt(1, GREEN)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(0, cyy), 21, 21)
        p.setPen(QPen(rgba(GREEN, 150), 5, cap=Qt.RoundCap))
        p.drawLine(QPointF(60, cyy), QPointF(116, cyy))      # 전극 배선
        p.setPen(QPen(rgba(GREEN, 150), 5, cap=Qt.RoundCap))
        p.drawLine(QPointF(-60, cyy), QPointF(-116, cyy))
    # 아래 접점
    p.setPen(Qt.NoPen)
    for i in range(3):
        p.setBrush(rgba(DEEP, 170))
        p.drawRoundedRect(QRectF(-72 + i * 52, 188, 40, 28), 8, 8)
    p.restore()

    # 5) 혈액 방울, 잎, 십자 표시
    droplet(p, 760, 215, 40, CORAL)
    droplet(p, 818, 300, 20, rgba(CORAL, 200))
    leaf(p, 170, 140, 120, -35, rgba(GREEN, 255), 235)
    leaf(p, 150, 182, 82, -8, QColor("#7FCCAE"), 235)
    plus(p, 215, 400, 22, DEEP, 150)
    plus(p, 770, 450, 18, GREEN, 190, 6)
    plus(p, 700, 100, 14, DEEP, 130, 5)
    p.setPen(Qt.NoPen)
    for x, y, r in ((95, 330, 9), (870, 380, 8), (330, 70, 7), (600, 40, 6), (115, 560, 7)):
        p.setBrush(rgba(GREEN, 120))
        p.drawEllipse(QPointF(x, y), r, r)
    p.end()
    return img


def make_preview(hero: QImage, mock_path: Path, out: Path) -> None:
    """시안(390x844)의 위쪽 빈 공간에 히어로를 얹은 미리보기를 만든다."""
    mock = QImage(str(mock_path)).convertToFormat(QImage.Format_ARGB32_Premultiplied)
    p = QPainter(mock)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    target_w = mock.width()
    target_h = int(hero.height() * target_w / hero.width())
    top = max(0, 352 - target_h + 24)       # 헤드라인 문구(y≈370) 바로 위까지
    p.drawImage(QRectF(0, top, target_w, target_h), hero)
    p.end()
    mock.save(str(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "assets" / "login-hero-portrait.png"))
    ap.add_argument("--preview", help="시안 이미지 경로 (있으면 미리보기 PNG 도 저장)")
    ap.add_argument("--preview-out", default=None)
    a = ap.parse_args()
    app = QApplication(sys.argv[:1])      # noqa: F841 (QPainter 에 필요)
    hero = draw_hero()
    hero.save(a.out)
    print("saved", a.out, hero.width(), "x", hero.height())
    if a.preview:
        out = Path(a.preview_out) if a.preview_out else Path(a.out).with_name("login-hero-portrait-preview.png")
        make_preview(hero, Path(a.preview), out)
        print("preview", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
