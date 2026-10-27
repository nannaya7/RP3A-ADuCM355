"""확인 팝업. 화면 테마(theme.qss 의 QMessageBox)에 맞춘 한국어 버튼을 쓴다."""
from PyQt5.QtWidgets import QMessageBox


def confirm(parent, title: str, text: str, yes: str = "예", no: str = "아니오") -> bool:
    """예/아니오 확인. 실수로 누르기 쉬운 쪽이 실행되지 않게 기본(엔터) 버튼은 '아니오' 이고, '예' 는 강조색으로 보인다."""
    box = QMessageBox(QMessageBox.Question, title, text, QMessageBox.NoButton, parent)
    yes_btn = box.addButton(yes, QMessageBox.AcceptRole)
    no_btn = box.addButton(no, QMessageBox.RejectRole)
    yes_btn.setProperty("primary", True)
    yes_btn.style().unpolish(yes_btn)
    yes_btn.style().polish(yes_btn)
    box.setDefaultButton(no_btn)
    box.setEscapeButton(no_btn)
    box.exec_()
    answered = box.clickedButton() is yes_btn
    box.deleteLater()
    return answered
