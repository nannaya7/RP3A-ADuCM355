import logging

import pytest
from PyQt5.QtCore import QSize

from app import display as d


class FakeScreen:
    def __init__(self, name):
        self._n = name

    def name(self):
        return self._n


@pytest.mark.parametrize("w,h,expected", [
    (1280, 800, "landscape"), (480, 800, "portrait"), (800, 1280, "portrait"),
    (1920, 1080, "landscape"), (1024, 1024, "landscape"), (800, 480, "landscape"),
])
def test_auto_selects_by_orientation(w, h, expected):
    assert d.select_profile("auto", QSize(w, h)).name == expected


def test_auto_without_size_falls_back_to_landscape(caplog):
    with caplog.at_level(logging.WARNING):
        assert d.select_profile("auto", None) is d.LANDSCAPE
    assert "unknown" in caplog.text


def test_explicit_profile_is_followed_even_if_screen_disagrees(caplog):
    with caplog.at_level(logging.WARNING):
        p = d.select_profile("portrait", QSize(1280, 800))
    assert p is d.PORTRAIT and "orientation" in caplog.text


def test_unknown_name_is_treated_as_auto():
    assert d.select_profile("sideways", QSize(480, 800)) is d.PORTRAIT
    assert d.select_profile("", QSize(1280, 800)) is d.LANDSCAPE


def test_non_standard_resolution_warns_but_works(caplog):
    with caplog.at_level(logging.WARNING):
        p = d.select_profile("auto", QSize(1024, 600))
    assert p is d.LANDSCAPE and "standard" in caplog.text


def test_standard_resolution_has_no_warning(caplog):
    with caplog.at_level(logging.WARNING):
        d.select_profile("auto", QSize(480, 800))
    assert caplog.text == ""


def test_profile_sizes():
    assert (d.PORTRAIT.size.width(), d.PORTRAIT.size.height()) == (480, 800) and d.PORTRAIT.is_portrait
    assert (d.LANDSCAPE.size.width(), d.LANDSCAPE.size.height()) == (1280, 800) and not d.LANDSCAPE.is_portrait


def test_pick_screen():
    hdmi, dsi = FakeScreen("HDMI-A-1"), FakeScreen("DSI-1")
    s, warn = d.pick_screen([hdmi, dsi], hdmi, "")
    assert s is hdmi and "2 screens" in warn and "[display] screen" in warn          # 여러 화면 → 주 화면 + 경고
    s, warn = d.pick_screen([hdmi, dsi], hdmi, "DSI-1")
    assert s is dsi and warn is None                                  # 이름 지정
    s, warn = d.pick_screen([hdmi, dsi], hdmi, "DSI-9")
    assert s is hdmi and "not found" in warn and "DSI-1" in warn      # 없는 이름 → 주 화면 + 경고
    s, warn = d.pick_screen([dsi], dsi, "")
    assert s is dsi and warn is None                                  # 화면 1개 → 조용히
