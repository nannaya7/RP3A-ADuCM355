"""세로 측정 화면(프로필 선택/단계 줄), 프로필 저장소·편집 화면, 검사 이력 화면."""
import dataclasses
import json

import pytest
from PyQt5.QtGui import QFont
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox

from app.app_window import AppWindow
from app.config import Config
from app.display import PORTRAIT
from app.measure.patient import PatientProfile
from app.measure.profiles import ProfileStore
from app.ui.theme import load_fonts, load_stylesheet

app = QApplication.instance()


@pytest.fixture(scope="module", autouse=True)
def styled():
    load_fonts()
    app.setFont(QFont("Pretendard", 10))
    app.setStyleSheet(load_stylesheet())
    yield
    app.setStyleSheet("")


def wait(cond, ms=6000):
    for _ in range(ms // 20):
        QTest.qWait(20)
        if cond():
            return True
    return False


def make(tmp_path, names=("김민수", "이서연", "김하준"), **kw):
    kw.setdefault("reaction_wait_s", 1)
    cfg = dataclasses.replace(Config(), uart_mock=True, net_mock=True, results_dir=str(tmp_path / "res"), **kw)
    win = AppWindow(PORTRAIT, cfg)
    win.profiles = win.measure._store = win.profile_edit._store = ProfileStore(tmp_path / "profiles.json")
    for n in names:
        win.profiles.add(PatientProfile(n, "남성", 40, 70.0))
    win.measure.refresh_profiles()
    win.show()
    win.start_uart()
    assert wait(lambda: win.client.connected)
    win._on_skip()
    assert wait(lambda: win.controller.state == "ready")
    return win


def run_stage(win, n_done):
    d = win.measure
    assert wait(lambda: d.primary_btn.isEnabled(), 8000)
    d.primary_btn.click()
    assert wait(lambda: len(win.controller._done) == n_done, 15000)


# ---------------- 구성 ----------------
def test_layout_fits_480x800_and_sections_visible(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        assert (win.width(), win.height()) == (480, 800)
        for w in (d.tab_tro, d.tab_nt, d.clock, d.profile_scroll, d.res_value, d.reset_btn, d.stop_btn,
                  d.monitor_btn, d.history_btn, *d.steps):
            assert w.isVisible()
        for w in (d.history_btn, d.steps[2], d.monitor_btn):
            r = w.mapTo(win, w.rect().bottomRight())
            assert r.x() <= 480 and r.y() <= 800, w
        g = win.gear.geometry()
        assert win.gear.isVisible() and g.top() < 40 and 480 - g.right() < 30
        assert d.clock.mapTo(win, d.clock.rect().topRight()).x() <= g.left()          # 날짜/시간이 설정 버튼과 겹치지 않는다
        assert [r.name.text() for r in d.steps] == ["1단계. 시료준비", "2단계. 혈액투입", "3단계. 세척후 검증"]
    finally:
        win.shutdown()


def test_history_button_is_as_tall_as_device_status_card(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        dev_card = d.dev_icons["device"].parentWidget()
        while dev_card is not None and dev_card.objectName() != "dashCard":
            dev_card = dev_card.parentWidget()
        assert dev_card is not None
        top = lambda w: w.mapTo(win, w.rect().topLeft()).y()
        assert d.history_btn.height() == dev_card.height() and top(d.history_btn) == top(dev_card)
    finally:
        win.shutdown()


def test_profile_cards_select_toggle_and_hint(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        ids = [sp.id for sp in win.profiles.all()]
        assert len(d._cards) == 3 and not d.edit_btn.isVisible() and "선택하세요" in d.profile_hint.text()
        d.select_profile(ids[0])
        assert d._cards[ids[0]].property("selected") is True and d.edit_btn.isVisible()
        assert "김민수" in d.profile_hint.text() and win.controller.patient["name"] == "김민수"
        d.select_profile(ids[1])                                       # 다른 사람을 고르면 바뀐다
        assert d._cards[ids[0]].property("selected") is False and win.controller.patient["name"] == "이서연"
        d.select_profile(ids[1])                                       # 다시 누르면 해제
        assert d.selected_profile() is None and win.controller.patient == {}
    finally:
        win.shutdown()


# ---------------- 시작 조건 / 저장 ----------------
def test_start_needs_a_selected_profile(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        assert d.steps[0].btn.text() == "1단계 시작" and d.steps[0].btn.isEnabled()
        d.primary_btn.click()
        QTest.qWait(100)
        assert not win.controller._cur and not win.controller._done
        assert d.banner.isVisible() and "프로필을 선택" in d.banner.text()
        assert d.profile_card_frame.property("error") is True
        d.select_profile(win.profiles.all()[0].id)
        assert d.profile_card_frame.property("error") is False and "프로필" not in d.banner.text()
        d.primary_btn.click()
        assert wait(lambda: bool(win.controller._cur) or bool(win.controller._done), 8000)
    finally:
        win.shutdown()


def test_require_patient_off_allows_start_without_profile(tmp_path):
    win = make(tmp_path, require_patient=False)
    try:
        win.measure.primary_btn.click()
        assert wait(lambda: bool(win.controller._cur) or bool(win.controller._done), 8000)
    finally:
        win.shutdown()


def test_full_run_saves_profile_and_new_run_clears_selection(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        d.select_profile(win.profiles.all()[1].id)
        for n in (1, 2, 3):
            run_stage(win, n)
        assert wait(lambda: win.controller.state == "done", 8000)
        sess = next((tmp_path / "res").iterdir())
        res = json.loads((sess / "result.json").read_text(encoding="utf-8"))
        assert res["patient"]["name"] == "이서연"
        assert d.res_value.text() != "—" and d.done_badge.isVisible()
        assert [s.badge.text() for s in d.steps] == ["완료", "완료", "검증 완료"]
        assert d.steps[2].btn.text() == "새 측정" and d.steps[2].btn.isEnabled()
        assert not d.steps[0].btn.isVisible() and not d.steps[1].btn.isVisible()
        d.primary_btn.click()
        QTest.qWait(100)
        assert d.selected_profile() is None and win.controller.patient == {}
    finally:
        win.shutdown()


def test_step_buttons_follow_state_and_waiting_timer(tmp_path):
    win = make(tmp_path, reaction_wait_s=3)
    try:
        d = win.measure
        d.select_profile(win.profiles.all()[0].id)
        assert [r.btn.isEnabled() for r in d.steps] == [True, False, False]
        run_stage(win, 1)
        assert wait(lambda: d.steps[1].badge.text() == "반응 중", 4000)
        assert not d.steps[0].btn.isVisible()                                   # 끝난 단계의 버튼은 숨긴다
        assert d.steps[1].btn.text() == "2단계 시작" and not d.steps[1].btn.isEnabled()
        assert d.steps[1].prog.isVisible() and "/ 00:03" in d.steps[1].time.text()
        assert wait(lambda: d.steps[1].btn.isEnabled(), 6000)
    finally:
        win.shutdown()


def test_tab_nt_and_buttons(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        d.tab_nt.click()
        assert win.controller.assay == "ntprobnp" and d.tab_nt.property("active") is True
        d.monitor_btn.click()
        assert win.currentWidget() is win.monitor
        win.monitor.back_btn.click()
        assert win.currentWidget() is win.measure
        d.back_btn.click()
        assert win.currentWidget() is win.login
    finally:
        win.shutdown()


def test_device_status_icons(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        assert [d.dev_labels[k].text() for k in ("device", "kit", "link")] == ["장비 정상", "키트 정상", "연결 정상"]
        assert d.dev_icons["device"].state == "ok"
    finally:
        win.shutdown()


# ---------------- 프로필 저장소 ----------------
def test_store_add_update_delete_persist_and_reload(tmp_path):
    path = tmp_path / "d" / "profiles.json"
    st = ProfileStore(path)
    a = st.add(PatientProfile("김민수", "남성", 58, 72.0, 120, 80, 98.0, ["고혈압"]))
    b = st.add(PatientProfile("이서연", "여성", 54, 58.0))
    assert [x.name for x in ProfileStore(path).all()] == ["김민수", "이서연"]
    assert st.update(a, PatientProfile("김민수", "남성", 59, 72.0))
    assert ProfileStore(path).get(a).profile.age == 59
    assert st.delete(b) and not st.delete(b)
    assert [x.name for x in ProfileStore(path).all()] == ["김민수"]
    assert not list(path.parent.glob("*.tmp"))


def test_store_survives_corrupt_file(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text("{not json", encoding="utf-8")
    st = ProfileStore(path)
    assert st.all() == [] and (tmp_path / "profiles.bad").exists()
    st.add(PatientProfile("a", "남성", 1, 1.0))
    assert len(ProfileStore(path).all()) == 1
    path.write_text(json.dumps({"profiles": [{"id": "x", "name": ""}, {"name": "no id"}]}), encoding="utf-8")
    assert ProfileStore(path).all() == []


# ---------------- 프로필 편집 ----------------
def test_add_profile_flow_validates_then_saves_and_selects(tmp_path):
    win = make(tmp_path, names=())
    try:
        d, e = win.measure, win.profile_edit
        assert len(d._cards) == 0 and len(d._cards_row) >= 1
        d.profileEditRequested.emit("")                                 # [+ 추가] 카드
        assert win.currentWidget() is e and e.title.text() == "프로필 추가" and not e.delete_btn.isVisible()
        assert not win.gear.isVisible()
        e.save_btn.click()                                              # 비어 있으면 저장 안 됨
        assert e.msg.isVisible() and "성명" in e.msg.text() and e.f_name.property("error") is True
        e.f_name.setText("박지민")
        e.f_sex.setCurrentIndex(2)
        e.f_age.edit.setText("33")
        e.f_weight.edit.setText("61.5")
        e.f_chronic.set_selected(["당뇨병"])
        assert e.f_name.property("error") is False
        e.save_btn.click()
        assert win.currentWidget() is win.measure
        sp = win.profiles.all()[0]
        assert (sp.name, sp.profile.sex, sp.profile.age, sp.profile.weight, sp.profile.chronic) == (
            "박지민", "여성", 33, 61.5, ["당뇨병"])
        assert d.selected_profile().name == "박지민" and win.controller.patient["age"] == 33    # 저장 즉시 선택
    finally:
        win.shutdown()


def test_duplicate_name_is_rejected(tmp_path):
    win = make(tmp_path)
    try:
        e = win.profile_edit
        e.open_new()
        e.f_name.setText("김민수")
        e.f_sex.setCurrentIndex(1)
        e.f_age.edit.setText("20")
        e.f_weight.edit.setText("60")
        e.save_btn.click()
        assert "같은 이름" in e.msg.text() and len(win.profiles.all()) == 3
    finally:
        win.shutdown()


def test_edit_existing_profile_and_cancel(tmp_path):
    win = make(tmp_path)
    try:
        d, e = win.measure, win.profile_edit
        pid = win.profiles.all()[0].id
        d.select_profile(pid)
        d.edit_btn.click()
        assert win.currentWidget() is e and e.title.text() == "프로필 편집" and e.f_name.text() == "김민수"
        assert e.delete_btn.isVisible() and e.f_sex.currentText() == "남성" and e.f_age.text() == "40"
        e.f_age.edit.setText("41")
        e.back_btn.click()                                               # 취소: 바뀌지 않는다
        assert win.currentWidget() is win.measure and win.profiles.get(pid).profile.age == 40
        d.edit_btn.click()
        e.f_age.edit.setText("41")
        e.save_btn.click()
        assert win.profiles.get(pid).profile.age == 41 and d.selected_profile().age == 41
    finally:
        win.shutdown()


def test_delete_profile_clears_selection(tmp_path, monkeypatch):
    win = make(tmp_path)
    try:
        d, e = win.measure, win.profile_edit
        pid = win.profiles.all()[0].id
        d.select_profile(pid)
        d.edit_btn.click()
        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
        e.delete_btn.click()
        assert win.profiles.get(pid) is not None and win.currentWidget() is e
        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
        e.delete_btn.click()
        assert win.profiles.get(pid) is None and win.currentWidget() is win.measure
        assert d.selected_profile() is None and len(d._cards) == 2
    finally:
        win.shutdown()


def test_long_press_on_card_opens_editor(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        pid = win.profiles.all()[2].id
        got = []
        d.profileEditRequested.connect(got.append)
        d._cards[pid]._on_hold()
        assert got == [pid]
    finally:
        win.shutdown()


def test_edit_page_keyboard_makes_room_for_last_fields(tmp_path):
    win = make(tmp_path)
    try:
        e = win.profile_edit
        e.open_new()
        win.go_to(e)
        QTest.qWait(80)
        e.on_keyboard(True, 319)
        QTest.qWait(150)
        assert e._pad.height() == 319 and not e.actions.isVisible()
        e.on_keyboard(False, 0)
        assert e._pad.height() == 0 and e.actions.isVisible()
    finally:
        win.shutdown()


# ---------------- 이력 ----------------
def test_history_page_lists_saved_results(tmp_path):
    win = make(tmp_path)
    try:
        res = tmp_path / "res"
        for i, v in enumerate((0.018, 0.156)):
            d = res / f"2026102{i}_090000_troponin"
            d.mkdir(parents=True)
            (d / "summary.json").write_text(json.dumps({"finished_at": f"2026-10-2{i}T09:00:00", "title": "Troponin I",
                                                        "value": v}), encoding="utf-8")
        win.measure.history_btn.click()
        assert win.currentWidget() is win.history_page and not win.gear.isVisible()
        assert win.history_page.table.rowCount() == 2 and "2건" in win.history_page.count.text()
        assert win.history_page.table.item(0, 0).text().startswith("2026. 10. 21")          # 최신 순
        win.history_page.back_btn.click()
        assert win.currentWidget() is win.measure
    finally:
        win.shutdown()
