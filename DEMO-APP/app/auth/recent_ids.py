"""최근 로그인한 ID 목록 (최대 5개, 최신이 앞). 비밀번호는 저장하지 않는다. Qt 의존 없음.

data/recent_logins.json 에 쓴다. 쓸 때는 임시 파일에 쓴 뒤 바꿔치기해서 도중에 전원이 꺼져도 깨지지 않는다.
읽을 수 없는 파일은 빈 목록으로 시작한다 (로그인을 막지 않는다).
"""
import json
import logging
import os
from pathlib import Path
from typing import List

log = logging.getLogger(__name__)
LIMIT = 5


class RecentIds:
    def __init__(self, path, limit: int = LIMIT):
        self.path, self.limit = Path(path), limit
        self._ids: List[str] = self._load()

    def _load(self) -> List[str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            ids = [str(x).strip() for x in data.get("ids", []) if str(x).strip()]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, AttributeError, TypeError) as e:
            log.warning("cannot read the recent login ids (%s): %s", self.path, e)
            return []
        return self._dedupe(ids)[:self.limit]

    @staticmethod
    def _dedupe(ids: List[str]) -> List[str]:
        seen, out = set(), []
        for i in ids:
            if i.lower() not in seen:                      # 이메일은 대소문자를 구분하지 않는다
                seen.add(i.lower())
                out.append(i)
        return out

    def all(self) -> List[str]:
        return list(self._ids)

    def add(self, user_id: str) -> None:
        """로그인에 성공한 ID 를 맨 앞으로 (이미 있으면 끌어올리고, 5개를 넘으면 가장 오래된 것을 지운다)."""
        user_id = user_id.strip()
        if not user_id:
            return
        self._ids = self._dedupe([user_id] + self._ids)[:self.limit]
        self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"ids": self._ids}, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("cannot save the recent login ids (%s): %s", self.path, e)
