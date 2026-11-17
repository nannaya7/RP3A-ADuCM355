"""인증 백엔드 인터페이스. UI 는 이 인터페이스만 안다."""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class AuthResult:
    ok: bool
    token: str = ""
    message: str = ""
    refresh_token: str = ""
    role: str = ""            # 서버가 알려 준 역할 (GENERAL / MEDICAL / HOSPITAL)


class AuthBackend(Protocol):
    def login(self, role: str, user_id: str, password: str) -> AuthResult: ...
