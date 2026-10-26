"""개발용: 항상 성공. 서버 로그인(server_auth.py) 구현 전까지 사용."""
from .base import AuthResult


class SkipAuth:
    def login(self, role: str, user_id: str, password: str) -> AuthResult:
        return AuthResult(ok=True, message="skip")
