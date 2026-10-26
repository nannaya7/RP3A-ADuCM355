"""경로 상수, 폰트·스타일시트 로딩."""
from pathlib import Path

from PyQt5.QtGui import QFontDatabase

UI_DIR = Path(__file__).resolve().parent
BASE = UI_DIR.parent
ASSETS = BASE / "assets"


def load_fonts() -> None:
    for ttf in (BASE / "fonts").glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(ttf))


def load_stylesheet() -> str:
    qss = (UI_DIR / "theme.qss").read_text(encoding="utf-8")
    return qss.replace("%CHECK%", (ASSETS / "check.svg").as_posix())
