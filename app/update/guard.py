"""업데이트 직후 안전장치 (표준 라이브러리만 사용 — 새 버전 코드가 깨져 있어도 실행되어야 하므로).

설치하면 `.update/state.json` 에 pending 을 적는다. 새 버전이 켜질 때마다 시도 횟수를 올리고, 앱이 정상으로 뜬 뒤
mark_healthy() 가 pending 을 지운다. 정상 표시 없이 MAX_BOOTS 번 시작되면(= 계속 죽는 중) 이전 버전으로 되돌린다.
"""
import json
import os
import shutil
from pathlib import Path
from typing import Optional

MAX_BOOTS = 3
KEEP = ("app", "deploy", "tools", "main.py", "requirements.txt", "VERSION")     # 업데이트가 바꾸는 항목 (config.ini, data, results 는 건드리지 않는다)


def update_dir(root: Path) -> Path:
    return Path(root) / ".update"


def _state_path(root: Path) -> Path:
    return update_dir(root) / "state.json"


def read_state(root: Path) -> dict:
    try:
        return json.loads(_state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(root: Path, state: dict) -> None:
    p = _state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, p)


def clear_state(root: Path) -> None:
    try:
        _state_path(root).unlink()
    except OSError:
        pass


def rollback(root: Path) -> bool:
    """`.update/prev` 의 이전 버전으로 되돌린다. 되돌렸으면 True."""
    root = Path(root)
    prev = update_dir(root) / "prev"
    if not prev.is_dir():
        return False
    for name in KEEP:
        src, dst = prev / name, root / name
        if not src.exists():
            continue
        if dst.exists():
            shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
        shutil.move(str(src), str(dst))
    clear_state(root)
    return True


def on_startup(root: Path) -> Optional[str]:
    """main.py 맨 앞에서 부른다. 되돌렸으면 'rolled_back', 업데이트 직후 시도 중이면 'pending', 아니면 None."""
    state = read_state(root)
    if not state.get("pending"):
        return None
    boots = int(state.get("boots", 0)) + 1
    if boots > MAX_BOOTS:
        return "rolled_back" if rollback(root) else None
    state["boots"] = boots
    write_state(root, state)
    return "pending"


def mark_healthy(root: Path) -> None:
    """앱이 정상으로 떴다 — 업데이트 확정. 이전 버전은 다음 업데이트 때까지 남겨 둔다."""
    state = read_state(root)
    if state.get("pending"):
        clear_state(root)
