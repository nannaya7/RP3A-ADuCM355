"""장비 상태 아이콘의 단색 마스크를 만든다 (PC 에서 한 번 실행, 결과 PNG 를 icon/ 에 둔다).

앱은 icon/ 의 PNG 를 '투명도 마스크'로만 쓰고 색은 상태(정상/주의/문제)에 따라 입힌다.
power.png / wifi.png 는 이미 검정 단색이라 그대로 쓴다. kit_check.png 는 파랑 윤곽선 + 분홍 채움 + 빨강 물방울의
다색 그림이라 단색 마스크(kit_check_mono.png)로 바꾼다: 윤곽선과 물방울은 진하게, 시험관 안의 채움은 같은 색의 연한 농도로.

    python tools/make_status_icons.py            # icon/kit_check_mono.png 를 만든다
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ICON_DIR = Path(__file__).resolve().parent.parent / "app" / "icon"
FILL_WEIGHT = 0.30      # 시험관 안 채움의 농도 (0~1). 윤곽선·물방울은 1.0


def to_mono(src: Path, dst: Path) -> None:
    rgba = np.array(Image.open(src).convert("RGBA")).astype(int)
    r, g, b, a = rgba[..., 0], rgba[..., 1], rgba[..., 2], rgba[..., 3]
    drop = (r > 200) & (g < 120)                                   # 빨간 물방울
    fill = (r > b + 40) & (r > g + 40) & ~drop                     # 분홍 채움 (윤곽선과 섞인 가장자리 포함)
    weight = np.where(fill, FILL_WEIGHT, 1.0)
    whiteness = np.minimum(np.minimum(r, g), b) / 255.0            # 시험관의 빈 부분(불투명한 흰색)은 투명으로: 흰색에 가까울수록 옅게
    weight = weight * np.clip(1.0 - (whiteness - 0.6) / 0.4, 0.0, 1.0)
    out = np.zeros_like(rgba)
    out[..., 3] = np.clip(a * weight, 0, 255).astype(np.uint8)     # 색은 검정, 농도만 투명도로
    img = Image.fromarray(out.astype(np.uint8), "RGBA")
    box = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()      # 바깥 여백을 잘라 다른 아이콘과 크기를 맞춘다
    if box:
        img = img.crop(box)
        side = max(img.size)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
        img = square
    img.save(dst)


def main() -> int:
    src = ICON_DIR / "kit_check.png"
    if not src.exists():
        print(f"없음: {src}")
        return 1
    dst = ICON_DIR / "kit_check_mono.png"
    to_mono(src, dst)
    print(f"만들었습니다: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
