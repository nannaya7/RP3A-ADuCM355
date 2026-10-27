"""설정 > 센서: 패치 센서(블루투스) / 내장 센서(UART) 를 토글로 켜고 끈다. 둘은 동시에 켤 수 없다.

화면은 선택을 요청(modeRequested)만 하고, 실제 연결 전환은 AppWindow 가 한다. 거절되면(측정 중 등) AppWindow 가
원래 상태를 다시 알려 주어 토글이 제자리로 돌아간다.
"""
from PyQt5.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import (QAbstractButton, QAbstractItemView, QBoxLayout, QFrame, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

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
    scanRequested = pyqtSignal()             # 패치 센서 검색
    patchSelected = pyqtSignal(str, str)     # (BLE 주소, 이름)
    patchCleared = pyqtSignal()

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
        root.addWidget(self._build_picker(portrait))
        root.addWidget(self.hint)
        root.addWidget(self.msg)
        root.addStretch(1)
        self._sync()

    def _build_picker(self, portrait: bool) -> QFrame:
        """패치 센서가 여러 대일 때 연결할 장치를 고른다. 고르지 않으면 이름이 nFor 로 시작하는 첫 장치에 연결된다."""
        card = QFrame(objectName="devDetail")
        col = QVBoxLayout(card)
        col.setContentsMargins(*((18, 14, 18, 14) if portrait else (24, 18, 24, 18)))
        col.setSpacing(6)
        col.addWidget(QLabel("패치 센서 선택", objectName="devTitle"))
        self.picked = QLabel("", objectName="devInfo", wordWrap=True)
        col.addWidget(self.picked)

        self.found = QListWidget(objectName="devList")
        self.found.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.found.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.found.setFocusPolicy(Qt.NoFocus)
        self.found.setFixedHeight(120 if portrait else 110)
        self.found.itemClicked.connect(self._on_found_clicked)
        self.found.hide()
        col.addWidget(self.found)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.scan_btn = QPushButton("검색", objectName="primaryBtn")
        self.clear_btn = QPushButton("선택 해제", objectName="ghostBtn")
        for b in (self.scan_btn, self.clear_btn):
            b.setFocusPolicy(Qt.NoFocus)
            b.setFixedHeight(48 if portrait else 52)
            row.addWidget(b, 1)
        self.scan_btn.clicked.connect(self.scanRequested)
        self.clear_btn.clicked.connect(self.patchCleared)
        col.addLayout(row)
        self.set_picked("", "")
        return card

    # ---- 패치 센서 선택 ----
    def set_picked(self, address: str, name: str) -> None:
        if address:
            self.picked.setText(f"선택한 센서: {name or '(이름 없음)'} · {address}")
        else:
            self.picked.setText("선택 안 함 — 이름이 nFor 로 시작하는 장치에 자동으로 연결합니다.\n"
                                "센서가 여러 대이면 [검색]으로 찾아 하나를 고르세요.")
        self.clear_btn.setEnabled(bool(address))

    def set_scanning(self, busy: bool) -> None:
        self.scan_btn.setEnabled(not busy and not self._locked)
        self.scan_btn.setText("검색 중…" if busy else "검색")

    def set_found(self, devices) -> None:
        """devices: (이름, 주소, rssi) 목록. 비어 있으면 목록을 숨긴다."""
        self.found.clear()
        for name, address, rssi in devices:
            it = QListWidgetItem(f"{name or '(이름 없음)'}\n{address}" + (f"   {rssi} dBm" if rssi is not None else ""))
            it.setData(Qt.UserRole, (address, name))
            self.found.addItem(it)
        self.found.setVisible(self.found.count() > 0)

    def _on_found_clicked(self, item: QListWidgetItem) -> None:
        address, name = item.data(Qt.UserRole)
        self.patchSelected.emit(address, name)

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
        self.scan_btn.setEnabled(not locked)

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
