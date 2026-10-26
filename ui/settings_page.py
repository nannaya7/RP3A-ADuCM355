"""설정 화면 — Wi-Fi / 블루투스 검색·등록.

가로(1280x800): 왼쪽 목록 + 오른쪽 상세, 세로(480x800): 위 목록 + 아래 상세.
외부 명령(nmcli, bluetoothctl)은 느릴 수 있어 모두 net/tasks.py 의 백그라운드에서 부르고, 화면은 결과만 그린다.
"""
from typing import Callable, List, Optional

from PyQt5.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QBoxLayout, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QProgressBar, QPushButton, QScroller, QSizePolicy, QStackedWidget, QStyle, QStyledItemDelegate,
                             QVBoxLayout, QWidget)

from net.tasks import TaskRunner

from .sensor_panel import SensorPanel
from .widgets import Field, RoleTabs

ROLE_OBJ, ROLE_TITLE, ROLE_SUB, ROLE_BADGE, ROLE_BARS = (Qt.UserRole + i for i in range(5))
MIN_WIFI_PW = 8


def _repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


def _set_prop(w: QWidget, name: str, value) -> None:
    w.setProperty(name, value)
    _repolish(w)


def bars_for_signal(percent: int) -> int:
    """신호 세기(0~100%) → 막대 0~4개"""
    return 0 if percent <= 0 else min(4, 1 + percent // 26)


def bars_for_rssi(rssi: Optional[int]) -> int:
    """RSSI(dBm, 보통 -100~-30) → 막대 1~4개. 값이 없으면 -1(표시 안 함)"""
    if rssi is None:
        return -1
    return bars_for_signal(max(0, min(100, 2 * (rssi + 100))))


class RowDelegate(QStyledItemDelegate):
    """목록 한 줄: 왼쪽에 이름/부제, 오른쪽에 상태 배지와 신호 막대."""

    def __init__(self, parent=None, height: int = 64):
        super().__init__(parent)
        self._h = height

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), self._h)

    def paint(self, p: QPainter, option, index) -> None:
        p.save()
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(option.rect)
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            p.setBrush(QColor("#D6F0E5"))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(r.adjusted(4, 3, -4, -3), 10, 10)
        else:
            p.setPen(QPen(QColor("#E3EDE8"), 1))
            p.drawLine(int(r.left() + 14), int(r.bottom()), int(r.right() - 14), int(r.bottom()))

        title, sub = index.data(ROLE_TITLE) or "", index.data(ROLE_SUB) or ""
        badge, bars = index.data(ROLE_BADGE) or "", index.data(ROLE_BARS)
        right = r.right() - 16
        if bars is not None and bars >= 0:                 # 신호 막대 (최대 4개)
            x0 = right - 26
            for i in range(4):
                h = 6 + 5 * i
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#2FAF87" if i < bars else "#CFE0D8"))
                p.drawRoundedRect(QRectF(x0 + i * 7, r.center().y() + 11 - h, 4, h), 1.5, 1.5)
            right = x0 - 12
        if badge:
            f = QFont("Pretendard")
            f.setPixelSize(12)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(badge) + 16
            chip = QRectF(right - w, r.center().y() - 11, w, 22)
            on = badge in ("연결됨",)
            p.setBrush(QColor("#D6F0E5" if on else "#E8EEEB"))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(chip, 11, 11)
            p.setPen(QColor("#1D7A5A" if on else "#5B6B64"))
            p.drawText(chip, Qt.AlignCenter, badge)
            right = chip.left() - 10

        text_w = right - (r.left() + 18)
        f = QFont("Pretendard")
        f.setPixelSize(16)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor("#1F2D27"))
        p.drawText(QRectF(r.left() + 18, r.top() + 9, text_w, 24), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(title, Qt.ElideRight, int(text_w)))
        f.setPixelSize(12)
        f.setWeight(QFont.Normal)
        p.setFont(f)
        p.setPen(QColor("#5B6B64"))
        p.drawText(QRectF(r.left() + 18, r.top() + 34, text_w, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(sub, Qt.ElideRight, int(text_w)))
        p.restore()


class DevicePanel(QWidget):
    """Wi-Fi / 블루투스 공통 화면. 종류별 내용은 하위 클래스가 채운다."""
    NAME = ""
    POWER_ON_TEXT, POWER_OFF_TEXT = "켜기", "끄기"
    SCAN_TEXT = "검색"
    HINT = "목록에서 항목을 선택하세요."

    def __init__(self, backend, runner: TaskRunner, portrait: bool):
        super().__init__()
        self.backend, self.runner, self._portrait = backend, runner, portrait
        self._busy = False
        self._powered: Optional[bool] = None
        self._selected_key = None
        self._loaded_once = False
        self._objs: List = []                  # 지금 목록에 보이는 항목 (필터 적용 후)
        self._all: List = []                   # 검색된 전체 (신호 세기 순)
        self._kb_visible = False
        self._usable = True

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8 if portrait else 10)

        # ---- 상태 / 전원 / 검색 ----
        self.head = QWidget()
        head = QHBoxLayout(self.head)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        self.status = QLabel("", objectName="netStatus", wordWrap=True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.power_btn = QPushButton(self.POWER_OFF_TEXT, objectName="ghostBtn")
        self.scan_btn = QPushButton(self.SCAN_TEXT, objectName="primaryBtn")
        bh = 44 if portrait else 48
        for b, w in ((self.power_btn, 76), (self.scan_btn, 84)):
            b.setFixedSize(w, bh)
            b.setFocusPolicy(Qt.NoFocus)
        self.scan_btn.setStyleSheet("font-size: 16px;")
        head.addWidget(self.status, 1)
        self.extra_head = QHBoxLayout()               # 하위 클래스가 버튼을 더 넣는 자리
        self.extra_head.setSpacing(8)
        head.addLayout(self.extra_head)
        head.addWidget(self.power_btn)
        head.addWidget(self.scan_btn)
        root.addWidget(self.head)

        self.busy_bar = QProgressBar(objectName="netBusy")
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedHeight(4)
        self.busy_bar.hide()
        root.addWidget(self.busy_bar)

        # ---- 이름 필터 (입력한 글자를 포함한 항목만 보인다) ----
        self.filter = Field("이름으로 찾기", height=44 if portrait else 48, large=True)
        self.filter.edit.setClearButtonEnabled(True)
        self.filter.edit.setFocusPolicy(Qt.ClickFocus)         # 화면이 열릴 때 저절로 포커스를 받아 키보드가 뜨지 않게
        self.filter_count = QLabel("", objectName="devInfo")
        self.filter_row = QWidget()
        fr = QHBoxLayout(self.filter_row)
        fr.setContentsMargins(0, 0, 0, 0)
        fr.setSpacing(10)
        fr.addWidget(self.filter, 1)
        fr.addWidget(self.filter_count)
        root.addWidget(self.filter_row)
        self.filter.edit.textChanged.connect(self._on_filter_changed)
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_focus_moved)     # 키보드가 열린 채 입력란이 바뀌어도 배치를 맞춘다

        # ---- 본문: 목록 + 상세 ----
        body = QBoxLayout(QBoxLayout.TopToBottom if portrait else QBoxLayout.LeftToRight)
        body.setSpacing(10 if portrait else 16)
        self.list = QListWidget(objectName="devList")
        self.list.setItemDelegate(RowDelegate(self.list, 60 if portrait else 66))
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setFrameShape(QFrame.NoFrame)
        QScroller.grabGesture(self.list.viewport(), QScroller.LeftMouseButtonGesture)   # 손가락으로 밀어서 스크롤
        self.list.itemClicked.connect(self._on_item_clicked)

        self.detail = QFrame(objectName="devDetail")
        dv = QVBoxLayout(self.detail)
        dv.setContentsMargins(*((16, 12, 16, 14) if portrait else (22, 18, 22, 18)))
        dv.setSpacing(6)
        self.d_hint = QLabel(self.HINT, objectName="devInfo", wordWrap=True)
        self.d_title = QLabel("", objectName="devTitle")
        self.d_title.setWordWrap(True)
        self.d_info = QLabel("", objectName="devInfo", wordWrap=True)
        self.ssid_field = Field("네트워크 이름(SSID)", height=46 if portrait else 48)
        self.pw_field = Field("비밀번호", password=True, height=46 if portrait else 48)
        self.d_msg = QLabel("", objectName="netMsg", wordWrap=True)
        self.d_msg.hide()
        self.btn_main = QPushButton("", objectName="primaryBtn")
        self.btn_alt = QPushButton("", objectName="ghostBtn")
        self.btn_del = QPushButton("", objectName="dangerBtn")
        bh = 52 if portrait else 56
        row = QHBoxLayout()
        row.setSpacing(8)
        for b in (self.btn_main, self.btn_alt, self.btn_del):
            b.setFixedHeight(bh)
            b.setFocusPolicy(Qt.NoFocus)
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            row.addWidget(b, 1)
        self.btn_alt.setStyleSheet("font-size: 16px;")
        self.btn_main.setStyleSheet("font-size: 18px;")
        for w in (self.d_hint, self.d_title, self.d_info, self.ssid_field, self.pw_field, self.d_msg):
            dv.addWidget(w)
        dv.addSpacing(4)
        dv.addLayout(row)
        dv.addStretch(1)

        if portrait:
            body.addWidget(self.list, 1)
            body.addWidget(self.detail, 0)
            self.detail.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            body.addStretch(0)                    # 키보드가 열려 목록이 접히면 상세 카드를 위쪽에 둔다
        else:
            body.addWidget(self.list, 5)
            body.addWidget(self.detail, 4)
        root.addLayout(body, 1)

        self.power_btn.clicked.connect(self._on_power)
        self.scan_btn.clicked.connect(self._on_scan)
        self.btn_main.clicked.connect(self._on_main)
        self.btn_alt.clicked.connect(self._on_alt)
        self.btn_del.clicked.connect(self._on_del)
        self._show_detail(None)

    # ================= 하위 클래스가 채우는 부분 =================
    def key_of(self, obj):                       # 목록에서 같은 항목을 다시 찾기 위한 키
        raise NotImplementedError

    def row_of(self, obj) -> tuple:              # (제목, 부제, 배지, 막대수)
        raise NotImplementedError

    def sort_key(self, obj):                     # 목록 정렬 키: 신호가 센 것부터
        raise NotImplementedError

    def search_text(self, obj) -> str:           # 필터가 비교하는 글자
        raise NotImplementedError

    def fill_detail(self, obj) -> None:          # 상세 카드 내용과 버튼
        raise NotImplementedError

    def load(self, scan: bool):                  # 백그라운드: (powered, 상태문구, [obj])
        raise NotImplementedError

    def set_power(self, on: bool) -> None:       # 백그라운드
        raise NotImplementedError

    def on_main(self, obj) -> Optional[Callable]:
        return None

    def on_alt(self, obj) -> Optional[Callable]:
        return None

    def on_del(self, obj) -> Optional[Callable]:
        return None

    # ================= 공통 동작 =================
    def open(self) -> None:
        """설정 화면이 열릴 때(또는 탭이 처음 보일 때) 현재 상태를 읽는다."""
        if not self._loaded_once:
            self.refresh(scan=True)

    def set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        self.busy_bar.setVisible(busy)
        for b in (self.power_btn, self.scan_btn, self.btn_main, self.btn_alt, self.btn_del):
            b.setEnabled(not busy and self._usable)
        if busy and text:
            self.status.setText(text)

    def refresh(self, scan: bool = True, text: str = "") -> None:
        if self._busy:
            return
        self._loaded_once = True
        self.set_busy(True, text or "목록을 읽는 중…")
        self.runner.submit(lambda: self.load(scan), self._on_loaded)

    def _on_loaded(self, result, err: str) -> None:
        self.set_busy(False)
        if err or result is None:
            self._usable = "설치되어 있는지" not in err           # 명령 자체가 없으면 버튼을 막는다
            self.status.setText(err or "상태를 읽지 못했습니다.")
            self._fill_list([])
            self.set_busy(False)
            self._show_detail(None)
            return
        self._usable = True
        powered, status, objs = result
        self._powered = powered
        self.status.setText(status)
        self.power_btn.setText(self.POWER_OFF_TEXT if powered else self.POWER_ON_TEXT)
        self.scan_btn.setEnabled(bool(powered))
        self._fill_list(objs)
        self.set_busy(False)
        self.scan_btn.setEnabled(bool(powered))

    def _fill_list(self, objs: list) -> None:
        self._all = sorted(objs, key=self.sort_key)
        self._render()

    def _on_filter_changed(self, _text: str) -> None:
        self._render()
        self.list.scrollToTop()

    def _render(self) -> None:
        """전체 목록에서 필터에 맞는 항목만 목록에 그린다."""
        q = self.filter.text().strip().lower()
        objs = [o for o in self._all if not q or q in self.search_text(o).lower()]
        self._objs = objs
        self.filter_count.setText(f"{len(objs)} / {len(self._all)}" if q else f"{len(self._all)}개")
        self.list.clear()
        sel_row = -1
        for i, o in enumerate(objs):
            title, sub, badge, bars = self.row_of(o)
            it = QListWidgetItem()
            it.setData(ROLE_OBJ, o)
            it.setData(ROLE_TITLE, title)
            it.setData(ROLE_SUB, sub)
            it.setData(ROLE_BADGE, badge)
            it.setData(ROLE_BARS, bars)
            self.list.addItem(it)
            if self._selected_key is not None and self.key_of(o) == self._selected_key:
                sel_row = i
        if sel_row >= 0:
            self.list.setCurrentRow(sel_row)
            self._show_detail(self._objs[sel_row], keep_msg=True)
        else:
            if not any(self.key_of(o) == self._selected_key for o in self._all):   # 필터로 가려진 것뿐이면 선택을 유지한다
                self._selected_key = None
            self._show_detail(None, keep_msg=True)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        obj = item.data(ROLE_OBJ)
        self._selected_key = self.key_of(obj)
        self._show_detail(obj)

    def current_obj(self):
        it = self.list.currentItem()
        return it.data(ROLE_OBJ) if it is not None else None

    def _show_detail(self, obj, keep_msg: bool = False) -> None:
        has = obj is not None
        self.d_hint.setVisible(not has)
        for w in (self.d_title, self.d_info):
            w.setVisible(has)
        for w in (self.ssid_field, self.pw_field, self.btn_main, self.btn_alt, self.btn_del):
            w.setVisible(False)
        if not keep_msg:
            self.show_msg("")
        if has:
            self.fill_detail(obj)

    def show_msg(self, text: str, level: str = "ok") -> None:
        self.d_msg.setText(text)
        self.d_msg.setVisible(bool(text))
        _set_prop(self.d_msg, "level", level)

    # ---- 버튼 ----
    def _start(self, fn: Optional[Callable], text: str) -> None:
        if fn is None or self._busy:
            return
        self.show_msg("")
        self.set_busy(True, text)
        self.runner.submit(fn, self._after_action)

    def _after_action(self, result, err: str) -> None:
        self.set_busy(False)
        if err:
            self.show_msg(err, "error")
        else:
            self.show_msg(result if isinstance(result, str) else "완료되었습니다.", "ok")
        self.refresh(scan=False, text="목록을 갱신하는 중…")

    def _on_main(self) -> None:
        o = self.current_obj()
        if o is not None or self.allow_no_selection():
            self.run_main(o)

    def run_main(self, obj) -> None:
        self._start(self.on_main(obj), self.progress_text("main", obj))

    def _on_alt(self) -> None:
        self._start(self.on_alt(self.current_obj()), self.progress_text("alt", self.current_obj()))

    def _on_del(self) -> None:
        self._start(self.on_del(self.current_obj()), self.progress_text("del", self.current_obj()))

    def allow_no_selection(self) -> bool:
        return False

    def progress_text(self, which: str, obj) -> str:
        return "처리 중…"

    def _on_scan(self) -> None:
        self.refresh(scan=True, text=self.scan_text())

    def scan_text(self) -> str:
        return "검색 중…"

    def _on_power(self) -> None:
        if self._busy or self._powered is None:
            return
        on = not self._powered
        self.set_busy(True, "켜는 중…" if on else "끄는 중…")

        def work():
            self.set_power(on)
            return self.load(False)

        self.runner.submit(work, self._on_loaded)

    def on_keyboard(self, visible: bool) -> None:
        """터치 키보드가 열리면 입력란과 버튼이 보이도록 위쪽 요소를 접는다.
        세로에서는 필터를 입력하는 중이면 결과 목록을 남기고 상세 카드를 접고, 그 외 입력(비밀번호 등)이면 목록과 필터를 접는다."""
        self._kb_visible = visible
        self._apply_keyboard_layout()

    def _on_focus_moved(self, _old, _new) -> None:
        if self._kb_visible:
            self._apply_keyboard_layout()

    def _apply_keyboard_layout(self) -> None:
        visible = self._kb_visible
        self.head.setVisible(not visible)
        if self._portrait:
            filtering = visible and self.filter.edit.hasFocus()
            self.list.setVisible(not visible or filtering)
            self.filter_row.setVisible(not visible or filtering)
            self.detail.setVisible(not filtering)


class WifiPanel(DevicePanel):
    POWER_ON_TEXT, POWER_OFF_TEXT = "켜기", "끄기"
    HINT = "목록에서 네트워크를 선택하세요.\n연결하면 자동으로 저장되어, 다음부터는 비밀번호 없이 연결됩니다."

    _manual = False                 # '직접 입력' 모드 (숨은 네트워크)
    _pw_key = None                  # 비밀번호 입력란이 어느 네트워크 것인지 (다시 그릴 때 입력한 글자를 지키려고)

    def __init__(self, backend, runner, portrait):
        super().__init__(backend, runner, portrait)
        self.manual_btn = QPushButton("직접 입력", objectName="ghostBtn")
        self.manual_btn.setFixedSize(92, 44 if portrait else 48)
        self.manual_btn.setFocusPolicy(Qt.NoFocus)
        self.extra_head.addWidget(self.manual_btn)
        self.manual_btn.clicked.connect(self._on_manual)

    def set_busy(self, busy: bool, text: str = "") -> None:
        super().set_busy(busy, text)
        if hasattr(self, "manual_btn"):
            self.manual_btn.setEnabled(not busy and self._usable and bool(self._powered or self._powered is None))

    # ---- 내용 ----
    def key_of(self, n):
        return n.ssid

    def sort_key(self, n):
        return (-n.signal, n.ssid.lower())

    def search_text(self, n):
        return n.ssid

    def row_of(self, n):
        sec = n.security if n.secured else "열린 네트워크"
        badge = "연결됨" if n.in_use else ("저장됨" if n.saved else "")
        return n.ssid, f"{sec} · 신호 {n.signal}%", badge, bars_for_signal(n.signal)

    def load(self, scan: bool):
        be = self.backend
        if not be.available():
            raise_unavailable("nmcli 가 없습니다. NetworkManager 가 설치되어 있는지 확인하세요.")
        on = be.radio()
        if not on:
            return False, "Wi-Fi 가 꺼져 있습니다.", []
        nets = be.scan(rescan=scan)
        ssid, ip = be.current()
        status = f"연결됨: {ssid}" + (f"  ·  {ip}" if ip else "") if ssid else "연결된 네트워크 없음"
        return True, status, nets

    def set_power(self, on: bool) -> None:
        self.backend.set_radio(on)

    def fill_detail(self, n) -> None:
        if self._manual:
            return self._fill_manual()
        self.d_title.setText(n.ssid)
        state = "연결됨" if n.in_use else ("저장됨 (자동 연결)" if n.saved else "새 네트워크")
        self.d_info.setText(f"{state}  ·  {n.security or '열린 네트워크'}  ·  신호 {n.signal}%")
        self.ssid_field.setVisible(False)
        need_pw = n.secured and not n.saved and not n.in_use
        self.pw_field.setVisible(need_pw)
        if need_pw and self._pw_key != n.ssid:
            self.pw_field.edit.clear()
            self._pw_key = n.ssid
        self.btn_main.setText("연결")
        self.btn_main.setVisible(not n.in_use)
        self.btn_alt.setText("연결 해제")
        self.btn_alt.setVisible(n.in_use)
        self.btn_del.setText("저장 삭제")
        self.btn_del.setVisible(n.saved)

    def _show_detail(self, obj, keep_msg: bool = False) -> None:
        super()._show_detail(obj, keep_msg)
        if self._manual and obj is None:              # 목록을 다시 그려도 직접 입력 화면은 유지
            self._fill_manual()

    def _fill_manual(self) -> None:
        self.d_hint.hide()
        self.d_title.show()
        self.d_info.show()
        self.btn_alt.hide()
        self.btn_del.hide()
        self.d_title.setText("직접 입력")
        self.d_info.setText("목록에 없는(숨겨진) 네트워크의 이름과 비밀번호를 입력하세요.")
        self.ssid_field.setVisible(True)
        self.pw_field.setVisible(True)
        self.btn_main.setText("연결")
        self.btn_main.setVisible(True)

    def _on_manual(self) -> None:
        self._manual = True
        self.list.clearSelection()
        self.list.setCurrentRow(-1)
        self._selected_key = None
        self.ssid_field.edit.clear()
        self.pw_field.edit.clear()
        self._pw_key = None
        self.show_msg("")
        self._fill_manual()

    def _after_action(self, result, err: str) -> None:
        if self._manual and not err:                  # 직접 입력으로 연결에 성공하면 목록의 일반 항목이 된다
            self._manual = False
            self._selected_key = self.ssid_field.text().strip()
        super()._after_action(result, err)

    def _on_item_clicked(self, item) -> None:
        self._manual = False
        super()._on_item_clicked(item)

    def allow_no_selection(self) -> bool:
        return self._manual

    def on_main(self, n):
        pw = self.pw_field.text() if self.pw_field.isVisible() else ""
        if self._manual:
            ssid = self.ssid_field.text().strip()
            if not ssid:
                self.show_msg("네트워크 이름을 입력해 주세요.", "error")
                return None
            if pw and len(pw) < MIN_WIFI_PW:
                self.show_msg(f"비밀번호는 {MIN_WIFI_PW}자 이상이어야 합니다.", "error")
                return None
            return lambda: self.backend.connect(ssid, pw, hidden=True)
        if self.pw_field.isVisible() and len(pw) < MIN_WIFI_PW:
            self.show_msg("비밀번호를 입력해 주세요 (8자 이상)." if not pw else
                          f"비밀번호는 {MIN_WIFI_PW}자 이상이어야 합니다.", "error")
            return None
        ssid = n.ssid
        return lambda: self.backend.connect(ssid, pw)

    def on_alt(self, n):
        return self.backend.disconnect

    def on_del(self, n):
        ssid = n.ssid
        return lambda: self.backend.forget(ssid)

    def progress_text(self, which, obj):
        return {"main": "연결하는 중…", "alt": "연결을 해제하는 중…", "del": "삭제하는 중…"}[which]

    def scan_text(self):
        return "Wi-Fi 를 검색하는 중…"


class BluetoothPanel(DevicePanel):
    HINT = "[검색]을 눌러 주변 장치를 찾고, 목록에서 선택해 등록하세요.\n등록한 장치는 다음부터 자동으로 연결됩니다."

    # 검색을 막아야 하는 이유를 돌려주는 함수 (막을 필요가 없으면 빈 문자열). 패치 센서로 검사하는 중에 검색하면 센서 통신이 느려진다.
    scan_guard: Optional[Callable[[], str]] = None

    def _scan_blocked(self) -> str:
        return self.scan_guard() if self.scan_guard else ""

    def _on_scan(self) -> None:
        why = self._scan_blocked()
        if why:
            self.show_msg(why, "error")
            return
        super()._on_scan()

    def refresh(self, scan: bool = True, text: str = "") -> None:
        if scan and self._scan_blocked():              # 탭을 처음 열 때의 자동 검색도 막는다 (이미 아는 장치 목록만 읽는다)
            scan, text = False, text or "목록을 읽는 중…"
        super().refresh(scan=scan, text=text)

    # ---- 내용 ----
    def key_of(self, d):
        return d.mac

    def sort_key(self, d):                       # RSSI 가 큰(센) 순, 신호 정보가 없는 장치는 맨 아래
        return (d.rssi is None, -(d.rssi or 0), (d.name or "").lower())

    def search_text(self, d):
        return f"{d.name if d.named else ''} {d.mac}"

    def row_of(self, d):
        state = "연결됨" if d.connected else ("등록됨" if d.paired else "")
        name = d.name if d.named else "이름 없는 장치"
        return name, d.mac, state, bars_for_rssi(d.rssi)

    def load(self, scan: bool):
        be = self.backend
        if not be.available():
            raise_unavailable("bluetoothctl 이 없습니다. bluez 가 설치되어 있는지 확인하세요.")
        if not be.powered():
            detail = getattr(be, "power_detail", "")
            return False, "블루투스가 꺼져 있습니다." + (f" ({detail})" if detail else ""), []
        devs = be.scan() if scan else be.devices()
        conn = [d.name for d in devs if d.connected]
        status = ("연결됨: " + ", ".join(conn)) if conn else "연결된 장치 없음"
        return True, status, devs

    def set_power(self, on: bool) -> None:
        self.backend.set_power(on)

    def fill_detail(self, d) -> None:
        name = d.name if d.named else "이름 없는 장치"
        self.d_title.setText(name)
        state = "연결됨" if d.connected else ("등록됨" if d.paired else "등록 안 됨")
        self.d_info.setText(f"{state}  ·  {d.mac}")
        if d.paired:
            self.btn_main.setText("연결")
            self.btn_main.setVisible(not d.connected)
            self.btn_alt.setText("연결 해제")
            self.btn_alt.setVisible(d.connected)
            self.btn_del.setText("등록 삭제")
            self.btn_del.setVisible(True)
        else:
            self.btn_main.setText("등록")
            self.btn_main.setVisible(True)

    def on_main(self, d):
        mac = d.mac
        if d.paired:
            return lambda: self.backend.connect(mac)
        return lambda: self.backend.register(mac)

    def on_alt(self, d):
        mac = d.mac
        return lambda: self.backend.disconnect(mac)

    def on_del(self, d):
        mac = d.mac
        return lambda: self.backend.remove(mac)

    def progress_text(self, which, d):
        if which == "main":
            return "연결하는 중…" if d.paired else "등록하는 중… (최대 30초)"
        return {"alt": "연결을 해제하는 중…", "del": "삭제하는 중…"}[which]

    def scan_text(self):
        return "주변 장치를 찾는 중… (약 8초)"


def raise_unavailable(msg: str):
    from net.errors import NetError
    raise NetError(msg)


class SettingsPage(QWidget):
    backRequested = pyqtSignal()

    def __init__(self, wifi, bluetooth, portrait: bool = False):
        super().__init__()
        self.setObjectName("settingsPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("compact", portrait)
        self._portrait = portrait
        self.runner = TaskRunner(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(*((16, 14, 16, 14) if portrait else (40, 28, 40, 28)))
        root.setSpacing(10 if portrait else 14)

        top = QHBoxLayout()
        self.back_btn = QPushButton("← 뒤로", objectName="ghostBtn")
        self.back_btn.setFixedSize(*((92, 40) if portrait else (130, 44)))
        self.back_btn.setFocusPolicy(Qt.NoFocus)
        self.back_btn.clicked.connect(self.backRequested)
        self.title = QLabel("설정", objectName="pageTitle")
        top.addWidget(self.back_btn)
        top.addSpacing(18)
        top.addWidget(self.title)
        top.addStretch(1)
        root.addLayout(top)

        self.tabs = RoleTabs([("wifi", "Wi-Fi"), ("bt", "블루투스"), ("sensor", "센서")], height=46, font_px=15,
                             track="#CFE3D9")
        if not portrait:
            self.tabs.setFixedWidth(480)
        self.tabs_row = QWidget()
        tr = QHBoxLayout(self.tabs_row)
        tr.setContentsMargins(0, 0, 0, 0)
        tr.addWidget(self.tabs)
        if not portrait:
            tr.addStretch(1)
        root.addWidget(self.tabs_row)

        self.stack = QStackedWidget()
        self.wifi = WifiPanel(wifi, self.runner, portrait)
        self.bt = BluetoothPanel(bluetooth, self.runner, portrait)
        self.sensor = SensorPanel(portrait)
        self.stack.addWidget(self.wifi)
        self.stack.addWidget(self.bt)
        self.stack.addWidget(self.sensor)
        root.addWidget(self.stack, 1)
        self.tabs.changed.connect(self._on_tab)
        self.sensorModeRequested = self.sensor.modeRequested        # 센서 선택 요청 (AppWindow 가 연결을 바꾼다)

    def current_panel(self):
        return self.stack.currentWidget()

    def _on_tab(self, key: str) -> None:
        self.stack.setCurrentWidget({"wifi": self.wifi, "bt": self.bt, "sensor": self.sensor}[key])
        self.current_panel().open()

    def open(self) -> None:
        """설정 화면이 열릴 때마다 호출. 처음 한 번만 자동으로 읽고, 이후에는 [검색]으로 갱신한다."""
        self.current_panel().open()

    def on_keyboard(self, visible: bool, height: int = 0) -> None:
        self.tabs_row.setVisible(not visible)
        for p in (self.wifi, self.bt):
            p.on_keyboard(visible)

    def shutdown(self) -> None:
        self.runner.wait(3000)
