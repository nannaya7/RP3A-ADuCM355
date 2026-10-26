"""저장된 프로필 목록 (세로 화면에서 가족 구성원을 골라 쓴다). Qt 의존 없음.

파일 하나(data/profiles.json)에 모두 저장한다. 쓸 때는 임시 파일에 쓴 뒤 바꿔치기해서 도중에 전원이 꺼져도 깨지지 않는다.
읽을 수 없는 파일은 .bad 로 옮겨 두고 빈 목록으로 시작한다 (측정을 막지 않는다).
이름 등 개인정보가 들어 있으므로 기기 밖으로 복사할 때 주의한다.
"""
import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .patient import PatientProfile

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredProfile:
    id: str
    profile: PatientProfile

    @property
    def name(self) -> str:
        return self.profile.name


def _to_profile(d: dict) -> PatientProfile:
    return PatientProfile(name=str(d.get("name", "")).strip(), sex=d.get("sex", "") or "", age=d.get("age"),
                          weight=d.get("weight"), bp_sys=d.get("bp_sys"), bp_dia=d.get("bp_dia"),
                          glucose=d.get("glucose"), chronic=list(d.get("chronic") or []))


class ProfileStore:
    def __init__(self, path):
        self.path = Path(path)
        self._items: List[StoredProfile] = []
        self._load()

    # ---- 읽기 ----
    def _load(self) -> None:
        self._items = []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for d in data.get("profiles", []):
                p = _to_profile(d)
                if p.name and d.get("id"):
                    self._items.append(StoredProfile(str(d["id"]), p))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError, TypeError) as e:
            log.warning("cannot read the profile file (%s): %s - starting with an empty list", self.path, e)
            try:
                self.path.replace(self.path.with_suffix(".bad"))
            except OSError:
                pass

    def all(self) -> List[StoredProfile]:
        return list(self._items)

    def get(self, pid: str) -> Optional[StoredProfile]:
        return next((x for x in self._items if x.id == pid), None)

    # ---- 쓰기 ----
    def add(self, profile: PatientProfile) -> str:
        pid = uuid.uuid4().hex[:8]
        self._items.append(StoredProfile(pid, profile))
        self._save()
        return pid

    def update(self, pid: str, profile: PatientProfile) -> bool:
        for i, x in enumerate(self._items):
            if x.id == pid:
                self._items[i] = StoredProfile(pid, profile)
                self._save()
                return True
        return False

    def delete(self, pid: str) -> bool:
        n = len(self._items)
        self._items = [x for x in self._items if x.id != pid]
        if len(self._items) != n:
            self._save()
            return True
        return False

    def _save(self) -> None:
        data = {"schema": 1, "profiles": [dict(id=x.id, **x.profile.to_dict()) for x in self._items]}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("cannot save the profiles (%s): %s", self.path, e)
