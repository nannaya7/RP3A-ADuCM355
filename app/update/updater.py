"""업데이트 확인·내려받기·설치 (Qt 와 무관한 로직).

서버의 manifest(latest.json):
    {"version": "V.0.10.007", "url": "nformare-V.0.10.007.tar.gz", "sha256": "...", "size": 123456,
     "notes": "변경 내용", "signature": "<base64 ed25519>"}
url 이 상대 경로이면 manifest 주소 기준이다. 서명은 "<version>, 줄바꿈, <sha256>" 문자열에 대한 ed25519 서명이다.

설치는 제자리 교체: 새 파일을 `.update/staging` 에 풀어 검사한 뒤 현재 app/ deploy/ tools/ main.py … 를 `.update/prev` 로
옮기고 새 것을 놓는다. config.ini, data/, results/ 는 건드리지 않는다. 문제가 있으면 guard.rollback 으로 되돌린다.
"""
import base64
import hashlib
import json
import logging
import re
import shutil
import tarfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from . import guard

log = logging.getLogger(__name__)

PUBLIC_KEY_FILE = Path(__file__).resolve().parent / "update_key.pub"
ALLOWED_TOP = set(guard.KEEP)                       # 패키지 최상위에 있을 수 있는 이름
MAX_PACKAGE_BYTES = 200 * 1024 * 1024


class UpdateError(Exception):
    """사용자에게 문구로 보여 줄 수 있는 업데이트 오류."""


def parse_version(text: str) -> Tuple[int, ...]:
    m = re.fullmatch(r"\s*[Vv]?\.?(\d+(?:\.\d+)*)\s*", text or "")
    if not m:
        raise UpdateError(f"알 수 없는 버전 형식입니다: {text!r}")
    return tuple(int(x) for x in m.group(1).split("."))


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


@dataclass(frozen=True)
class Manifest:
    version: str
    url: str
    sha256: str
    size: int = 0
    notes: str = ""
    signature: str = ""


def _open(url: str, token: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": "nformare-updater"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_manifest(url: str, token: str = "", timeout: float = 15.0) -> Manifest:
    if not url:
        raise UpdateError("업데이트 서버 주소가 설정되어 있지 않습니다.")
    try:
        with _open(url, token, timeout) as r:
            data = json.loads(r.read(1 << 20).decode("utf-8"))
        version = str(data["version"])
        parse_version(version)
        pkg = urllib.parse.urljoin(url, str(data["url"]))
        sha = str(data["sha256"]).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise UpdateError("업데이트 정보의 체크섬 형식이 올바르지 않습니다.")
        return Manifest(version, pkg, sha, int(data.get("size", 0) or 0), str(data.get("notes", "")),
                        str(data.get("signature", "")))
    except UpdateError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise UpdateError(f"업데이트 정보를 가져오지 못했습니다: {e}") from e


def signed_message(m: Manifest) -> bytes:
    return f"{m.version}\n{m.sha256}".encode("utf-8")


def verify_signature(m: Manifest, required: bool = True, key_file: Optional[Path] = None) -> None:
    """서명 검증. required 이면 서명과 공개 키가 모두 있어야 한다."""
    key_file = Path(key_file) if key_file else PUBLIC_KEY_FILE
    if not required and (not m.signature or not key_file.is_file()):      # 서명이 필수가 아니면 키가 없는 장비는 건너뛴다
        return
    if not m.signature:
        raise UpdateError("서명이 없는 업데이트는 설치할 수 없습니다.")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as e:
        raise UpdateError("서명 검증 모듈(python3-cryptography)이 설치되어 있지 않습니다.") from e
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(key_file.read_text(encoding="utf-8").strip()))
    except (OSError, ValueError) as e:
        raise UpdateError("서명 확인용 공개 키를 읽을 수 없습니다.") from e
    try:
        pub.verify(base64.b64decode(m.signature), signed_message(m))
    except (InvalidSignature, ValueError) as e:
        raise UpdateError("업데이트 서명이 올바르지 않습니다. 설치하지 않습니다.") from e


def download(m: Manifest, dest_dir: Path, token: str = "", timeout: float = 30.0,
             progress: Optional[Callable[[int, int], None]] = None) -> Path:
    """패키지를 내려받아 체크섬을 확인한다. 어긋나면 파일을 지우고 오류."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / "package.tar.gz"
    h, got = hashlib.sha256(), 0
    try:
        with _open(m.url, token, timeout) as r, open(out, "wb") as f:
            total = int(r.headers.get("Content-Length") or m.size or 0)
            if total > MAX_PACKAGE_BYTES:
                raise UpdateError("업데이트 파일이 너무 큽니다.")
            if total and shutil.disk_usage(dest_dir).free < total * 4:
                raise UpdateError("저장 공간이 부족합니다.")
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                got += len(chunk)
                if got > MAX_PACKAGE_BYTES:
                    raise UpdateError("업데이트 파일이 너무 큽니다.")
                h.update(chunk)
                f.write(chunk)
                if progress:
                    progress(got, total)
    except UpdateError:
        out.unlink(missing_ok=True)
        raise
    except OSError as e:
        out.unlink(missing_ok=True)
        raise UpdateError(f"내려받지 못했습니다: {e}") from e
    if h.hexdigest() != m.sha256:
        out.unlink(missing_ok=True)
        raise UpdateError("내려받은 파일이 손상되었습니다 (체크섬 불일치).")
    return out


def _safe_extract(archive: Path, dest: Path) -> None:
    dest = dest.resolve()
    with tarfile.open(archive, "r:gz") as tf:
        members = tf.getmembers()
        for mem in members:
            name = Path(mem.name)
            if name.is_absolute() or ".." in name.parts or not name.parts:
                raise UpdateError(f"패키지에 허용되지 않는 경로가 있습니다: {mem.name}")
            if name.parts[0] not in ALLOWED_TOP:
                raise UpdateError(f"패키지에 허용되지 않는 항목이 있습니다: {mem.name}")
            if not (mem.isfile() or mem.isdir()):                 # 링크·장치 파일 금지
                raise UpdateError(f"패키지에 허용되지 않는 파일 형식이 있습니다: {mem.name}")
            if not str((dest / name).resolve()).startswith(str(dest)):
                raise UpdateError(f"패키지 경로가 범위를 벗어납니다: {mem.name}")
        for mem in members:
            tf.extract(mem, dest)


def package_version(staged: Path) -> str:
    try:
        text = (Path(staged) / "app" / "version.py").read_text(encoding="utf-8")
    except OSError as e:
        raise UpdateError("패키지에 app/version.py 가 없습니다.") from e
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', text)
    if not m:
        raise UpdateError("패키지의 버전 정보를 읽을 수 없습니다.")
    return m.group(1)


def _check_syntax(staged: Path) -> None:
    for py in list(Path(staged).rglob("*.py")):
        try:
            compile(py.read_bytes(), str(py), "exec")
        except (SyntaxError, ValueError) as e:
            raise UpdateError(f"패키지의 코드가 올바르지 않습니다: {py.name}") from e


def install(archive: Path, root: Path, expected_version: str, allow_dev: bool = False) -> None:
    """패키지를 검사하고 root 의 앱을 교체한다 (재시작은 호출한 쪽이). 실패하면 원래 상태를 유지한다."""
    root = Path(root)
    if (root / ".git").exists() and not allow_dev:
        raise UpdateError("개발용 작업 폴더(.git)에는 설치하지 않습니다.")
    base = guard.update_dir(root)
    staging = base / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        _safe_extract(Path(archive), staging)
        if not (staging / "main.py").is_file():
            raise UpdateError("패키지에 main.py 가 없습니다.")
        if package_version(staging) != expected_version:
            raise UpdateError("패키지 버전이 업데이트 정보와 다릅니다.")
        _check_syntax(staging)
    except (tarfile.TarError, OSError) as e:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"패키지를 풀지 못했습니다: {e}") from e
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    prev = base / "prev"
    shutil.rmtree(prev, ignore_errors=True)
    prev.mkdir(parents=True)
    try:
        for name in guard.KEEP:                                    # 현재 것을 prev 로
            if (root / name).exists():
                shutil.move(str(root / name), str(prev / name))
        for item in staging.iterdir():                             # 새 것을 제자리로
            shutil.move(str(item), str(root / item.name))
        guard.write_state(root, {"pending": expected_version, "boots": 0})
    except OSError as e:
        log.error("update install failed, rolling back: %s", e)
        guard.rollback(root)
        raise UpdateError(f"설치 중 오류가 나 이전 버전으로 되돌렸습니다: {e}") from e
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    log.info("update installed: %s", expected_version)
