"""가로 측정 화면(대시보드)에서 쓰는 작은 위젯: 단계 삽화, 단계 카드, 만성질환 선택, 이력 표."""
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import QPointF, QRectF, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QMenu, QProgressBar,
                             QPushButton, QScroller, QSizePolicy, QTableWidget, QTableWidgetItem, QToolButton,
                             QVBoxLayout, QWidget)

from measure.history import HistoryItem, format_value

BLUE, BLUE_DARK, GREEN = "#2F80ED", "#1E63C9", "#2FAF87"


def _set_prop(w: QWidget, name: str, value) -> None:
    w.setProperty(name, value)
    w.style().unpolish(w)
    w.style().polish(w)


class StepIllustration(QWidget):
    """단계 삽화 (직접 그림): 0 = 시료 튜브, 1 = 혈액 투입(스트립 + 핏방울), 2 = 카세트. 완료되면 오른쪽 아래에 체크 표시."""

    def __init__(self, kind: int, size: int = 96, parent=None):
        super().__init__(parent)
        self.kind, self.done, self.dim = kind, False, False
        self.setFixedSize(size, size)

    def set_state(self, done: bool, dim: bool) -> None:
        if (done, dim) != (self.done, self.dim):
            self.done, self.dim = done, dim
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        if self.dim:
            p.setOpacity(0.55)
        s = self.width()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#E6F0FB"))
        p.drawEllipse(QRectF(0, 0, s, s))
        c = s / 2
        if self.kind == 0:
            self._tube(p, c, s)
        elif self.kind == 1:
            self._strip(p, c, s)
        else:
            self._cassette(p, c, s)
        if self.done:
            r = s * 0.17
            cx, cy = s * 0.80, s * 0.80
            p.setOpacity(1.0)
            p.setBrush(QColor("#3BB58A"))
            p.setPen(QPen(QColor("#FFFFFF"), 2))
            p.drawEllipse(QPointF(cx, cy), r, r)
            p.setPen(QPen(QColor("#FFFFFF"), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline(QPointF(cx - r * 0.45, cy), QPointF(cx - r * 0.1, cy + r * 0.38), QPointF(cx + r * 0.5, cy - r * 0.32))

    @staticmethod
    def _tube(p, c, s):
        w, h = s * 0.26, s * 0.62
        body = QRectF(c - w / 2, s * 0.22, w, h)
        p.setBrush(QColor("#FFFFFF"))
        p.setPen(QPen(QColor("#9CB7DA"), 1.6))
        path = QPainterPath()
        path.addRoundedRect(body, w * 0.4, w * 0.4)
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(BLUE))
        p.drawRoundedRect(QRectF(c - w * 0.58, s * 0.16, w * 1.16, s * 0.15), 4, 4)
        p.setPen(QPen(QColor("#6C7F96"), 1.4))
        for i in range(6):                       # 바코드 표시
            y = s * 0.42 + i * s * 0.05
            p.drawLine(QPointF(c - w * 0.3, y), QPointF(c + w * 0.3, y))

    @staticmethod
    def _strip(p, c, s):
        p.setBrush(QColor("#C95757"))
        drop = QPainterPath()
        drop.moveTo(c, s * 0.14)
        drop.cubicTo(c + s * 0.10, s * 0.27, c + s * 0.09, s * 0.36, c, s * 0.37)
        drop.cubicTo(c - s * 0.09, s * 0.36, c - s * 0.10, s * 0.27, c, s * 0.14)
        p.drawPath(drop)
        p.setBrush(QColor("#9DA9B8"))
        p.drawRoundedRect(QRectF(s * 0.18, s * 0.46, s * 0.64, s * 0.24), 6, 6)
        p.setBrush(QColor("#E8EDF3"))
        p.drawRoundedRect(QRectF(s * 0.24, s * 0.52, s * 0.52, s * 0.12), 4, 4)
        p.setBrush(QColor("#7C8AA0"))
        p.drawRoundedRect(QRectF(c - s * 0.07, s * 0.535, s * 0.14, s * 0.09), 3, 3)

    @staticmethod
    def _cassette(p, c, s):
        p.save()
        p.translate(c, c)
        p.rotate(-18)
        p.setBrush(QColor("#F4F6F9"))
        p.setPen(QPen(QColor("#B6C2D2"), 1.6))
        p.drawRoundedRect(QRectF(-s * 0.34, -s * 0.15, s * 0.68, s * 0.30), 8, 8)
        p.setBrush(QColor("#D3DAE4"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(-s * 0.24, -s * 0.07, s * 0.20, s * 0.14))
        p.drawRoundedRect(QRectF(s * 0.02, -s * 0.06, s * 0.26, s * 0.12), 4, 4)
        p.restore()


class StepCard(QFrame):
    """검사 진행의 한 단계: 번호 + 이름, 상태 배지, 삽화, 타이머/진행 막대, 설명."""

    def __init__(self, index: int, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("stepCard")
        self.index = index
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.num = QLabel(str(index + 1), objectName="stepNum")
        self.num.setFixedSize(28, 28)
        self.num.setAlignment(Qt.AlignCenter)
        self.name = QLabel(f"{index + 1}단계. {name}", objectName="stepName")
        head.addWidget(self.num)
        head.addWidget(self.name, 1)
        v.addLayout(head)

        self.badge = QLabel("대기", objectName="stepBadge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedHeight(24)
        self.badge.setMinimumWidth(78)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.badge)
        row.addStretch(1)
        v.addLayout(row)

        self.art = StepIllustration(index, 104)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.art)
        row.addStretch(1)
        v.addLayout(row)

        self.time = QLabel("", objectName="stepTime")
        self.time.setAlignment(Qt.AlignCenter)
        self.bar = QProgressBar(objectName="stepBar")
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.pct = QLabel("", objectName="stepPct")
        self.pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        brow = QHBoxLayout()
        brow.setSpacing(6)
        brow.addWidget(self.bar, 1)
        brow.addWidget(self.pct)
        self.prog = QWidget()
        pv = QVBoxLayout(self.prog)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(2)
        pv.addWidget(self.time)
        pv.addLayout(brow)
        v.addWidget(self.prog)

        self.desc = QLabel("", objectName="stepDesc", wordWrap=True)
        self.desc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        v.addWidget(self.desc, 1)

    def update_card(self, status: str, badge: str, active: bool, desc: str, time_text: str = "",
                    progress: Optional[float] = None) -> None:
        """status: pending | active | done | error"""
        _set_prop(self, "active", active)
        _set_prop(self, "status", status)
        _set_prop(self.num, "status", status)
        _set_prop(self.badge, "status", status)
        self.badge.setText(badge)
        self.art.set_state(done=status == "done", dim=status == "pending")
        self.desc.setText(desc)
        show = progress is not None
        self.prog.setVisible(show)
        if show:
            self.time.setText(time_text)
            self.time.setVisible(bool(time_text))
            self.bar.setValue(int(max(0.0, min(1.0, progress)) * 1000))
            self.pct.setText(f"{int(round(progress * 100))}%")


class ChipSelect(QFrame):
    """만성질환 같은 다중 선택. 선택한 항목을 칩으로 보이고, 오른쪽 ▾ 로 목록을 연다. 칩을 누르면 해제."""
    changed = pyqtSignal()
    MAX_SHOWN = 2

    def __init__(self, options, placeholder: str = "선택", parent=None):
        super().__init__(parent)
        self.setObjectName("chipSelect")
        self._options = list(options)
        self._selected: List[str] = []
        self._placeholder = placeholder
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(10, 0, 8, 0)
        self._row.setSpacing(6)
        self._chips_box = QHBoxLayout()
        self._chips_box.setSpacing(6)
        self._row.addLayout(self._chips_box, 1)
        self.arrow = QToolButton(objectName="chipArrow")
        self.arrow.setArrowType(Qt.DownArrow)                # 글꼴에 의존하지 않는 화살표
        self.arrow.setFocusPolicy(Qt.NoFocus)
        self.arrow.clicked.connect(self._open_menu)
        self._row.addWidget(self.arrow)
        self.setCursor(Qt.PointingHandCursor)
        self._rebuild()

    def selected(self) -> List[str]:
        return list(self._selected)

    def set_selected(self, items) -> None:
        self._selected = [x for x in items if x in self._options]
        self._rebuild()
        self.changed.emit()

    def mousePressEvent(self, e):
        self._open_menu()

    def _open_menu(self) -> None:
        menu = QMenu(self)
        menu.setObjectName("chipMenu")
        for opt in self._options:
            act = menu.addAction(opt)
            act.setCheckable(True)
            act.setChecked(opt in self._selected)
            act.toggled.connect(lambda on, o=opt: self._toggle(o, on))
        menu.exec_(self.mapToGlobal(self.rect().bottomLeft()))

    def _toggle(self, opt: str, on: bool) -> None:
        if on and opt not in self._selected:
            self._selected.append(opt)
        elif not on and opt in self._selected:
            self._selected.remove(opt)
        self._rebuild()
        self.changed.emit()

    def _rebuild(self) -> None:
        while self._chips_box.count():
            w = self._chips_box.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if not self._selected:
            ph = QLabel(self._placeholder, objectName="chipPlaceholder")
            self._chips_box.addWidget(ph)
            return
        for opt in self._selected[:self.MAX_SHOWN]:
            b = QPushButton(f"{opt}  ×", objectName="chip")
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, o=opt: self._toggle(o, False))
            self._chips_box.addWidget(b)
        extra = len(self._selected) - self.MAX_SHOWN
        if extra > 0:
            self._chips_box.addWidget(QLabel(f"+{extra}", objectName="chipMore"))
        self._chips_box.addStretch(1)


class HistoryTable(QTableWidget):
    """최근 검사 이력: 날짜/시간, 검사 항목, 결과, 상태. 손가락으로 밀어서 스크롤."""
    HEADERS = ("날짜 / 시간", "검사 항목", "결과", "상태")

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setObjectName("historyTable")
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.verticalHeader().hide()
        self.setShowGrid(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        h = self.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        h.setHighlightSections(False)
        h.setMinimumSectionSize(60)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        QScroller.grabGesture(self.viewport(), QScroller.LeftMouseButtonGesture)

    def set_items(self, items: List[HistoryItem]) -> None:
        self.setRowCount(len(items))
        for r, it in enumerate(items):
            self.setRowHeight(r, 34)
            when = it.when.strftime("%Y. %m. %d  %H:%M")
            cells = (when, it.title, format_value(it.value) + (f" {it.unit}" if it.unit and it.value is not None else ""))
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self.setItem(r, c, item)
            tag = QLabel(it.status or "—", objectName="histStatus")
            tag.setAlignment(Qt.AlignCenter)
            tag.setProperty("kind", {"정상": "ok", "주의": "warn"}.get(it.status, "none"))
            tag.setFixedHeight(22)
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(4, 0, 4, 0)
            hl.addWidget(tag)
            self.setCellWidget(r, 3, holder)


class SectionIcon(QWidget):
    """카드 제목 옆의 작은 아이콘 (직접 그림): person / chart / flask / device / doc"""

    def __init__(self, kind: str, size: int = 26, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        s = self.width()
        blue = QColor(BLUE)
        p.setPen(Qt.NoPen)
        p.setBrush(blue)
        if self.kind == "person":
            p.drawEllipse(QRectF(s * 0.32, s * 0.08, s * 0.36, s * 0.36))
            path = QPainterPath()
            path.addRoundedRect(QRectF(s * 0.14, s * 0.52, s * 0.72, s * 0.40), s * 0.2, s * 0.2)
            p.drawPath(path)
        elif self.kind == "chart":
            for i, h in enumerate((0.45, 0.80, 0.62)):
                p.drawRoundedRect(QRectF(s * (0.12 + i * 0.30), s * (0.92 - h), s * 0.2, s * h), 2, 2)
        elif self.kind == "flask":
            path = QPainterPath()
            path.moveTo(s * 0.38, s * 0.08)
            path.lineTo(s * 0.62, s * 0.08)
            path.lineTo(s * 0.62, s * 0.38)
            path.lineTo(s * 0.88, s * 0.84)
            path.lineTo(s * 0.12, s * 0.84)
            path.lineTo(s * 0.38, s * 0.38)
            path.closeSubpath()
            p.drawPath(path)
        elif self.kind == "device":
            p.drawRoundedRect(QRectF(s * 0.10, s * 0.14, s * 0.80, s * 0.70), 4, 4)
            p.setBrush(QColor("#FFFFFF"))
            p.drawRoundedRect(QRectF(s * 0.2, s * 0.24, s * 0.6, s * 0.28), 2, 2)
        else:                                    # doc
            p.drawRoundedRect(QRectF(s * 0.18, s * 0.06, s * 0.64, s * 0.88), 3, 3)
            p.setPen(QPen(QColor("#FFFFFF"), 1.6))
            for i in range(3):
                y = s * (0.32 + i * 0.18)
                p.drawLine(QPointF(s * 0.30, y), QPointF(s * 0.70, y))


class MiniIcon(QWidget):
    """결과 카드의 작은 아이콘 (직접 그림): clock / calendar / doc"""

    def __init__(self, kind: str, size: int = 22, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        s = self.width()
        pen = QPen(QColor("#5B6B7C"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if self.kind == "clock":
            p.drawEllipse(QRectF(s * 0.1, s * 0.1, s * 0.8, s * 0.8))
            p.drawPolyline(QPointF(s * 0.5, s * 0.28), QPointF(s * 0.5, s * 0.52), QPointF(s * 0.68, s * 0.62))
        elif self.kind == "calendar":
            p.drawRoundedRect(QRectF(s * 0.12, s * 0.2, s * 0.76, s * 0.68), 3, 3)
            p.drawLine(QPointF(s * 0.12, s * 0.42), QPointF(s * 0.88, s * 0.42))
            p.drawLine(QPointF(s * 0.32, s * 0.1), QPointF(s * 0.32, s * 0.28))
            p.drawLine(QPointF(s * 0.68, s * 0.1), QPointF(s * 0.68, s * 0.28))
        else:
            p.drawRoundedRect(QRectF(s * 0.2, s * 0.08, s * 0.6, s * 0.84), 3, 3)
            for i in range(3):
                y = s * (0.34 + i * 0.17)
                p.drawLine(QPointF(s * 0.32, y), QPointF(s * 0.68, y))


ICON_DIR = Path(__file__).resolve().parent.parent / "icon"
# 아이콘 PNG 는 '투명도 마스크'로만 쓴다 (색은 상태에 따라 입힌다). kit_check_mono.png 는 tools/make_status_icons.py 가 kit_check.png 에서 만든다.
ICON_FILES = {"power": "power.png", "strip": "kit_check_mono.png", "wifi": "wifi.png"}
GLYPH_RATIO = {"power": 0.58, "strip": 0.54, "wifi": 0.52}      # 원형 배경 지름 대비 아이콘 크기 (원본 PNG 의 여백이 달라 따로 맞춘다)
_ICON_CACHE: dict = {}


def tinted_icon(kind: str, px: int, color: str) -> Optional[QPixmap]:
    """icon/ 의 PNG 를 px x px 로 줄이고 color 한 가지 색으로 칠한다. 파일이 없거나 못 읽으면 None (그리기 대체 경로를 쓴다)."""
    key = (kind, px, color)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    pm = None
    name = ICON_FILES.get(kind)
    if name and px > 0:
        img = QImage(str(ICON_DIR / name))
        if not img.isNull():
            img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied).scaled(
                px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            out = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
            out.fill(Qt.transparent)
            q = QPainter(out)
            q.drawImage(0, 0, img)
            q.setCompositionMode(QPainter.CompositionMode_SourceIn)       # 원본의 투명도만 남기고 색을 바꾼다
            q.fillRect(out.rect(), QColor(color))
            q.end()
            pm = QPixmap.fromImage(out)
    _ICON_CACHE[key] = pm
    return pm


class StatusIcon(QWidget):
    """장비 상태의 원형 아이콘 (직접 그림): power / strip / wifi. state: ok | warn | bad"""
    COLORS = {"ok": ("#E3F6EE", "#1FA37A"), "warn": ("#FFF1D6", "#C47A00"), "bad": ("#FFE1E1", "#C73838")}

    def __init__(self, kind: str, size: int = 46, parent=None):
        super().__init__(parent)
        self.kind, self.state = kind, "ok"
        self.setFixedSize(size, size)

    def set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        bg, fg = self.COLORS.get(self.state, self.COLORS["ok"])
        s = self.width()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(bg))
        p.drawEllipse(QRectF(0, 0, s, s))
        glyph = int(round(s * GLYPH_RATIO.get(self.kind, 0.55)))
        pm = tinted_icon(self.kind, glyph, fg)
        if pm is not None:                               # icon/ 의 PNG 를 상태 색 단색으로 칠해 그린다
            p.drawPixmap((s - glyph) // 2, (s - glyph) // 2, pm)
            return
        pen = QPen(QColor(fg), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        c = s / 2
        if self.kind == "power":
            p.drawArc(QRectF(s * 0.26, s * 0.28, s * 0.48, s * 0.48), 120 * 16, -300 * 16)
            p.drawLine(QPointF(c, s * 0.22), QPointF(c, s * 0.48))
        elif self.kind == "strip":
            p.drawRoundedRect(QRectF(s * 0.38, s * 0.2, s * 0.24, s * 0.6), 4, 4)
            p.drawLine(QPointF(c, s * 0.34), QPointF(c, s * 0.5))
        else:                                    # wifi
            for r in (0.30, 0.20):
                p.drawArc(QRectF(c - s * r, s * 0.62 - s * r, 2 * s * r, 2 * s * r), 45 * 16, 90 * 16)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(fg))
            p.drawEllipse(QPointF(c, s * 0.64), s * 0.04, s * 0.04)


class DeviceStatusPanel(QWidget):
    """장비 상태: 아이콘 3개(장비 / 키트 / 연결)와 한 줄 문구. 세로·가로 측정 화면이 함께 쓴다.
    정상은 초록, 주의는 주황, 문제는 빨강. 모듈 정보(FW/보정/보드)는 화면 공간이 없어 아이콘의 툴팁으로만 둔다."""
    KEYS = (("device", "power"), ("kit", "strip"), ("link", "wifi"))

    def __init__(self, icon_size: int = 40, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.icons: dict = {}
        self.labels: dict = {}
        for key, kind in self.KEYS:
            col = QVBoxLayout()
            col.setSpacing(2)
            ic = StatusIcon(kind, icon_size)
            lb = QLabel("", objectName="devLabel")
            lb.setAlignment(Qt.AlignCenter)
            col.addWidget(ic, 0, Qt.AlignHCenter)
            col.addWidget(lb)
            row.addLayout(col, 1)
            self.icons[key], self.labels[key] = ic, lb
        self.module = QLabel("")                 # 모듈 정보 텍스트 (화면에는 넣지 않고 툴팁에 쓴다)

    def render(self, d) -> None:
        """d: ui.dashboard_logic.DeviceView"""
        states = {"device": "ok" if d.device_ok else "bad", "kit": d.kit_kind, "link": "ok" if d.link_ok else "bad"}
        texts = {"device": "장비 정상" if d.device_ok else "모듈 없음",
                 "kit": {"ok": "키트 정상", "warn": "신호 포화", "bad": "키트 확인 불가"}[d.kit_kind],
                 "link": "연결 정상" if d.link_ok else "연결 끊김"}
        for key, state in states.items():
            self.icons[key].set_state(state)
            self.labels[key].setText(texts[key])
            _set_prop(self.labels[key], "kind", state)
            self.icons[key].setToolTip(d.module_text)
        self.module.setText(d.module_text)


class ProfileCard(QFrame):
    """세로 화면 프로필 선택 카드: 원형 아바타 + 이름 (+ 선택 체크). 짧게 누르면 선택, 길게 누르면 편집."""
    clicked = pyqtSignal(str)
    longPressed = pyqtSignal(str)

    def __init__(self, pid: str, name: str, add: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("profileCard")
        self.pid, self.add = pid, add
        self._selected = False
        self._moved = False
        self.setFixedSize(132, 64)
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(8)
        self.avatar = _Avatar(add)
        self.avatar.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.label = QLabel(name, objectName="profileName")
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(self.avatar)
        row.addWidget(self.label, 1)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._on_hold)
        self._fired = False

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self.avatar.selected = on
        self.avatar.update()
        _set_prop(self, "selected", on)

    def mousePressEvent(self, e):
        self._fired = False
        if not self.add:
            self._hold.start(650)

    def mouseReleaseEvent(self, e):
        self._hold.stop()
        if not self._fired and self.rect().contains(e.pos()):
            self.clicked.emit(self.pid)

    def _on_hold(self) -> None:
        self._fired = True
        self.longPressed.emit(self.pid)


class _Avatar(QWidget):
    def __init__(self, add: bool = False, parent=None):
        super().__init__(parent)
        self.add, self.selected = add, False
        self.setFixedSize(40, 40)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        s = self.width()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#DCEBFE" if (self.selected or self.add) else "#E8EDF3"))
        p.drawEllipse(QRectF(0, 0, s, s))
        p.setBrush(QColor(BLUE if (self.selected or self.add) else "#8A97A8"))
        if self.add:
            p.setPen(QPen(QColor(BLUE), 2.8, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(s * 0.3, s * 0.5), QPointF(s * 0.7, s * 0.5))
            p.drawLine(QPointF(s * 0.5, s * 0.3), QPointF(s * 0.5, s * 0.7))
            return
        p.drawEllipse(QRectF(s * 0.35, s * 0.18, s * 0.30, s * 0.30))
        path = QPainterPath()
        path.addRoundedRect(QRectF(s * 0.22, s * 0.52, s * 0.56, s * 0.30), s * 0.14, s * 0.14)
        p.drawPath(path)
        if self.selected:                        # 선택 표시: 오른쪽 아래 체크
            p.setBrush(QColor(BLUE))
            p.setPen(QPen(QColor("#FFFFFF"), 1.6))
            p.drawEllipse(QRectF(s * 0.62, s * 0.62, s * 0.38, s * 0.38))
            p.setPen(QPen(QColor("#FFFFFF"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline(QPointF(s * 0.70, s * 0.82), QPointF(s * 0.78, s * 0.89), QPointF(s * 0.91, s * 0.74))
