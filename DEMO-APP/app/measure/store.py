"""측정 세션 저장: 원문 UART 로그(raw.log)와 결과(JSON). 저장 실패가 측정을 막지 않도록 예외를 삼킨다."""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def _default(o):
    return str(o)


class SessionStore:
    def __init__(self, base_dir: Path, now=datetime.now):
        self.base_dir = Path(base_dir)
        self._now = now
        self.dir: Optional[Path] = None
        self._raw = None
        self._warned = False

    @property
    def is_open(self) -> bool:
        return self.dir is not None

    def open(self, tag: str = "demo") -> Optional[Path]:
        try:
            self.dir = self.base_dir / f"{self._now():%Y%m%d_%H%M%S}_{tag}"
            self.dir.mkdir(parents=True, exist_ok=True)
            self._raw = open(self.dir / "raw.log", "a", encoding="utf-8", buffering=1)
        except OSError as e:
            self._fail(e)
        return self.dir

    def log_line(self, line: str) -> None:
        """펌웨어에서 받은 원문 한 줄 (수신 시각 포함)."""
        if self._raw is None:
            return
        try:
            self._raw.write(f"{self._now():%H:%M:%S.%f}"[:-3] + "\t" + line + "\n")
        except OSError as e:
            self._fail(e)

    def note(self, text: str) -> None:
        self.log_line("# " + text)

    def write_json(self, name: str, obj) -> None:
        if self.dir is None:
            return
        path = self.dir / name
        tmp = path.with_name(path.name + ".tmp")
        try:                                       # 임시 파일에 다 쓴 뒤 바꿔치기: 도중에 앱이 꺼지거나 전원이 나가도 빈 파일이 남지 않는다
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False, indent=2, default=_default))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except OSError as e:
            self._fail(e)

    def close(self) -> None:
        if self._raw is not None:
            try:
                self._raw.close()
            except OSError:
                pass
            self._raw = None

    def _fail(self, e: Exception) -> None:
        if not self._warned:
            self._warned = True
            log.warning("failed to save the result (measurement continues): %s", e)
