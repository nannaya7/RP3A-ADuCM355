"""세션 정보 (로그인 결과)."""
from dataclasses import dataclass


@dataclass
class Session:
    role: str = ""
    user_id: str = ""
    token: str = ""

    def clear(self) -> None:
        self.role = self.user_id = self.token = ""
