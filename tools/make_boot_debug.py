"""부팅 스플래시 진단 테마(nformare-debug)에 쓰는 이미지를 만든다 (PC 에서 한 번 실행).

Plymouth 스크립트는 글자를 그릴 수 있는 플러그인이 initramfs 에 없을 수 있어서, 숫자·문구를 모두 미리 그린 PNG 로 만든다.
결과(deploy/plymouth/nformare-debug/): px.png(빨강 한 점), d0~d9.png(숫자), w.png / h.png / n.png(W, H, N 글자),
tl.png(왼쪽 위 표식), br.png(오른쪽 아래 표식), logo.png(가로 로고, 돌리지 않은 것)

    python tools/make_boot_debug.py
"""
import shutil
import sys
from pathlib import Path

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deploy" / "plymouth" / "nformare-debug"


def text_image(text: str, px: int, color: str = "#1F2D27", pad: int = 6, bold: bool = True) -> QImage:
    f = QFont("Arial")
    f.setPixelSize(px)
    f.setBold(bold)
    probe = QImage(1, 1, QImage.Format_ARGB32)
    p = QPainter(probe)
    p.setFont(f)
    w, h = p.fontMetrics().horizontalAdvance(text), p.fontMetrics().height()
    p.end()
    img = QImage(w + 2 * pad, h + 2 * pad, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(QRectF(pad, pad, w, h), Qt.AlignCenter, text)
    p.end()
    return img


def corner_marker(label: str, top_left: bool) -> QImage:
    """모서리를 가리키는 표식: 꺾쇠(┏ 또는 ┛) + 글자. 거꾸로/뒤집힌 것을 한눈에 알 수 있다."""
    txt = text_image(label, 34, "#C73838")
    arm, th = 70, 14
    w, h = max(txt.width(), arm) + 20, txt.height() + arm + 20
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#C73838"))
    if top_left:                              # ┏ 모양: 화면의 왼쪽 위 모서리에 붙는다
        p.drawRect(0, 0, arm, th)
        p.drawRect(0, 0, th, arm)
        p.drawImage(10, arm + 6, txt)
    else:                                     # ┛ 모양: 오른쪽 아래 모서리에 붙는다
        p.drawRect(w - arm, h - th, arm, th)
        p.drawRect(w - th, h - arm, th, arm)
        p.drawImage(w - txt.width() - 10, 4, txt)
    p.end()
    return img


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)   # noqa: F841 (폰트를 쓰려면 필요)
    OUT.mkdir(parents=True, exist_ok=True)
    red = QImage(1, 1, QImage.Format_ARGB32)
    red.fill(QColor("#E03030"))
    red.save(str(OUT / "px.png"))
    for d in range(10):
        text_image(str(d), 64).save(str(OUT / f"d{d}.png"))
    for ch in "WHN":
        text_image(ch + " =", 64, "#2F80ED").save(str(OUT / f"{ch.lower()}.png"))
    corner_marker("TOP-LEFT", True).save(str(OUT / "tl.png"))
    corner_marker("BOTTOM-RIGHT", False).save(str(OUT / "br.png"))
    src = ROOT / "deploy" / "boot_logo_centered.png"
    if src.exists():
        shutil.copyfile(src, OUT / "logo.png")                      # 돌리지 않은 가로 로고: 방향 확인용
    print(f"만들었습니다: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
