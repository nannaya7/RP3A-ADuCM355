"""UART 모니터링 화면 — 모듈과 주고받는 줄을 실시간으로 보여 준다 (읽기 전용).

    → STATUS            우리가 보낸 명령 (파란색)
    ← #I,FW,...         모듈이 보낸 줄 (검정, #D 측정점은 회색, ERR 은 빨강)
    • UART 연결 끊김     연결 상태/오류 (주황)

스윕 한 번에 #D 가 수백 줄 오므로 [측정점(#D)] 을 끄면 명령과 응답만 볼 수 있다.
많은 줄이 한꺼번에 와도 화면이 느려지지 않도록 0.1초마다 모아서 그린다.
"""
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScroller, QVBoxLayout,
                             QWidget)

from app.comm.traffic_log import RX, SYS, TX, Entry, TrafficLog, format_entry

FLUSH_MS = 100
MAX_BLOCKS = 4000
COLORS = {TX: "#1B6FB8", RX: "#1F2D27", SYS: "#C47A00"}
DATA_COLOR, ERROR_COLOR = "#8A9892", "#AD3131"


def color_of(e: Entry) -> str:
    if e.kind == RX and e.text.upper().startswith("ERR"):
        return ERROR_COLOR
    if e.is_data:
        return DATA_COLOR
    return COLORS[e.kind]


def mono_font(px: int) -> QFont:
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    f.setPixelSize(px)
    return f


class MonitorPage(QWidget):
    backRequested = pyqtSignal()

    def __init__(self, log: TrafficLog, portrait: bool = False, save_dir: Optional[Path] = None):
        super().__init__()
        self.setObjectName("monitorPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("compact", portrait)
        self._log = log
        self._save_dir = Path(save_dir) if save_dir else Path("results")
        self._portrait = portrait
        self._pending: List[Entry] = []
        self._paused = False
        self._first_block = True

        root = QVBoxLayout(self)
        root.setContentsMargins(*((16, 14, 16, 14) if portrait else (40, 28, 40, 28)))
        root.setSpacing(10)

        # ---- 상단 바 ----
        top = QHBoxLayout()
        self.back_btn = QPushButton("← 뒤로", objectName="ghostBtn")
        self.back_btn.setFixedSize(*((92, 40) if portrait else (130, 44)))
        self.back_btn.setFocusPolicy(Qt.NoFocus)
        self.back_btn.clicked.connect(self.backRequested)
        self.title = QLabel("UART 모니터링", objectName="pageTitle")
        top.addWidget(self.back_btn)
        top.addSpacing(18)
        top.addWidget(self.title)
        top.addStretch(1)
        root.addLayout(top)

        # ---- 필터 / 상태 ----
        bar = QHBoxLayout()
        bar.setSpacing(16 if not portrait else 10)
        self.cb_tx = QCheckBox("보냄 →")
        self.cb_rx = QCheckBox("받음 ←")
        self.cb_data = QCheckBox("측정점(#D)")
        for cb in (self.cb_tx, self.cb_rx, self.cb_data):
            cb.setChecked(True)
            cb.setProperty("touch", True)
            cb.setMinimumHeight(40)
            cb.setFocusPolicy(Qt.NoFocus)
            cb.toggled.connect(self._rebuild)
            bar.addWidget(cb)
        bar.addStretch(1)
        root.addLayout(bar)
        self.status = QLabel("", objectName="monStatus")
        root.addWidget(self.status)

        # ---- 본문 ----
        self.view = QPlainTextEdit(objectName="monView")
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)          # 줄이 길어도 접지 않는다 (좌우로 밀어서 본다)
        self.view.setMaximumBlockCount(MAX_BLOCKS)
        self.view.setFont(mono_font(11 if portrait else 14))
        self.view.setFocusPolicy(Qt.NoFocus)                  # 터치 키보드가 열리지 않게
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        QScroller.grabGesture(self.view.viewport(), QScroller.LeftMouseButtonGesture)
        root.addWidget(self.view, 1)

        # ---- 하단 버튼 ----
        row = QHBoxLayout()
        row.setSpacing(10)
        bh = 52 if portrait else 56
        self.pause_btn = QPushButton("일시정지", objectName="ghostBtn")
        self.clear_btn = QPushButton("지우기", objectName="ghostBtn")
        self.save_btn = QPushButton("저장", objectName="primaryBtn")
        for b in (self.pause_btn, self.clear_btn, self.save_btn):
            b.setFixedHeight(bh)
            b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet("font-size: 17px;")
            row.addWidget(b, 1)
        root.addLayout(row)
        self.note = QLabel("", objectName="monNote", wordWrap=True)
        self.note.hide()
        root.addWidget(self.note)

        self.pause_btn.clicked.connect(self._toggle_pause)
        self.clear_btn.clicked.connect(self._log.clear)
        self.save_btn.clicked.connect(self._save)

        log.entryAdded.connect(self._on_entry)
        log.cleared.connect(self._on_cleared)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flush)
        self._timer.start(FLUSH_MS)
        self._rebuild()

    # ---- 필터 ----
    def _wanted(self, e: Entry) -> bool:
        if e.kind == TX:
            return self.cb_tx.isChecked()
        if e.kind == RX:
            return self.cb_rx.isChecked() and (self.cb_data.isChecked() or not e.is_data)
        return True                                       # 연결/오류 줄은 항상 보인다

    # ---- 그리기 ----
    def _on_entry(self, e: Entry) -> None:
        if len(self._pending) < 2 * MAX_BLOCKS:             # 일시정지 중 무한히 쌓이지 않게
            self._pending.append(e)

    def _on_cleared(self) -> None:
        self._pending.clear()
        self._rebuild()

    def _flush(self) -> None:
        if self._paused:
            self._update_status()
            return
        if self._pending:
            batch, self._pending = self._pending, []
            self._append([e for e in batch if self._wanted(e)])
        self._update_status()

    def _append(self, entries: List[Entry]) -> None:
        if not entries:
            return
        bar = self.view.verticalScrollBar()
        follow = bar.value() >= bar.maximum() - 4            # 맨 아래를 보고 있을 때만 따라간다 (위로 올려 읽는 중이면 그대로)
        cur = QTextCursor(self.view.document())
        cur.movePosition(QTextCursor.End)
        cur.beginEditBlock()
        for e in entries:
            if not self._first_block:
                cur.insertBlock()
            self._first_block = False
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color_of(e)))
            cur.insertText(format_entry(e), fmt)
        cur.endEditBlock()
        if follow:
            bar.setValue(bar.maximum())

    def _rebuild(self, *_) -> None:
        self.view.clear()
        self._first_block = True
        shown = [e for e in self._log.entries() if self._wanted(e)]
        self._pending = []
        self._append(shown[-MAX_BLOCKS:])
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())
        self._update_status()

    def _update_status(self) -> None:
        link = {True: "연결됨", False: "연결 끊김", None: "연결 확인 중"}[self._log.connected]
        held = f" · 보류 {len(self._pending)}줄" if self._paused and self._pending else ""
        self.status.setText(f"{link} · 보냄 {self._log.tx_count} · 받음 {self._log.rx_count}"
                            f"{' · 일시정지' if self._paused else ''}{held}")

    # ---- 버튼 ----
    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_btn.setText("계속" if self._paused else "일시정지")
        if not self._paused:
            self._flush()
        else:
            self._update_status()

    def _save(self) -> None:
        name = datetime.now().strftime("uart_%Y%m%d_%H%M%S.log")
        try:
            path = self._log.save(self._save_dir / "monitor" / name)
        except OSError as e:
            self._show_note(f"저장하지 못했습니다: {e}", error=True)
            return
        self._show_note(f"저장했습니다: {path}")

    def _show_note(self, text: str, error: bool = False) -> None:
        self.note.setText(text)
        self.note.setProperty("level", "error" if error else "ok")
        self.note.style().unpolish(self.note)
        self.note.style().polish(self.note)
        self.note.show()

    def on_keyboard(self, visible: bool, height: int = 0) -> None:
        pass                                                  # 입력란이 없다

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.note.hide()
        self._flush()
