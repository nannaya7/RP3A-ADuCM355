"""서버 로그인 (VITAL PHR 서버). `POST {base_url}/api/v1/auth/login` 에 {email, password} 를 JSON 으로 보낸다.

응답 (웹 프런트의 authApi.login 과 같은 해석):
  성공  {"success": true,  "data": {"accessToken": ..., "refreshToken": ..., "role": ...}}
  실패  {"success": false, "message": "이메일 또는 비밀번호가 올바르지 않습니다.", "data": null}   (HTTP 400/401)
역할 탭(일반/의료진/기관)은 서버로 보내지 않는다 — 역할은 응답의 role 로 정해진다 (웹도 같다).
"""
from __future__ import annotations

import json
import logging

from .base import AuthResult

log = logging.getLogger(__name__)
LOGIN_PATH = "/api/v1/auth/login"
BAD_LOGIN = "이메일 또는 비밀번호가 올바르지 않습니다."


class ServerAuth:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url, self.timeout = base_url.strip().rstrip("/"), timeout

    def login(self, role: str, user_id: str, password: str) -> AuthResult:
        """블로킹 호출 — GUI 스레드에서 부르지 말 것 (TaskRunner 로 실행). 예외 없이 AuthResult 로 돌려준다."""
        if not self.base_url:
            return AuthResult(False, message="로그인 서버 주소가 설정되어 있지 않습니다. (config.ini [server] base_url)")
        import urllib.error
        import urllib.request
        body = json.dumps({"email": user_id, "password": password}).encode("utf-8")
        req = urllib.request.Request(self.base_url + LOGIN_PATH, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:                  # 서버가 거절 (잘못된 아이디/비밀번호 등)
            msg = self._message(e.read()) or (BAD_LOGIN if e.code in (400, 401, 403) else f"서버 오류 (HTTP {e.code})")
            log.info("login rejected: HTTP %s", e.code)
            return AuthResult(False, message=msg)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            reason = getattr(e, "reason", e)
            log.warning("login server unreachable: %s", reason)
            return AuthResult(False, message=f"서버에 연결할 수 없습니다. 네트워크를 확인해 주세요. ({reason})")
        try:
            doc = json.loads(raw.decode("utf-8"))
            data = doc.get("data", doc) if isinstance(doc, dict) else {}
            token = str(data.get("accessToken") or "")
        except (ValueError, AttributeError):
            token, data = "", {}
        if status >= 400 or not token:
            log.warning("login response without a token (HTTP %s)", status)
            return AuthResult(False, message=self._message(raw) or "서버 응답을 해석할 수 없습니다.")
        return AuthResult(True, token=token, message="ok", refresh_token=str(data.get("refreshToken") or ""),
                          role=str(data.get("role") or ""))

    @staticmethod
    def _message(raw: bytes) -> str:
        try:
            doc = json.loads(raw.decode("utf-8"))
            return str(doc.get("message") or "") if isinstance(doc, dict) else ""
        except (ValueError, AttributeError):
            return ""
