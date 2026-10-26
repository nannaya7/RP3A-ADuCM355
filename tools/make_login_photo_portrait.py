"""가로 로그인 사진(assets/login-bg.jpg)을 세로 로그인 위쪽 영역용으로 만든다.

    python tools/make_login_photo_portrait.py                 # B: 가운데 크롭(480x420 @2x) → assets/login-hero-photo.png
    python tools/make_login_photo_portrait.py --mode full     # A: 사진 전체를 폭에 맞춰 축소
    python tools/make_login_photo_portrait.py --preview 시안.png --preview-out 미리보기.png

아래쪽은 투명하게 서서히 사라지게(페이드) 해서 페이지 배경(#E9F1ED)과 자연스럽게 이어진다.
"""
import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QImage, QLinearGradient, QPainter
from PyQt5.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app" / "assets" / "login-bg.jpg"
OUT_W = 960                      # 논리 480px @2x


def build(mode: str, crop_x: int, fade: float) -> QImage:
    src = QImage(str(SRC)).convertToFormat(QImage.Format_ARGB32_Premultiplied)
    if mode == "full":                          # 전체를 폭에 맞춰 축소
        crop = QRectF(0, 0, src.width(), src.height())
    else:                                       # 두 사람과 장비 중심 가운데 크롭 (480:420 비율)
        h = src.height()
        w = h * 960 / 840
        crop = QRectF(crop_x, 0, w, h)
    out_h = round(OUT_W * crop.height() / crop.width())
    img = QImage(OUT_W, out_h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    p.drawImage(QRectF(0, 0, OUT_W, out_h), src, crop)
    # 아래쪽 페이드: 알파를 1 → 0 으로
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    g = QLinearGradient(0, out_h * (1 - fade), 0, out_h)
    g.setColorAt(0, QColor(0, 0, 0, 255))
    g.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(QRectF(0, 0, OUT_W, out_h), g)
    p.end()
    return img


def preview(hero: QImage, mock: Path, out: Path, anchor: str) -> None:
    m = QImage(str(mock)).convertToFormat(QImage.Format_ARGB32_Premultiplied)
    p = QPainter(m)
    p.setRenderHints(QPainter.SmoothPixmapTransform)
    w = m.width()
    h = hero.height() * w / hero.width()
    y = 0 if anchor == "top" else max(0.0, 352 - h + 24)
    p.drawImage(QRectF(0, y, w, h), hero)
    p.end()
    m.save(str(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("crop", "full"), default="crop")
    ap.add_argument("--crop-x", type=int, default=130, help="crop 모드에서 원본 x 시작점(px)")
    ap.add_argument("--fade", type=float, default=0.32, help="아래쪽 페이드 비율(0~1)")
    ap.add_argument("--out", default=str(ROOT / "app" / "assets" / "login-hero-photo.png"))
    ap.add_argument("--preview")
    ap.add_argument("--preview-out")
    ap.add_argument("--anchor", choices=("top", "text"), default="top", help="미리보기에서 위쪽 정렬 / 문구 바로 위 정렬")
    a = ap.parse_args()
    app = QApplication(sys.argv[:1])      # noqa: F841
    hero = build(a.mode, a.crop_x, a.fade)
    hero.save(a.out)
    print("saved", a.out, hero.width(), "x", hero.height(), f"({os.path.getsize(a.out) // 1024} KB)")
    if a.preview:
        out = Path(a.preview_out) if a.preview_out else Path(a.out).with_name(Path(a.out).stem + "-preview.png")
        preview(hero, Path(a.preview), out, a.anchor)
        print("preview", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
