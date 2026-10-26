"""부팅 스플래시(Plymouth) 로고 이미지를 만든다: deploy/plymouth/nformare/logo.png

로고(심볼 + 워드마크 + 태그라인)는 로그인 화면의 BrandLockup 과 같은 비율로 그린다. 배경은 투명이고,
배경색(#E9F1ED)과 화면 중앙 배치/축소는 Plymouth 스크립트(nformare.script)가 한다.

    python tools/make_boot_splash.py                       # logo.png + 미리보기(480x800, 1280x800)
    python tools/make_boot_splash.py --rotate 90           # 패널이 세로 기본인데 가로로 쓰며 스플래시가 눕는 경우
    # 직접 만든 로고 이미지(PNG, 투명 배경)를 쓰면서 돌리기 (로고 둘레를 잘라 사방 40px 여백으로 맞춘다):
    python tools/make_boot_splash.py --source deploy/boot_logo.png --rotate 90 --preview-dir deploy/plymouth/preview
    #   --rotate 90: 시계 방향, 270: 반시계 방향. 결과가 거꾸로 보이면 다른 쪽으로 다시 만든다.
"""
import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QTransform
from PyQt5.QtWidgets import QApplication

from ui.theme import ASSETS, load_fonts

BG = QColor("#E9F1ED")          # 페이지 배경색 — nformare.script 의 배경색과 같아야 한다
PAD = 24


def render_logo(scale: float = 6.0) -> QImage:
    """BrandLockup(116x36 기준 좌표)을 scale 배로 투명 배경에 그린다."""
    mark = QImage(str(ASSETS / "mark.png"))
    word = QImage(str(ASSETS / "wordmark.png"))
    w, h = round(116 * scale) + 2 * PAD, round(36 * scale) + 2 * PAD
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)

    def put(src: QImage, x, y, tw, th):
        scaled = src.scaled(round(tw), round(th), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        p.drawImage(QPointF(PAD + x, PAD + y), scaled)

    put(mark, 0, 0, 34.4 * scale, 36 * scale)
    put(word, 36.7 * scale, 4.5 * scale, 78.2 * scale, 17.5 * scale)
    f = QFont("Inter")
    f.setPixelSize(round(5.73 * scale))
    p.setFont(f)
    p.setPen(QColor("#6A7C60"))
    p.drawText(QRectF(PAD + 37.8 * scale, PAD + 24 * scale, 90 * scale, 10 * scale),
               Qt.AlignLeft | Qt.AlignTop, "Biomarker-based Diagnosis")
    p.end()
    return img


def load_source(path: str, pad: int = PAD + 16) -> QImage:
    """직접 만든 로고 PNG 를 읽어, 투명하지 않은 부분만 잘라 사방 같은 여백(pad)을 둔다 (한쪽으로 치우친 여백을 바로잡는다)."""
    img = QImage(path).convertToFormat(QImage.Format_ARGB32)
    if img.isNull():
        raise SystemExit(f"이미지를 읽을 수 없습니다: {path}")
    x0, y0, x1, y1 = img.width(), img.height(), -1, -1
    for y in range(img.height()):
        for x in range(img.width()):
            if (img.pixel(x, y) >> 24) > 8:
                x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
    if x1 < 0:
        raise SystemExit("이미지가 완전히 투명합니다")
    crop = img.copy(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    out = QImage(crop.width() + 2 * pad, crop.height() + 2 * pad, QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.drawImage(pad, pad, crop)
    p.end()
    return out


def rotate(img: QImage, degrees: int) -> QImage:
    return img.transformed(QTransform().rotate(degrees), Qt.SmoothTransformation) if degrees % 360 else img


def preview(logo: QImage, w: int, h: int, panel_rotation: int = 0) -> QImage:
    """nformare.script 와 같은 규칙(세로 화면은 폭의 82%, 가로 화면은 50%, 최대 640px, 중앙)으로 합성한 미리보기."""
    out = QImage(w, h, QImage.Format_ARGB32)
    out.fill(BG)
    target = min(w * (0.82 if w < h else 0.5), 640)
    s = target / logo.width()
    lw, lh = round(logo.width() * s), round(logo.height() * s)
    p = QPainter(out)
    p.setRenderHints(QPainter.SmoothPixmapTransform)
    p.drawImage(QRectF((w - lw) / 2, (h - lh) / 2, lw, lh), logo)
    p.end()
    return out


def preview_native(logo: QImage, native_w: int, native_h: int, rotation: int) -> QImage:
    """패널의 원래 방향(native_w x native_h)에서 nformare.script 규칙으로 합성한 뒤, 사용자가 보는 방향으로 되돌려 보여 준다.

    rotation 은 로고를 돌린 각도다. 세로로 선 로고(rotation 90/270)는 화면의 짧은 변의 82%에 긴 변을 맞춘다."""
    out = QImage(native_w, native_h, QImage.Format_ARGB32)
    out.fill(BG)
    if logo.height() > logo.width():
        long_target = (native_w if native_w < native_h else native_h) * 0.82
        long_side = logo.height()
    else:
        long_target = native_w * (0.82 if native_w < native_h else 0.5)
        long_side = logo.width()
    s = min(long_target, 640) / long_side
    lw, lh = round(logo.width() * s), round(logo.height() * s)
    p = QPainter(out)
    p.setRenderHints(QPainter.SmoothPixmapTransform)
    p.drawImage(QRectF((native_w - lw) / 2, (native_h - lh) / 2, lw, lh), logo)
    p.end()
    return out.transformed(QTransform().rotate(-rotation), Qt.SmoothTransformation) if rotation % 360 else out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(ROOT / "deploy" / "plymouth" / "nformare"))
    ap.add_argument("--scale", type=float, default=6.0, help="로고 해상도 배율 (6 = 약 740px 폭)")
    ap.add_argument("--rotate", type=int, default=0, choices=(0, 90, 180, 270))
    ap.add_argument("--source", help="직접 만든 로고 PNG (투명 배경). 없으면 앱의 BrandLockup 으로 그린다")
    ap.add_argument("--panel", default="800x480", help="회전 로고 미리보기에 쓸 패널의 원래 해상도 (기본 800x480)")
    ap.add_argument("--preview-dir", help="미리보기 PNG 저장 폴더 (없으면 만들지 않음)")
    a = ap.parse_args()
    app = QApplication(sys.argv[:1])      # noqa: F841
    load_fonts()
    base = load_source(a.source) if a.source else render_logo(a.scale)
    logo = rotate(base, a.rotate)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    logo.save(str(out / "logo.png"))
    print("saved", out / "logo.png", logo.width(), "x", logo.height(), f"({(out / 'logo.png').stat().st_size // 1024} KB)")
    if a.preview_dir:
        pd = Path(a.preview_dir)
        pd.mkdir(parents=True, exist_ok=True)
        if a.rotate % 180:                    # 돌린 로고: 패널 원래 방향에서 합성해, 사용자가 보는 방향으로 되돌려 저장
            nw, nh = (int(v) for v in a.panel.lower().split("x"))
            f = pd / f"splash_panel_{nw}x{nh}_rot{a.rotate}.png"
            preview_native(logo, nw, nh, a.rotate).save(str(f))
            print("preview", f, "(사용자가 보는 방향)")
        else:
            for w, h in ((480, 800), (1280, 800)):
                preview(logo, w, h).save(str(pd / f"splash_{w}x{h}.png"))
                print("preview", pd / f"splash_{w}x{h}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
