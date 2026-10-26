"""로고 PNG 를 시계 방향으로 90 단위로 돌려 저장한다 (install_splash.sh --rotate 가 부른다. Pi 에 설치된 PyQt5 를 쓴다).

    python3 deploy/rotate_logo.py 원본.png 90 결과.png     # 0 / 90 / 180 / 270 (시계 방향)
"""
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QTransform


def main(argv) -> int:
    if len(argv) != 4 or argv[2] not in ("0", "90", "180", "270"):
        print("사용법: rotate_logo.py 원본.png {0|90|180|270} 결과.png", file=sys.stderr)
        return 2
    src, deg, dst = argv[1], int(argv[2]), argv[3]
    img = QImage(src)
    if img.isNull():
        print(f"이미지를 읽을 수 없습니다: {src}", file=sys.stderr)
        return 1
    out = img.transformed(QTransform().rotate(deg), Qt.SmoothTransformation) if deg else img
    if not out.save(dst):
        print(f"저장하지 못했습니다: {dst}", file=sys.stderr)
        return 1
    print(f"{src} → {deg}도(시계 방향) → {dst} ({out.width()}x{out.height()})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
