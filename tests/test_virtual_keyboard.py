import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QLineEdit, QWidget

from app.ui.virtual_keyboard import BS, DONE, SHIFT, SPACE, SYM, VirtualKeyboard

app = QApplication.instance() or QApplication(sys.argv)


def make():
    host = QWidget()
    host.resize(1280, 800)
    edit = QLineEdit(host)
    kb = VirtualKeyboard(host)
    kb._target = edit
    return host, edit, kb


def test_type_and_backspace():
    _, edit, kb = make()
    for k in "ab1":
        kb.press(k)
    kb.press(SPACE)
    kb.press("@")
    assert edit.text() == "ab1 @"
    kb.press(BS)
    assert edit.text() == "ab1 "


def test_shift_is_one_shot():
    _, edit, kb = make()
    kb.press(SHIFT)
    kb.press("a")
    kb.press("b")
    assert edit.text() == "Ab"


def test_symbol_layer_and_ampersand_label():
    _, edit, kb = make()
    kb.press(SYM)
    kb.press("&")
    assert edit.text() == "&"
    labels = [b.text() for b in kb.findChildren(__import__("PyQt5.QtWidgets", fromlist=["QPushButton"]).QPushButton)]
    assert "&&" in labels  # 니모닉 방지로 이스케이프됨


def test_done_hides_and_ignores_without_target():
    host, edit, kb = make()
    host.show()
    kb.show_keyboard()
    assert kb.isVisible()
    kb.press(DONE)
    assert not kb.isVisible()
    kb.press("a")  # 대상 없음: 예외 없이 무시
    assert edit.text() == ""


def test_geometry_at_bottom():
    host, _, kb = make()
    kb.reposition()
    g = kb.geometry()
    assert g.bottom() == 799 and g.width() == 1280


def test_hangul_typing_in_line_edit():
    from app.ui.virtual_keyboard import LANG
    _, edit, kb = make()
    kb.press(LANG)  # 한글 레이어
    for k in "ㅎㅏㄴㄱㅡㄹ":
        kb.press(k)
    assert edit.text() == "한글"
    kb.press(BS)
    assert edit.text() == "한그"
    kb.press(SPACE)
    for k in "ㅇㅏㄴㅏ":
        kb.press(k)
    assert edit.text() == "한그 아나"


def test_hangul_shift_and_mixed_input():
    from app.ui.virtual_keyboard import LANG
    _, edit, kb = make()
    kb.press(LANG)
    kb.press(SHIFT)
    kb.press("ㅂ")      # ㅃ
    kb.press("ㅏ")
    kb.press("1")      # 숫자는 조합을 끊고 그대로 입력
    kb.press("ㅏ")
    assert edit.text() == "빠1ㅏ"
    kb.press(LANG)      # 영문으로
    kb.press("a")
    assert edit.text().endswith("a")


def test_hangul_resets_when_cursor_moved():
    from app.ui.virtual_keyboard import LANG
    _, edit, kb = make()
    kb.press(LANG)
    for k in "ㅎㅏ":
        kb.press(k)
    edit.setCursorPosition(0)  # 사용자가 커서를 옮김
    kb.press("ㄴ")
    assert edit.text() == "ㄴ하"
