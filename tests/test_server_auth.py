"""서버 로그인: 가짜 HTTP 서버로 요청 형식과 응답 처리를 시험한다 (실제 서버에는 접속하지 않는다)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.auth.server_auth import BAD_LOGIN, ServerAuth


class _Handler(BaseHTTPRequestHandler):
    reply = (200, {})
    seen = {}

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        type(self).seen = {"path": self.path, "ctype": self.headers.get("Content-Type"),
                           "body": json.loads(self.rfile.read(n))}
        code, doc = type(self).reply
        raw = json.dumps(doc).encode() if not isinstance(doc, bytes) else doc
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_):
        pass


@pytest.fixture()
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}", _Handler
    srv.shutdown()


def test_login_sends_email_and_password_and_reads_the_tokens(server):
    url, h = server
    h.reply = (200, {"success": True, "data": {"accessToken": "AT", "refreshToken": "RT", "role": "MEDICAL"}})
    r = ServerAuth(url).login("GENERAL", "a@b.com", "secret")
    assert r.ok and r.token == "AT" and r.refresh_token == "RT" and r.role == "MEDICAL"
    assert h.seen["path"] == "/api/v1/auth/login" and h.seen["ctype"] == "application/json"
    assert h.seen["body"] == {"email": "a@b.com", "password": "secret"}          # 역할 탭은 보내지 않는다


def test_wrong_password_shows_the_server_message(server):
    url, h = server
    h.reply = (400, {"success": False, "message": BAD_LOGIN, "data": None})
    r = ServerAuth(url).login("GENERAL", "a@b.com", "bad")
    assert not r.ok and r.message == BAD_LOGIN and not r.token


def test_http_error_without_a_message_uses_a_default(server):
    url, h = server
    h.reply = (401, {})
    assert ServerAuth(url).login("", "a@b.com", "x").message == BAD_LOGIN
    h.reply = (500, {})
    assert "HTTP 500" in ServerAuth(url).login("", "a@b.com", "x").message


def test_success_response_without_a_token_is_a_failure(server):
    url, h = server
    h.reply = (200, {"success": True, "data": {}})
    assert not ServerAuth(url).login("", "a@b.com", "x").ok


def test_unreachable_server_and_empty_address_give_messages_not_exceptions():
    r = ServerAuth("http://127.0.0.1:9", timeout=2).login("", "a@b.com", "x")       # 닫힌 포트
    assert not r.ok and "연결할 수 없습니다" in r.message
    assert "base_url" in ServerAuth("").login("", "a@b.com", "x").message


def test_app_login_button_goes_to_the_measure_page_and_shows_errors(tmp_path, server):
    import dataclasses
    from PyQt5.QtCore import QCoreApplication
    from app.app_window import AppWindow
    from app.config import Config
    from app.display import PORTRAIT
    import time
    url, h = server
    cfg = dataclasses.replace(Config(), uart_mock=True, net_mock=True, server_base_url=url)
    win = AppWindow(PORTRAIT, cfg)
    win.show()

    def wait(cond, ms=4000):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            QCoreApplication.processEvents()
            if cond():
                return
            time.sleep(0.01)
        raise AssertionError("조건 미충족")
    try:
        win.login.email.edit.setText("a@b.com")
        win.login.password.edit.setText("bad")
        h.reply = (400, {"success": False, "message": BAD_LOGIN, "data": None})
        win.login.login_btn.click()
        wait(lambda: not win.login.banner.isHidden())
        assert win.login.banner.text() == BAD_LOGIN and win.currentWidget() is win.login and win.login.login_btn.isEnabled()
        h.reply = (200, {"success": True, "data": {"accessToken": "AT", "refreshToken": "RT", "role": "GENERAL"}})
        win.login.login_btn.click()
        wait(lambda: win.currentWidget() is win.measure)
        assert win.session.token == "AT" and win.session.user_id == "a@b.com" and win.session.role == "GENERAL"
        assert win.login.password.text() == ""
    finally:
        win.shutdown()


def test_successful_logins_are_remembered_up_to_five(tmp_path, server):
    import dataclasses
    import time
    from PyQt5.QtCore import QCoreApplication
    from app.app_window import AppWindow
    from app.config import Config
    from app.display import PORTRAIT
    url, h = server
    h.reply = (200, {"success": True, "data": {"accessToken": "AT", "refreshToken": "RT", "role": "GENERAL"}})
    win = AppWindow(PORTRAIT, dataclasses.replace(Config(), uart_mock=True, net_mock=True, server_base_url=url))
    win.show()
    try:
        for n in range(6):
            win.go_to(win.login)
            win.login.email.edit.setText(f"u{n}@x.com")
            win.login.password.edit.setText("pw")
            win.login.login_btn.click()
            end = time.monotonic() + 4
            while win.currentWidget() is not win.measure and time.monotonic() < end:
                QCoreApplication.processEvents()
                time.sleep(0.01)
            assert win.currentWidget() is win.measure
        assert win.recent_ids.all() == [f"u{n}@x.com" for n in (5, 4, 3, 2, 1)]
        assert win.login.email.edit.completer().model().rowCount() == 5
        h.reply = (400, {"success": False, "message": BAD_LOGIN, "data": None})          # 실패한 ID 는 기억하지 않는다
        win.go_to(win.login)
        win.login.email.edit.setText("bad@x.com")
        win.login.password.edit.setText("pw")
        win.login.login_btn.click()
        end = time.monotonic() + 4
        while win.login.banner.isHidden() and time.monotonic() < end:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert "bad@x.com" not in win.recent_ids.all()
    finally:
        win.shutdown()
