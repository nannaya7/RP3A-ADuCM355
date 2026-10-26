"""앱 내장 터치 키보드 (영문/한글(두벌식)/숫자/기호). 물리 키보드가 없는 DSI 터치 환경용.

- 키 버튼은 포커스를 받지 않으므로 입력란(QLineEdit)의 포커스·커서가 유지된다.
- 입력란에 포커스가 가면 화면 하단에 나타나고, 다른 곳을 누르거나 [완료]를 누르면 사라진다.
- 레이어는 LAYERS 에 정의한다 (abc / ko / sym). 한글 조합은 ui/hangul.py 의 HangulComposer 가 맡는다.
"""
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QApplication, QFrame, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .hangul import JAMO, HangulComposer

# 특수 키 토큰
BS, SHIFT, SYM, ABC, SPACE, DONE, LANG = "<bs>", "<shift>", "<sym>", "<abc>", "<space>", "<done>", "<lang>"

# 각 행: [(키, 가로 비율), ...]  — 문자열 키는 비율 1
def _keys(chars: str) -> list:
    return [(c, 1.0) for c in chars]


LAYERS = {
    "abc": [
        _keys("1234567890") + [(BS, 1.5)],
        _keys("qwertyuiop"),
        [("", 0.5)] + _keys("asdfghjkl") + [("", 0.5)],
        [(SHIFT, 1.5)] + _keys("zxcvbnm") + [(",", 1.0), (".", 1.0)],
        [(SYM, 1.5), (LANG, 1.5), ("@", 1.0), (SPACE, 4.5), ("-", 1.0), ("_", 1.0), (DONE, 2.0)],
    ],
    "ko": [
        _keys("1234567890") + [(BS, 1.5)],
        _keys("ㅂㅈㄷㄱㅅㅛㅕㅑㅐㅔ"),
        [("", 0.5)] + _keys("ㅁㄴㅇㄹㅎㅗㅓㅏㅣ") + [("", 0.5)],
        [(SHIFT, 1.5)] + _keys("ㅋㅌㅊㅍㅠㅜㅡ") + [(",", 1.0), (".", 1.0)],
        [(SYM, 1.5), (LANG, 1.5), ("@", 1.0), (SPACE, 4.5), ("-", 1.0), ("_", 1.0), (DONE, 2.0)],
    ],
    "sym": [
        _keys("1234567890") + [(BS, 1.5)],
        _keys("!@#$%^&*()"),
        _keys("-_=+[]{}/\\"),
        _keys("'\"<>?;:|~`"),
        [(ABC, 1.5), (SPACE, 6.0), (",", 1.0), (".", 1.0), (DONE, 2.0)],
    ],
}

FN_LABELS = {BS: "⌫", SHIFT: "⇧", SYM: "?123", ABC: "가/A", SPACE: "", DONE: "완료", LANG: "한/영"}

# 두벌식 Shift 조합 (쌍자음, ㅒ, ㅖ)
KO_SHIFT = {"ㅂ": "ㅃ", "ㅈ": "ㅉ", "ㄷ": "ㄸ", "ㄱ": "ㄲ", "ㅅ": "ㅆ", "ㅐ": "ㅒ", "ㅔ": "ㅖ"}


class VirtualKeyboard(QFrame):
    KEY_HEIGHT = 56  # 터치 최소 높이 (DisplayProfile.touch_min 과 동일)
    visibilityChanged = pyqtSignal(bool, int)   # (보임 여부, 키보드 높이) — 화면이 가려지지 않게 배치를 바꾸는 데 쓴다

    def __init__(self, parent: QWidget, key_height: int = KEY_HEIGHT, compact: bool = False):
        super().__init__(parent)
        self._compact = compact
        self._gap = 5 if compact else 8
        self.setProperty("compact", compact)
        self.setObjectName("vkb")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._key_height = key_height
        self._layer = "abc"
        self._text_layer = "abc"  # sym 에서 돌아갈 문자 레이어 (abc | ko)
        self._shift = False
        self._hangul = HangulComposer()
        self._expect_pos = -1     # 우리가 입력한 뒤의 커서 위치. 어긋나면 사용자가 커서를 옮긴 것
        self._target: Optional[QLineEdit] = None
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(*((8, 8, 8, 10) if compact else (12, 10, 12, 12)))
        self._root.setSpacing(self._gap)
        self._build()
        self.hide()

    # ---- 포커스 연동 ------------------------------------------------
    def attach(self, app: QApplication) -> None:
        app.focusChanged.connect(self._on_focus_changed)

    def _on_focus_changed(self, _old, new) -> None:
        if new is None:  # 창 비활성화 등: 상태 유지
            return
        if isinstance(new, QLineEdit) and not new.isReadOnly() and self.window() is new.window():
            if new is not self._target:
                self._hangul.reset()
            self._target = new
            self.show_keyboard()
        elif not self.isAncestorOf(new):
            self.hide_keyboard()

    def show_keyboard(self) -> None:
        self.reposition()
        was = self.isVisible()
        self.show()
        self.raise_()
        if not was:
            self.visibilityChanged.emit(True, self.height())

    def hide_keyboard(self) -> None:
        self._hangul.reset()
        self._target = None
        was = self.isVisible()
        self.hide()
        if was:
            self.visibilityChanged.emit(False, 0)

    def reposition(self) -> None:
        p = self.parentWidget()
        h = self.sizeHint().height()
        bottom = p.contentsMargins().bottom()          # 아래쪽 안전 여백이 있으면 그 위에 붙인다
        self.setGeometry(0, p.height() - bottom - h, p.width(), h)

    # ---- 키 입력 ----------------------------------------------------
    def press(self, key: str) -> None:
        t = self._target
        if key == SHIFT:
            self._shift = not self._shift
            self._build()
        elif key == SYM:
            self._hangul.reset()
            self._layer, self._shift = "sym", False
            self._build()
        elif key in (ABC, LANG):
            self._hangul.reset()
            if key == LANG:  # 한/영 전환
                self._text_layer = "ko" if self._text_layer == "abc" else "abc"
            self._layer, self._shift = self._text_layer, False
            self._build()
        elif key == DONE:
            self._hangul.reset()
            if t is not None:
                t.clearFocus()
            self.hide_keyboard()
        elif t is None:
            return
        elif key == BS:
            self._sync_cursor(t)
            res = self._hangul.backspace()
            if res is None:
                t.backspace()
            else:
                self._apply(t, res)
            self._expect_pos = t.cursorPosition()
        elif key == SPACE:
            self._hangul.reset()
            t.insert(" ")
        elif key in JAMO:
            self._sync_cursor(t)
            k = KO_SHIFT.get(key, key) if self._shift else key
            self._apply(t, self._hangul.feed(k))
            self._release_shift()
        else:
            self._hangul.reset()
            t.insert(key.upper() if self._shift else key)
            self._release_shift()

    def _sync_cursor(self, t: QLineEdit) -> None:
        """사용자가 커서를 옮기거나 글자를 선택했으면 조합을 끝낸다."""
        if t.hasSelectedText() or t.cursorPosition() != self._expect_pos:
            self._hangul.reset()

    def _apply(self, t: QLineEdit, res: tuple) -> None:
        delete_n, text = res
        for _ in range(delete_n):
            t.backspace()
        t.insert(text)
        self._expect_pos = t.cursorPosition()

    def _release_shift(self) -> None:
        if self._shift:  # 한 글자 입력 후 기본 상태로 복귀
            self._shift = False
            self._build()

    # ---- 화면 구성 --------------------------------------------------
    def _build(self) -> None:
        while self._root.count():
            item = self._root.takeAt(0)
            if item.layout():
                self._clear(item.layout())
            if item.widget():
                self._discard(item.widget())
        for row in LAYERS[self._layer]:
            hl = QHBoxLayout()
            hl.setSpacing(self._gap)
            for key, ratio in row:
                if not key:
                    hl.addStretch(int(ratio * 10))
                    continue
                hl.addWidget(self._make_key(key), int(ratio * 10))
            self._root.addLayout(hl)

    @classmethod
    def _clear(cls, layout) -> None:
        while layout.count():
            w = layout.takeAt(0).widget()
            if w:
                cls._discard(w)

    @staticmethod
    def _discard(w: QWidget) -> None:
        """이전 키를 즉시 화면에서 떼어내고 삭제를 예약한다 (deleteLater 만으로는 잠시 겹쳐 보인다)."""
        w.hide()
        w.setParent(None)
        w.deleteLater()

    def _key_label(self, key: str) -> str:
        if not self._shift:
            return key
        return KO_SHIFT.get(key, key) if self._layer == "ko" else key.upper()

    def _make_key(self, key: str) -> QPushButton:
        is_fn = key in FN_LABELS
        label = FN_LABELS[key] if is_fn else self._key_label(key)
        btn = QPushButton(label.replace("&", "&&"))
        btn.setObjectName("kbDone" if key == DONE else "kbFn" if is_fn else "kbKey")
        if key == SHIFT:
            btn.setProperty("active", self._shift)
        btn.setFocusPolicy(Qt.NoFocus)  # 입력란의 포커스를 뺏지 않는다
        btn.setFixedHeight(self._key_height)
        if key == BS:
            btn.setAutoRepeat(True)
            btn.setAutoRepeatDelay(400)
            btn.setAutoRepeatInterval(60)
            btn.clicked.connect(lambda _=False: self.press(BS))
        else:
            btn.clicked.connect(lambda _=False, k=key: self.press(k))
        return btn
