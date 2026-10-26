"""디스플레이 프로파일(가로 1280x800 / 세로 480x800)과 화면 선택.

- 해상도는 **시작할 때 한 번** 감지한다 (실행 중 회전 없음).
- 회전은 OS(Pi 의 Screen Configuration, wlr-randr 등)가 하고, 앱은 회전된 결과 크기만 보고 방향을 정한다.
- 화면이 여러 개(예: DSI + HDMI)면 `[display] screen` 이름으로 지정하고, 없으면 주 화면을 쓴다.
"""
import logging
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from PyQt5.QtCore import QSize

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DisplayProfile:
    name: str
    size: QSize
    margin: int
    spacing: int
    touch_min: int  # 최소 터치 높이(px)

    @property
    def is_portrait(self) -> bool:
        return self.name == "portrait"


LANDSCAPE = DisplayProfile("landscape", QSize(1280, 800), margin=30, spacing=12, touch_min=56)
PORTRAIT = DisplayProfile("portrait", QSize(480, 800), margin=20, spacing=10, touch_min=56)
PROFILES = {"landscape": LANDSCAPE, "portrait": PORTRAIT}


def orientation_of(size: QSize) -> str:
    """가로가 세로 이상이면 landscape (정사각형은 landscape)."""
    return "landscape" if size.width() >= size.height() else "portrait"


def select_profile(requested: str = "auto", screen_size: Optional[QSize] = None) -> DisplayProfile:
    """프로파일을 고른다.

    requested: "auto" | "landscape" | "portrait"
      auto      → 화면 크기의 방향으로 선택 (크기를 모르면 landscape + 경고)
      그 외 이름 → 그 프로파일 (화면 방향과 다르면 경고만 남기고 그대로 따른다)
    """
    requested = (requested or "auto").strip().lower()
    if requested not in ("auto", *PROFILES):
        log.warning("unknown display profile '%s', using auto", requested)
        requested = "auto"

    if requested == "auto":
        if screen_size is None:
            log.warning("screen size unknown, using landscape")
            return LANDSCAPE
        profile = PROFILES[orientation_of(screen_size)]
        log.info("screen %dx%d -> %s profile selected", screen_size.width(), screen_size.height(), profile.name)
    else:
        profile = PROFILES[requested]
        if screen_size is not None and orientation_of(screen_size) != profile.name:
            log.warning("profile is %s but the screen (%dx%d) is %s orientation; check the OS rotation setting",
                        profile.name, screen_size.width(), screen_size.height(), orientation_of(screen_size))

    if screen_size is not None and (screen_size.width(), screen_size.height()) != \
            (profile.size.width(), profile.size.height()):
        log.warning("screen size %dx%d differs from the standard %dx%d; the layout may be off",
                    screen_size.width(), screen_size.height(), profile.size.width(), profile.size.height())
    return profile


def pick_screen(screens: Sequence, primary, name: str = "") -> Tuple[object, Optional[str]]:
    """사용할 화면을 고른다. (screen, 경고 메시지 또는 None)

    - name 이 있으면 `screen.name()` 이 같은 화면 (없으면 주 화면 + 경고)
    - name 이 없고 화면이 여러 개이면 주 화면 + "여러 화면" 경고 (HDMI 가 함께 연결된 경우 등)
    """
    name = (name or "").strip()
    names = ", ".join(s.name() for s in screens)
    if name:
        for s in screens:
            if s.name() == name:
                return s, None
        return primary, f"screen '{name}' not found, using the primary screen '{primary.name()}' (connected: {names})."
    if len(screens) > 1:
        return primary, (f"{len(screens)} screens connected ({names}), using the primary screen '{primary.name()}'. "
                         "To use another one, set its name in config.ini [display] screen.")
    return primary, None
