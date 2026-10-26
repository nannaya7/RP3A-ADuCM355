"""배포 패키지(tar.gz)와 업데이트 정보(latest.json)를 만든다. 파이썬 코드 그대로 배포한다 (바이너리 아님).

    python tools/make_release.py --gen-key ~/keys          # 처음 한 번: 서명 키 쌍 생성 (공개 키는 app/update/ 에 저장)
    python tools/make_release.py --key ~/keys/update_private.key --notes "변경 내용"
    python tools/make_release.py --no-sign                  # 서명 없이 (서버 시험용. 장비는 require_signature = false 여야 설치)

결과(dist/): nformare-<버전>.tar.gz, latest.json. 둘을 서버에 올린다. 버전은 app/version.py 의 VERSION.
개인 키(update_private.key)는 저장소에 넣지 않는다 (.gitignore 의 *.key).
"""
import argparse
import base64
import gzip
import hashlib
import io
import json
import re
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

INCLUDE_DIRS = ("app", "deploy")
INCLUDE_FILES = ("main.py", "requirements.txt", "tools/uart_demo.py", "tools/net_check.py")
SKIP_PARTS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIX = {".pyc", ".pyo"}


def read_version() -> str:
    text = (ROOT / "app" / "version.py").read_text(encoding="utf-8")
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("app/version.py 에서 VERSION 을 찾을 수 없습니다.")
    return m.group(1)


def collect() -> list:
    files = []
    for d in INCLUDE_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_PARTS) and p.suffix not in SKIP_SUFFIX:
                files.append(p.relative_to(ROOT).as_posix())
    files += [f for f in INCLUDE_FILES if (ROOT / f).is_file()]
    return files


def build_tar(files: list, version: str) -> bytes:
    """같은 내용이면 같은 바이트가 나오게 만든다 (시각·소유자 고정, 이름순)."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tf:
        def add(name: str, data: bytes) -> None:
            ti = tarfile.TarInfo(name)
            ti.size, ti.mtime, ti.mode = len(data), 0, 0o755 if name.endswith(".sh") else 0o644
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            tf.addfile(ti, io.BytesIO(data))
        for name in sorted(files):
            data = (ROOT / name).read_bytes()
            if name.endswith((".sh", ".py", ".service", ".script", ".plymouth", ".ini", ".txt", ".md")):
                data = data.replace(b"\r\n", b"\n")                 # Pi 에서 실행되는 파일은 LF
            add(name, data)
        add("VERSION", (version + "\n").encode("utf-8"))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def gen_key(dest: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    dest.mkdir(parents=True, exist_ok=True)
    priv_file = dest / "update_private.key"
    if priv_file.exists():
        raise SystemExit(f"이미 있습니다: {priv_file} (덮어쓰지 않습니다)")
    key = Ed25519PrivateKey.generate()
    raw = serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    priv_file.write_text(base64.b64encode(key.private_bytes(*raw)).decode() + "\n", encoding="utf-8")
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pub_file = ROOT / "app" / "update" / "update_key.pub"
    pub_file.write_text(base64.b64encode(pub).decode() + "\n", encoding="utf-8")
    print(f"개인 키: {priv_file}  (안전한 곳에 보관, 저장소에 넣지 말 것)")
    print(f"공개 키: {pub_file}  (장비에 배포되는 앱에 포함됨 — 커밋한다)")


def sign(key_file: Path, version: str, sha256: str) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(key_file.read_text(encoding="utf-8").strip()))
    return base64.b64encode(key.sign(f"{version}\n{sha256}".encode("utf-8"))).decode()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gen-key", metavar="DIR", help="서명 키 쌍을 만든다 (개인 키는 DIR, 공개 키는 app/update/)")
    ap.add_argument("--key", metavar="FILE", help="서명에 쓸 개인 키")
    ap.add_argument("--no-sign", action="store_true", help="서명하지 않는다 (시험용)")
    ap.add_argument("--notes", default="", help="업데이트 설명(장비 화면에 표시)")
    ap.add_argument("--out", default=str(ROOT / "dist"), help="출력 폴더")
    args = ap.parse_args()
    if args.gen_key:
        gen_key(Path(args.gen_key).expanduser())
        return 0
    if not args.key and not args.no_sign:
        ap.error("--key FILE 또는 --no-sign 이 필요합니다")
    version = read_version()
    files = collect()
    blob = build_tar(files, version)
    sha = hashlib.sha256(blob).hexdigest()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pkg = f"nformare-{version}.tar.gz"
    (out / pkg).write_bytes(blob)
    manifest = {"version": version, "url": pkg, "sha256": sha, "size": len(blob), "notes": args.notes}
    if not args.no_sign:
        manifest["signature"] = sign(Path(args.key).expanduser(), version, sha)
    (out / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{out / pkg}  ({len(blob) // 1024} KB, {len(files)} files)")
    print(f"sha256 {sha}")
    print(f"{out / 'latest.json'}  ({'unsigned' if args.no_sign else 'signed'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
