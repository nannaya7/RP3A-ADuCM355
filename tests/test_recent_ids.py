"""최근 로그인 ID: 저장 목록(최대 5개)과 로그인 화면의 펼침 목록."""
import json

from PyQt5.QtCore import QCoreApplication, Qt
from PyQt5.QtTest import QTest

from app.auth.recent_ids import RecentIds


def _dispose(page):
    """펼침 목록(최상위 팝업)이 창보다 먼저 지워져 나중에 비정상 종료하지 않게, 창과 같이 바로 정리한다."""
    page.email.edit.completer().popup().hide()
    page.close()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, 0)


def test_newest_first_deduped_and_capped_at_five(tmp_path):
    r = RecentIds(tmp_path / "r.json")
    for i in "abcdef":
        r.add(f"{i}@x.com")
    assert r.all() == ["f@x.com", "e@x.com", "d@x.com", "c@x.com", "b@x.com"]          # 가장 오래된 a 는 빠진다
    r.add("C@X.com")                                                                   # 이미 있으면 끌어올린다 (대소문자 무시)
    assert r.all()[:3] == ["C@X.com", "f@x.com", "e@x.com"] and len(r.all()) == 5
    r.add("   ")
    assert len(r.all()) == 5


def test_saved_and_reloaded_without_any_password(tmp_path):
    p = tmp_path / "r.json"
    RecentIds(p).add("a@x.com")
    assert RecentIds(p).all() == ["a@x.com"]
    assert set(json.loads(p.read_text(encoding="utf-8"))) == {"ids"}


def test_unreadable_file_starts_empty_and_login_still_works(tmp_path):
    p = tmp_path / "r.json"
    p.write_text("{not json", encoding="utf-8")
    r = RecentIds(p)
    assert r.all() == []
    r.add("a@x.com")
    assert RecentIds(p).all() == ["a@x.com"]


def test_login_page_lists_recent_ids_when_the_id_field_is_focused(qapp_or_none=None):
    from app.ui.login_page import LoginPage
    page = LoginPage(portrait=True)
    page.resize(480, 800)
    page.show()
    page.set_recent_ids(["a@x.com", "b@x.com"])
    page.email.edit.setFocus(Qt.MouseFocusReason)
    QTest.qWait(80)
    comp = page.email.edit.completer()
    assert comp.popup().isVisible() and comp.completionModel().rowCount() == 2
    comp.popup().hide()
    page.email.edit.setText("b")                                       # 글자를 치면 앞부분이 같은 것만
    comp.setCompletionPrefix("b")
    assert comp.completionCount() == 1
    _dispose(page)


def test_login_page_without_recent_ids_shows_no_popup():
    from app.ui.login_page import LoginPage
    page = LoginPage(portrait=False)
    page.show()
    page.email.edit.setFocus(Qt.MouseFocusReason)
    QCoreApplication.processEvents()
    assert not page.email.edit.completer().popup().isVisible()
    _dispose(page)
