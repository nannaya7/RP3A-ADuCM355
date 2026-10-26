"""설정 > 센서: 패치 센서(블루투스) / 내장 센서(UART) 를 토글로 켜고 끈다. 둘은 동시에 켤 수 없다.

화면은 선택을 요청(modeRequested)만 하고, 실제 연결 전환은 AppWindow 가 한다. 거절되면(측정 중 등) AppWindow 가
원래 상태를 다시 알려 주어 토글이 제자리로 돌아간다.
"""
from PyQt5.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QAbstractButton, QBoxLayout, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.comm.sensor import BUILTIN, OFF, PATCH, toggled


class ToggleSwitch(QAbstractButton):
    """직접 그리는 ON/OFF 스위치 (플랫폼 스타일에 상관없이 같은 모양)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(64, 36)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def sizeHint(self) -> QSize:
        return QSize(64, 36)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        on, enabled = self.isChecked(), self.isEnabled()
        track = QColor("#2FAF87" if on else "#C5D3CC")
        if not enabled:
            track.setAlpha(110)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 8
        x = r.right() - 4 - d if on else r.left() + 4
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, r.top() + 4, d, d))


class SensorCard(QFrame):
    clicked = pyqtSignal(bool)

    def __init__(self, title: str, how: str, portrait: bool):
        super().__init__(objectName="devDetail")
        row = QHBoxLayout(self)
        row.setContentsMargins(*((18, 16, 18, 16) if portrait else (24, 20, 24, 20)))
        row.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.title = QLabel(title, objectName="devTitle")
        self.how = QLabel(how, objectName="devInfo", wordWrap=True)
        self.state = QLabel("꺼짐", objectName="sensorState")
        self.state.setWordWrap(True)
        col.addWidget(self.title)
        col.addWidget(self.how)
        col.addWidget(self.state)
        row.addLayout(col, 1)
        self.switch = ToggleSwitch()
        self.switch.clicked.connect(self.clicked)
        row.addWidget(self.switch, 0, Qt.AlignVCenter)

    def show_state(self, on: bool, text: str, level: str) -> None:
        self.switch.setChecked(on)
        self.state.setText(text)
        self.state.setProperty("level", level)
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)


class SensorPanel(QWidget):
    modeRequested = pyqtSignal(str)          # patch / builtin / off

    def __init__(self, portrait: bool = False, patch_how: str = "블루투스로 ADuCM355 연결",
                 builtin_how: str = "UART로 ADuCM355 연결"):
        super().__init__()
        self._mode = BUILTIN
        self._connected = False
        self._checking = False
        self._detail = ""
        self._locked = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10 if portrait else 16)

        self.patch = SensorCard("패치 센서", patch_how, portrait)
        self.builtin = SensorCard("내장 센서", builtin_how, portrait)
        self.patch.clicked.connect(lambda on: self._request(PATCH, on))
        self.builtin.clicked.connect(lambda on: self._request(BUILTIN, on))

        cards = QBoxLayout(QBoxLayout.TopToBottom if portrait else QBoxLayout.LeftToRight)
        cards.setSpacing(10 if portrait else 16)
        cards.addWidget(self.patch)
        cards.addWidget(self.builtin)
        root.addLayout(cards)

        self.hint = QLabel("한 번에 한 가지 센서만 사용할 수 있습니다.\n하나를 켜면 다른 하나는 자동으로 꺼집니다.",
                           objectName="devInfo", wordWrap=True)
        self.msg = QLabel("", objectName="netMsg", wordWrap=True)
        self.msg.hide()
        root.addWidget(self.hint)
        root.addWidget(self.msg)
        root.addStretch(1)
        self._sync()

    # ---- 바깥에서 부르는 것 ----
    def open(self) -> None:                  # 설정 탭 공통 인터페이스 (읽을 것이 없다)
        pass

    def on_keyboard(self, visible: bool) -> None:
        pass

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._sync()

    def set_connection(self, connected: bool, detail: str = "", checking: bool = False) -> None:
        self._connected, self._detail, self._checking = connected, detail, checking
        self._sync()

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        for c in (self.patch, self.builtin):
            c.switch.setEnabled(not locked)

    def show_msg(self, text: str, level: str = "ok") -> None:
        self.msg.setText(text)
        self.msg.setVisible(bool(text))
        self.msg.setProperty("level", level)
        self.msg.style().unpolish(self.msg)
        self.msg.style().polish(self.msg)

    # ---- 내부 ----
    @property
    def mode(self) -> str:
        return self._mode

    def _request(self, which: str, on: bool) -> None:
        new = toggled(self._mode, which, on)
        self._sync()                          # 요청이 받아들여질 때까지 토글은 제자리에 둔다
        if new != self._mode:
            self.show_msg("")
            self.modeRequested.emit(new)

    def _state_text(self, which: str):
        if self._mode != which:
            return False, "꺼짐", "off"
        if self._connected and self._checking:
            return True, "모듈 확인 중…", "warn"
        if self._connected:
            return True, "연결됨" + (f" · {self._detail}" if self._detail else ""), "ok"
        return True, "연결 중… 연결 안 됨" + (f" · {self._detail}" if self._detail else ""), "warn"

    def _sync(self) -> None:
        for which, card in ((PATCH, self.patch), (BUILTIN, self.builtin)):
            card.show_state(*self._state_text(which))
