"""가로 측정 화면(대시보드): 환자 프로필 검증, 단계 카드, 결과/이력, 장비 상태."""
import dataclasses
import json
from datetime import datetime

import pytest
from PyQt5.QtGui import QFont
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.app_window import AppWindow
from app.config import Config
from app.display import LANDSCAPE, PORTRAIT
from app.measure.history import classify, format_value, load_history
from app.measure.patient import PatientProfile
from app.ui.dashboard_logic import DeviceView
from app.ui.dashboard_page import DashboardPage, korean_datetime
from app.ui.dashboard_portrait import PortraitDashboard
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


def make(tmp_path, **kw):
    kw.setdefault("reaction_wait_s", 1)
    cfg = dataclasses.replace(Config(), uart_mock=True, net_mock=True, results_dir=str(tmp_path / "res"), **kw)
    win = AppWindow(LANDSCAPE, cfg)
    win.show()
    win.start_uart()
    assert wait(lambda: win.client.connected)
    win._on_skip()
    assert wait(lambda: win.controller.state == "ready")
    return win


def fill(d: DashboardPage, name="김민수"):
    d.f_name.setText(name)
    d.f_sex.setCurrentIndex(1)
    d.f_age.edit.setText("58")
    d.f_weight.edit.setText("72")


def run_stage(d: DashboardPage, win, n_done):
    d.primary_btn.click()
    assert wait(lambda: len(win.controller._done) == n_done, 15000)


# ---------------- 선택 / 구성 ----------------
def test_landscape_and_portrait_use_their_own_dashboards(tmp_path):
    win = make(tmp_path)
    try:
        assert isinstance(win.measure, DashboardPage)
    finally:
        win.shutdown()
    cfg = dataclasses.replace(Config(), uart_mock=True, net_mock=True, results_dir=str(tmp_path / "r2"))
    p = AppWindow(PORTRAIT, cfg)
    try:
        assert isinstance(p.measure, PortraitDashboard)
    finally:
        p.shutdown()


def test_dashboard_has_all_sections_and_fits_screen(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        for w in (d.f_name, d.f_sex, d.f_age, d.f_weight, d.f_sys, d.f_glu, d.f_chronic, d.res_value, d.history,
                  d.dev_icons["device"], d.primary_btn, d.stop_btn, d.reset_btn, d.monitor_btn, d.tab_tro, d.tab_nt, d.clock):
            assert w.isVisible()
        assert len(d.steps) == 3
        for w in (d.history, d.primary_btn, d.steps[0]):
            r = w.mapTo(win, w.rect().bottomRight())
            assert r.x() <= 1280 and r.y() <= 800
        assert d.steps[0].name.text() == "1단계. 시료준비" and d.steps[1].name.text() == "2단계. 혈액투입"
        assert d.steps[2].name.text() == "3단계. 세척후 검증"
    finally:
        win.shutdown()


def test_right_column_cards_share_the_same_left_edge(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        def card_of(w):
            while w is not None and w.objectName() != "dashCard":
                w = w.parentWidget()
            return w
        cards = [card_of(w) for w in (d.res_title, d.dev_icons["device"], d.history)]
        assert all(c is not None for c in cards)
        xs = {c.mapTo(win, c.rect().topLeft()).x() for c in cards}
        assert len(xs) == 1, xs                                    # 검사 결과 / 장비 상태 / 검사 이력
    finally:
        win.shutdown()


def test_device_status_is_three_icons_like_the_portrait_screen(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        assert list(d.dev_icons) == ["device", "kit", "link"] and [i.kind for i in d.dev_icons.values()] == ["power", "strip", "wifi"]
        assert all(i.isVisible() and i.width() >= 48 for i in d.dev_icons.values())      # 가로 화면은 세로보다 큰 아이콘
        assert wait(lambda: d.dev_labels["device"].text() in ("장비 정상", "모듈 없음"), 4000)
        # 모듈이 없으면 장비와 키트는 문제(빨강), 연결 상태는 따로 표시된다
        d._render_device(DeviceView("연결 안 됨", 0, 3, "확인 불가", "bad", 0, 3, "FW ?", device_ok=False, link_ok=False))
        assert [d.dev_labels[k].text() for k in ("device", "kit", "link")] == ["모듈 없음", "키트 확인 불가", "연결 끊김"]
        assert [i.state for i in d.dev_icons.values()] == ["bad", "bad", "bad"]
        d._render_device(DeviceView("대기", 0, 3, "신호 포화 주의", "warn", 0, 3, "FW 1.0", device_ok=True, link_ok=True))
        assert [i.state for i in d.dev_icons.values()] == ["ok", "warn", "ok"] and d.dev_labels["kit"].text() == "신호 포화"
        assert d.dev_icons["device"].toolTip() == "FW 1.0"                                  # 모듈 정보는 툴팁
    finally:
        win.shutdown()


def test_clock_format_korean():
    assert korean_datetime(datetime(2024, 5, 14, 15, 27)) == "2024년 5월 14일 (화)  오후 03:27"
    assert korean_datetime(datetime(2024, 5, 14, 0, 5)).endswith("오전 12:05")


# ---------------- 환자 프로필 ----------------
def test_patient_profile_parsing_and_required_fields():
    p = PatientProfile.from_texts("  김민수 ", "남성", "58", "72.5", "120", "80", "98", ["고혈압"])
    assert (p.name, p.sex, p.age, p.weight, p.bp_sys, p.bp_dia, p.glucose, p.chronic) == (
        "김민수", "남성", 58, 72.5, 120, 80, 98.0, ["고혈압"])
    assert p.is_complete()
    q = PatientProfile.from_texts("", "선택", "abc", "0", "", "", "", [])
    assert set(q.missing()) == {"name", "sex", "age", "weight"}              # 숫자가 아니거나 범위 밖이면 비어 있는 것
    assert PatientProfile.from_texts("a", "여성", "200", "70").missing() == ["age"]


def test_start_is_blocked_until_required_fields_are_filled(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        d.primary_btn.click()
        QTest.qWait(100)
        assert win.controller.state == "ready" and not win.controller._done          # 시작되지 않았다
        assert d.banner.isVisible() and "성명" in d.banner.text() and "몸무게" in d.banner.text()
        assert d.f_name.property("error") is True and d.f_age.property("error") is True
        fill(d)
        assert d.f_name.property("error") is False and d.f_age.property("error") is False
        assert not d.banner.isVisible() or "필수 정보" not in d.banner.text()
        d.primary_btn.click()
        assert wait(lambda: win.controller.state in ("measuring", "configuring", "ready") and bool(win.controller._cur))
    finally:
        win.shutdown()


def test_require_patient_can_be_turned_off(tmp_path):
    win = make(tmp_path, require_patient=False)
    try:
        win.measure.primary_btn.click()
        assert wait(lambda: bool(win.controller._cur) or bool(win.controller._done), 8000)
    finally:
        win.shutdown()


def test_patient_is_saved_in_result_and_summary(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        fill(d)
        d.f_chronic.set_selected(["고혈압", "당뇨병"])
        for n in (1, 2, 3):
            run_stage(d, win, n)
            if n < 3:
                assert wait(lambda: win.controller.state == "ready" and d.primary_btn.isEnabled(), 8000)
        assert wait(lambda: win.controller.state == "done", 8000)
        sess = next((tmp_path / "res").iterdir())
        res = json.loads((sess / "result.json").read_text(encoding="utf-8"))
        summ = json.loads((sess / "summary.json").read_text(encoding="utf-8"))
        assert res["patient"]["name"] == "김민수" and res["patient"]["chronic"] == ["고혈압", "당뇨병"]
        assert summ["patient"]["age"] == 58 and summ["title"] == "Troponin" and summ["value"] is not None
        # 결과 카드, 단계 카드, 장비 상태
        assert d.res_value.text() != "—" and d.done_badge.isVisible()
        assert [s.badge.text() for s in d.steps] == ["완료", "완료", "검증 완료"]
        assert [d.dev_labels[k].text() for k in ("device", "kit", "link")] == ["장비 정상", "키트 정상", "연결 정상"]
        assert d.info_done.text() != "—" and d.primary_btn.text() == "새 측정"
        # 이력에 방금 검사가 올라온다
        assert wait(lambda: d.history.rowCount() == 1, 3000)
        # 새 측정: 이전 환자 정보를 지운다
        d.primary_btn.click()
        QTest.qWait(100)
        assert d.f_name.text() == "" and d.f_sex.currentIndex() == 0 and win.controller.patient["name"] == ""
    finally:
        win.shutdown()


# ---------------- 단위 / 참고 범위 ----------------
def test_no_reference_range_means_no_judgement(tmp_path):
    win = make(tmp_path)                                         # 기본: 단위 pg/mL, 참고 범위 없음
    try:
        d = win.measure
        assert d.res_ref.text() == "미설정" and d.res_unit.text() == "pg/mL"
        fill(d)
        for n in (1, 2, 3):
            run_stage(d, win, n)
            if n < 3:
                assert wait(lambda: d.primary_btn.isEnabled() and win.controller.state == "ready", 8000)
        assert wait(lambda: win.controller.state == "done", 8000)
        assert not d.res_status.isVisible()                      # 정상/주의를 표시하지 않는다
    finally:
        win.shutdown()


def test_reference_range_and_unit_when_configured(tmp_path):
    win = make(tmp_path, result_unit="ng/mL", ref_low=0.0, ref_high=0.04)
    try:
        d = win.measure
        assert d.res_unit.isVisible() and d.res_unit.text() == "ng/mL"
        assert d.res_ref.text() == "0.000 – 0.040 ng/mL"
    finally:
        win.shutdown()


def test_classify_and_format_value():
    assert classify(0.02, 0.0, 0.04) == "정상" and classify(0.5, 0.0, 0.04) == "주의"
    assert classify(None, 0.0, 0.04) == "판정불가" and classify(5.0, None, None) == ""
    assert classify(-1.0, 0.0, 0.04) == "주의"
    assert format_value(0.042) == "0.042" and format_value(3.456) == "3.46" and format_value(123.44) == "123.4"
    assert format_value(None) == "—"


# ---------------- 이력 ----------------
def test_history_reads_summaries_newest_first_and_skips_incomplete(tmp_path):
    def mk(name, value, when, ref_high=0.04):
        d = tmp_path / name
        d.mkdir()
        (d / "summary.json").write_text(json.dumps({"finished_at": when, "title": "Troponin I", "value": value,
                                                    "unit": "ng/mL", "ref_low": 0.0, "ref_high": ref_high}),
                                        encoding="utf-8")
    mk("20241010_084200_troponin", 0.018, "2024-10-10T08:42:00")
    mk("20241013_101800_troponin", 0.156, "2024-10-13T10:18:00")
    mk("20241014_152500_troponin", 0.042, "2024-10-14T15:25:00")
    (tmp_path / "20241015_000000_troponin").mkdir()                     # 끝나지 않은 검사 (summary 없음)
    bad = tmp_path / "20241016_000000_troponin"
    bad.mkdir()
    (bad / "summary.json").write_text("{broken", encoding="utf-8")
    items = load_history(tmp_path)
    assert [i.when.day for i in items] == [14, 13, 10]
    assert [i.status for i in items] == ["주의", "주의", "정상"]
    assert load_history(tmp_path / "none") == []
    assert len(load_history(tmp_path, limit=2)) == 2


def test_history_table_renders_rows(tmp_path):
    d = tmp_path / "20241014_152500_troponin"
    d.mkdir()
    (d / "summary.json").write_text(json.dumps({"finished_at": "2024-10-14T15:25:00", "title": "Troponin I",
                                                "value": 0.042, "unit": "ng/mL", "ref_high": 0.04}), encoding="utf-8")
    page = DashboardPage(dataclasses.replace(Config(), result_unit="ng/mL", ref_high=0.04), results_dir=tmp_path)
    page.resize(1280, 800)
    page.show()
    assert page.history.rowCount() == 1
    assert page.history.item(0, 0).text() == "2024. 10. 14  15:25"
    assert page.history.item(0, 2).text() == "0.042 ng/mL"
    assert page.history.cellWidget(0, 3).findChild(type(page.res_status)).text() == "주의"


# ---------------- 단계 카드 ----------------
def test_step_cards_follow_states(tmp_path):
    win = make(tmp_path, reaction_wait_s=3)
    try:
        d = win.measure
        assert [s.badge.text() for s in d.steps] == ["시작 대기", "대기", "대기"]
        assert d.steps[0].property("active") is True and d.steps[1].property("active") is False
        fill(d)
        run_stage(d, win, 1)
        assert wait(lambda: d.steps[1].badge.text() == "반응 중", 4000)       # 타이머가 도는 동안
        assert d.steps[0].badge.text() == "완료" and d.steps[1].prog.isVisible()
        assert "/ 00:03" in d.steps[1].time.text() and not d.primary_btn.isEnabled()
        assert wait(lambda: d.primary_btn.isEnabled(), 6000)                  # 타이머 후 시작 버튼 활성화
        assert d.steps[1].badge.text() == "시작 대기"
    finally:
        win.shutdown()


def test_nt_probnp_tab_switches_the_model_and_the_result_card(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        assert win.controller.assay == "troponin"
        d.tab_nt.click()
        assert win.controller.assay == "ntprobnp"
        assert d.tab_nt.property("active") is True and d.tab_tro.property("active") is False
        assert d.res_title.text() == "NT-proBNP" and d.res_unit.text() == "pg/mL"
        assert win.controller.meta["title"] == "NT-proBNP"
        d.tab_tro.click()
        assert win.controller.assay == "troponin" and d.res_title.text() == win._base_cfg.result_title
    finally:
        win.shutdown()


def test_assay_choice_is_refused_midway_and_remembered(tmp_path):
    win = make(tmp_path)
    try:
        win.controller._done[0] = {0: []}                       # 1단계를 끝낸 상태
        win.measure.tab_nt.click()
        assert win.controller.assay == "troponin" and "바꿀 수 없습니다" in win.measure.banner.text()
        win.controller._done.clear()
        win.measure.tab_nt.click()
        assert win._load_assay() == "ntprobnp"                  # 파일에 저장돼 다음 실행에도 유지
    finally:
        win.shutdown()


def test_monitor_and_back_buttons_still_work(tmp_path):
    win = make(tmp_path)
    try:
        win.measure.monitor_btn.click()
        assert win.currentWidget() is win.monitor
        win.monitor.back_btn.click()
        assert win.currentWidget() is win.measure
        win.measure.back_btn.click()
        assert win.currentWidget() is win.login
    finally:
        win.shutdown()


def test_stop_and_reset_buttons_state(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        assert not d.stop_btn.isEnabled() and not d.reset_btn.isEnabled()
    finally:
        win.shutdown()


def test_history_tab_opens_the_history_page_and_back_returns(tmp_path):
    win = make(tmp_path)
    try:
        win.measure.tab_hist.click()
        assert win.currentWidget() is win.history_page
        win.history_page.back_btn.click()
        assert win.currentWidget() is win.measure
        assert win.controller.assay == "troponin"                   # 이력 탭은 검사 항목을 바꾸지 않는다
    finally:
        win.shutdown()


# ---------------- 검사 이력 찾기 ----------------
def _item(day, hour, title="Troponin", value=1.0, status="정상", patient="김철수"):
    from datetime import datetime
    from app.measure.history import HistoryItem
    return HistoryItem(datetime(2026, 10, day, hour, 30), title, value, status, "", patient)


def test_find_history_searches_names_dates_and_values():
    from app.measure.history import find_history
    items = [_item(25, 9, patient="김철수"), _item(26, 10, "NT-proBNP", 212.5, "주의", "이영희"),
             _item(27, 11, "Troponin", None, "판정불가", "김철수")]
    assert [i.patient for i in find_history(items, "이영희")] == ["이영희"]
    assert len(find_history(items, "김철수")) == 2
    assert len(find_history(items, "10월 26일")) == 1 and len(find_history(items, "2026-10-27")) == 1
    assert len(find_history(items, "212")) == 1
    assert len(find_history(items, "김철수 판정불가")) == 1            # 낱말은 모두 들어 있어야 한다
    assert find_history(items, "없는사람") == []


def test_find_history_filters_by_assay_and_status_and_sorts():
    from app.measure.history import find_history
    items = [_item(25, 9, value=5.0), _item(26, 10, "NT-proBNP", 212.5, "주의"), _item(27, 11, value=None, status="판정불가"),
             _item(28, 12, value=9.0)]
    assert [i.title for i in find_history(items, title="NT-proBNP")] == ["NT-proBNP"]
    assert [i.status for i in find_history(items, status="주의")] == ["주의"]
    assert [i.when.day for i in find_history(items)] == [28, 27, 26, 25]                     # 최신순이 기본
    assert [i.when.day for i in find_history(items, sort="오래된순")] == [25, 26, 27, 28]
    assert [i.when.day for i in find_history(items, sort="결과 높은순")] == [26, 28, 25, 27]   # 값 없는 기록은 맨 뒤
    assert [i.when.day for i in find_history(items, sort="결과 낮은순")] == [25, 28, 26, 27]


def test_history_page_search_filter_and_reset(tmp_path):
    import json
    from app.ui.history_page import HistoryPage
    for n, (day, title, value, name) in enumerate([(25, "Troponin", 5.0, "김철수"), (26, "NT-proBNP", 212.5, "이영희"),
                                                   (27, "Troponin", 9.0, "이영희")]):
        d = tmp_path / f"2026102{day - 20}_000000_x{n}"
        d.mkdir()
        (d / "summary.json").write_text(json.dumps({
            "finished_at": f"2026-10-{day}T09:00:00", "title": title, "value": value, "unit": "",
            "patient": {"name": name}}), encoding="utf-8")
    page = HistoryPage(tmp_path)
    page.refresh()
    assert page.table.rowCount() == 3 and "전체 3건" in page.count.text()
    page.search.edit.setText("이영희")
    assert page.table.rowCount() == 2 and "검색 결과 2건" in page.count.text()
    page.chips[2][1].click()                                              # NT-proBNP
    assert page.table.rowCount() == 1
    page.sort_btn.click()
    assert page.sort_btn.text() == "정렬: 오래된순"
    page.reset_btn.click()
    assert page.table.rowCount() == 3 and page.query == "" and page.sort_btn.text() == "정렬: 최신순"
    page.search.edit.setText("없는사람")
    assert page.table.rowCount() == 0 and "맞는 기록이 없습니다" in page.count.text()


def test_cortisol_tab_shows_the_troponin_like_screen_without_a_model(tmp_path):
    win = make(tmp_path)
    try:
        d = win.measure
        d.tab_cor.click()
        assert win.controller.assay == "cortisol" and d.tab_cor.property("active") is True
        assert d.tab_tro.property("active") is False and d.res_title.text() == "Cortisol"
        assert win._load_assay() == "cortisol"
        d.tab_tro.click()
        assert win.controller.assay == "troponin" and d.tab_cor.property("active") is False
    finally:
        win.shutdown()


def test_cortisol_placeholder_model_gives_no_value_and_a_pending_note():
    from app.models.cortisol import CortisolModel
    from types import SimpleNamespace
    from app.measure.controller import State
    from app.ui.dashboard_logic import result_view
    r = CortisolModel().predict([], [], [])
    assert r.value is None and r.pending and not r.qc_pass
    note = result_view(Config(), SimpleNamespace(state=State.DONE, result=r), 0, None).note
    assert "연결되지 않아" in note
