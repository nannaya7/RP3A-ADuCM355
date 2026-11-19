"""확인/안내 팝업. 아이콘 없이 가운데 정렬한 문구와 큰 버튼을 쓰고, 색은 theme.qss 의 #popup 을 따른다.
창 틀은 쓰지 않고(라즈베리 파이 창 틀은 한글 제목이 깨지고 모서리도 각진다) 둥근 모서리의 자체 틀을 그린다."""
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class _Popup(QDialog):
    def __init__(self, parent, text: str, buttons, extra: Optional[QWidget] = None):
        """buttons: [(문구, 강조 여부)] — 눌린 버튼의 위치를 self.choice 에 남긴다."""
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setObjectName("popup")
        self.setAttribute(Qt.WA_TranslucentBackground, True)         # 바깥 네모를 투명하게 해 둥근 모서리만 보이게 한다
        self.setWindowTitle(" ")
        self.setModal(True)
        self.choice = -1
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bar = QFrame(objectName="popupBar")                          # 위쪽 회색 띠 (오른쪽 × 는 취소)
        bar.setFixedHeight(34)
        bar_row = QHBoxLayout(bar)
        bar_row.setContentsMargins(8, 0, 10, 0)
        bar_row.addStretch(1)
        close = QPushButton("✕", objectName="popupClose")
        close.setFixedSize(32, 28)
        close.setFocusPolicy(Qt.NoFocus)
        close.clicked.connect(self.reject)
        bar_row.addWidget(close)
        outer.addWidget(bar)
        body = QFrame(objectName="popupBody")
        outer.addWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 28, 28, 24)
        root.setSpacing(24)
        label = QLabel(text, objectName="popupText")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        root.addWidget(label)
        if extra is not None:                                        # 문구 아래에 넣는 내용 (측정 결과 요약 등)
            root.addWidget(extra)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.buttons = []
        for i, (caption, primary) in enumerate(buttons):
            b = QPushButton(caption, objectName="popupBtn")
            b.setProperty("primary", primary)
            b.setFixedHeight(48)
            b.setMinimumWidth(110)
            b.setAutoDefault(False)
            b.clicked.connect(lambda _=False, n=i: self._pick(n))
            row.addWidget(b, 1)
            self.buttons.append(b)
        root.addLayout(row)
        self.setMinimumWidth(340)

    def _pick(self, n: int) -> None:
        self.choice = n
        self.accept()


class _LockedPopup(_Popup):
    """진행 팝업: Esc 로도 닫히지 않는다."""
    def keyPressEvent(self, e) -> None:
        e.ignore()


def _run(parent, text: str, buttons, extra: Optional[QWidget] = None, min_width: int = 340) -> int:
    box = _Popup(parent, text, buttons, extra)
    box.setMinimumWidth(min_width)
    box.exec_()
    choice = box.choice
    box.deleteLater()
    return choice


def confirm(parent, title: str, text: str, yes: str = "예", no: str = "아니오") -> bool:
    """예/아니오 확인. 왼쪽이 실행(강조색), 오른쪽이 취소이고 Esc·닫기는 취소로 본다. title 은 호출부 기록용이라 화면에 쓰지 않는다."""
    return _run(parent, text, [(yes, True), (no, False)]) == 0


def notify(parent, text: str, ok: str = "확인") -> None:
    """알림 (버튼 하나)."""
    _run(parent, text, [(ok, True)])


ANALYZE_SECONDS = 160           # 검사가 끝난 뒤 결과를 보여 주기까지 진행 팝업을 보여 주는 시간


def _result_box(parent, rv, method: str, ok: str) -> _Popup:
    from .dashboard_widgets import ResultSummary            # 순환 import 를 피하려고 쓸 때 불러온다
    infos = (("측정 시간", rv.info_wait), ("검증 완료 시간", rv.info_done), ("검사 방법", method or "—"))
    narrow = parent is not None and parent.width() < 600     # 세로(480px) 화면에서는 폭을 줄인다
    box = _Popup(parent, "측정 완료되었습니다.", [(ok, True)], ResultSummary(rv.rows, rv.ready, infos))
    box.setMinimumWidth(440 if narrow else 640)
    return box


def _progress_box(parent, size, seconds: int) -> _Popup:
    """결과 팝업과 같은 크기의 진행 팝업: 진행바 + 퍼센트 + 남은 시간. 닫기·버튼 없이 시간이 되면 스스로 닫힌다."""
    from PyQt5.QtCore import QElapsedTimer, QTimer
    from PyQt5.QtWidgets import QProgressBar
    body = QWidget()
    lay = QVBoxLayout(body)
    lay.setContentsMargins(24, 0, 24, 0)
    lay.setSpacing(14)
    lay.addStretch(1)
    pct = QLabel("0%", objectName="popupPercent")
    pct.setAlignment(Qt.AlignCenter)
    bar = QProgressBar(objectName="popupProgress")
    bar.setRange(0, 1000)
    bar.setTextVisible(False)
    for w in (pct, bar):
        lay.addWidget(w)
    lay.addStretch(1)
    box = _LockedPopup(parent, "결과를 분석하고 있습니다.", [], body)
    box.findChild(QPushButton, "popupClose").hide()           # 진행 중에는 닫을 수 없다
    box.setFixedSize(size)
    clock = QElapsedTimer()
    clock.start()
    tick = QTimer(box)

    def update() -> None:
        ms = min(clock.elapsed(), seconds * 1000)
        bar.setValue(int(ms * 1000 / (seconds * 1000)))
        pct.setText(f"{ms * 100 // (seconds * 1000)}%")
        if ms >= seconds * 1000:
            tick.stop()
            box.accept()

    tick.timeout.connect(update)
    tick.start(100)
    update()
    return box


def result_popup(parent, rv, method: str = "", ok: str = "확인", analyze_s: int = ANALYZE_SECONDS) -> None:
    """검사 완료 팝업: 먼저 진행율 팝업을 analyze_s 초 동안 보여 주고(0 이면 생략), 이어서 같은 크기의 결과 팝업을 띄운다.
    rv: dashboard_logic.ResultView (rows, ready, info_wait, info_done)."""
    result = _result_box(parent, rv, method, ok)
    if analyze_s > 0:
        result.adjustSize()
        wait = _progress_box(parent, result.size(), analyze_s)
        wait.exec_()
        wait.deleteLater()
    result.exec_()
    result.deleteLater()
