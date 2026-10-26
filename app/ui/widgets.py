"""로그인 화면에서 쓰는 재사용 위젯: BrandLockup, RoleTabs, Field."""
from PyQt5.QtCore import Qt, QPointF, QRectF, QSize, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPalette, QPixmap
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QToolButton, QVBoxLayout, QWidget

from .theme import ASSETS


class BrandLockup(QWidget):
    """심볼 + 워드마크 + 태그라인. 웹 BrandLockup 의 116x36 기준 좌표를 scale 배.

    비트맵을 화면 실제 픽셀(DPR 반영) 크기로 한 번만 고품질 축소해 캐시한다 —
    paintEvent 에서 매번 큰 원본을 줄여 그리면 흐릿하고 거칠다.
    """

    def __init__(self, scale: float = 1.4, parent=None):
        super().__init__(parent)
        self._s = scale
        self._mark = QImage(str(ASSETS / "mark.png"))
        self._word = QImage(str(ASSETS / "wordmark.png"))
        self._cache = None
        self._cache_dpr = 0.0
        self.setFixedSize(round(116 * scale), round(36 * scale))

    def _render(self, dpr: float) -> QPixmap:
        s = self._s
        out = QPixmap(round(self.width() * dpr), round(self.height() * dpr))
        out.fill(Qt.transparent)
        out.setDevicePixelRatio(dpr)
        p = QPainter(out)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)

        def put(img: QImage, x, y, w, h):
            scaled = img.scaled(round(w * dpr), round(h * dpr), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            p.drawImage(QPointF(round(x * dpr) / dpr, round(y * dpr) / dpr), scaled)

        put(self._mark, 0, 0, 34.4 * s, 36 * s)
        put(self._word, 36.7 * s, 4.5 * s, 78.2 * s, 17.5 * s)
        f = QFont("Inter")
        f.setPixelSize(round(5.73 * s))
        p.setFont(f)
        p.setPen(QColor("#6A7C60"))
        p.drawText(QRectF(37.8 * s, 24 * s, 90 * s, 10 * s), Qt.AlignLeft | Qt.AlignTop,
                   "Biomarker-based Diagnosis")
        p.end()
        return out

    def paintEvent(self, _):
        dpr = self.devicePixelRatioF()
        if self._cache is None or dpr != self._cache_dpr:
            self._cache, self._cache_dpr = self._render(dpr), dpr
        QPainter(self).drawPixmap(0, 0, self._cache)


class RoleTabs(QWidget):
    """역할 세그먼트 — 트랙 440x42 r12 패딩 6, 선택 탭 r7 흰색. 직접 그려 플랫폼 차이를 없앤다."""

    changed = pyqtSignal(str)

    def __init__(self, tabs, parent=None, height: int = 42, font_px: int = 12, track: str = "#E9F1ED"):
        super().__init__(parent)
        self._tabs = tabs
        self._index = 0
        self._hover = -1
        self._font_px = font_px
        self._track = QColor(track)
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def current_key(self) -> str:
        return self._tabs[self._index][0]

    def _seg(self, i: int) -> QRectF:
        w = (self.width() - 12) / len(self._tabs)
        return QRectF(6 + w * i, 6, w, self.height() - 12)

    def _at(self, x: float) -> int:
        for i in range(len(self._tabs)):
            if self._seg(i).left() <= x < self._seg(i).right():
                return i
        return -1

    def mouseMoveEvent(self, e):
        self._hover = self._at(e.x())
        self.update()

    def leaveEvent(self, _):
        self._hover = -1
        self.update()

    def mousePressEvent(self, e):
        i = self._at(e.x())
        if i >= 0 and i != self._index:
            self._index = i
            self.changed.emit(self.current_key())
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        track = QPainterPath()
        track.addRoundedRect(QRectF(self.rect()), 12, 12)
        p.fillPath(track, self._track)
        for i, (_, label) in enumerate(self._tabs):
            r = self._seg(i)
            sel = i == self._index
            if sel:
                pill = QPainterPath()
                pill.addRoundedRect(r, 7, 7)
                p.fillPath(pill, QColor("#FFFFFF"))
            f = QFont("Pretendard")
            f.setPixelSize(self._font_px)
            f.setWeight(QFont.DemiBold if sel else QFont.Normal)
            p.setFont(f)
            p.setPen(QColor("#0C8444" if (i == self._hover and not sel) else "#424242"))
            p.drawText(r, Qt.AlignCenter, label)


class Field(QWidget):
    """라벨 없는 입력 필드 + 에러 문구. 필드 높이 44, 좌측 패딩 15."""

    def __init__(self, placeholder: str, password: bool = False, parent=None, height: int = 44, large: bool = False):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self.frame = QFrame(objectName="field")
        self.frame.setFixedHeight(height)
        if large:                       # 세로(터치) 화면: 흰 배경·큰 글자 (theme.qss 의 [touch="true"]). 'size' 는 QWidget 기본 속성이라 쓰지 않는다
            self.frame.setProperty("touch", True)
        row = QHBoxLayout(self.frame)
        row.setContentsMargins(15, 0, 12, 0)
        row.setSpacing(8)

        self.edit = QLineEdit(placeholderText=placeholder)
        pal = self.edit.palette()
        pal.setColor(QPalette.PlaceholderText, QColor("#68AF98"))
        self.edit.setPalette(pal)
        row.addWidget(self.edit, 1)

        self.toggle = None
        if password:
            self.edit.setEchoMode(QLineEdit.Password)
            self.toggle = QToolButton(cursor=Qt.PointingHandCursor)
            self.toggle.setIconSize(QSize(16, 16))
            self.toggle.setIcon(QIcon(str(ASSETS / "eye.svg")))
            self.toggle.setToolTip("비밀번호 보기")
            self.toggle.setCheckable(True)
            self.toggle.toggled.connect(self._on_toggle)
            row.addWidget(self.toggle)

        self.error = QLabel(objectName="errorText")
        self.error.setContentsMargins(4, 0, 0, 0)
        self.error.hide()

        outer.addWidget(self.frame)
        outer.addWidget(self.error)

    def text(self) -> str:
        return self.edit.text()

    def set_error(self, message: str = "") -> None:
        self.error.setText(message)
        self.error.setVisible(bool(message))
        self._set_prop("error", bool(message))

    def _on_toggle(self, shown: bool):
        self.edit.setEchoMode(QLineEdit.Normal if shown else QLineEdit.Password)
        self.toggle.setIcon(QIcon(str(ASSETS / ("eye-off.svg" if shown else "eye.svg"))))
        self.toggle.setToolTip("비밀번호 숨기기" if shown else "비밀번호 보기")

    def _set_prop(self, name: str, value: bool):
        self.frame.setProperty(name, value)
        self.frame.style().unpolish(self.frame)
        self.frame.style().polish(self.frame)
