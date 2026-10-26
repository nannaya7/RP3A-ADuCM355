"""장비 상태 아이콘: icon/ 의 PNG 를 상태 색 한 가지로 칠해 그린다."""
import pytest
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QApplication

import ui.dashboard_widgets as dw
from ui.dashboard_widgets import ICON_DIR, ICON_FILES, StatusIcon, tinted_icon


@pytest.mark.parametrize("kind", ["power", "strip", "wifi"])
def test_icon_files_exist(kind):
    assert (ICON_DIR / ICON_FILES[kind]).is_file()           # Pi 에 icon/ 폴더도 올려야 한다


@pytest.mark.parametrize("kind", ["power", "strip", "wifi"])
@pytest.mark.parametrize("state", ["ok", "warn", "bad"])
def test_icon_is_a_single_color_matching_the_state(kind, state):
    fg = StatusIcon.COLORS[state][1]
    img = tinted_icon(kind, 64, fg).toImage()
    want = QColor(fg)
    seen = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 40:                                # 거의 투명한 가장자리는 제외
                seen += 1
                assert abs(c.red() - want.red()) <= 3 and abs(c.green() - want.green()) <= 3 \
                    and abs(c.blue() - want.blue()) <= 3, (kind, state, c.name())
    assert seen > 100                                         # 실제로 그려졌다


def test_kit_icon_keeps_a_lighter_fill_but_the_same_color():
    """시험관 안 채움은 같은 색의 연한 농도(투명도)로 — 윤곽선이 진하고 채움이 옅다."""
    img = tinted_icon("strip", 128, "#1FA37A").toImage()
    alphas = {img.pixelColor(x, y).alpha() for y in range(128) for x in range(128)}
    assert max(alphas) > 230 and any(60 < a < 140 for a in alphas)


def test_missing_icon_file_falls_back_to_drawn_icon(monkeypatch, tmp_path):
    monkeypatch.setattr(dw, "ICON_DIR", tmp_path)             # 파일이 없는 폴더
    dw._ICON_CACHE.clear()
    try:
        assert tinted_icon("power", 40, "#1FA37A") is None
        w = StatusIcon("power", 40)
        w.show()
        QApplication.processEvents()
        img = w.grab().toImage()                              # 대체 그리기로도 죽지 않고 그려진다
        assert any(img.pixelColor(x, y).alpha() > 0 for x in range(0, 40, 4) for y in range(0, 40, 4))
    finally:
        dw._ICON_CACHE.clear()
