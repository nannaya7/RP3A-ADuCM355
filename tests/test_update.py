"""업데이트: 패키지 생성, 서명·체크섬 검증, 안전한 설치, 되돌리기, 컨트롤러/화면."""
import base64
import dataclasses
import hashlib
import io
import json
import sys
import tarfile
import time

import pytest
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from app.config import Config
from app.net.tasks import TaskRunner  # noqa: F401  (Qt 앱 생성 순서 보장용 import)
from app.update import guard, updater
from app.update.controller import AVAILABLE, ERROR, INSTALLED, UPTODATE, UpdateController
from app.version import VERSION

crypto = pytest.importorskip("cryptography")
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "tools"))
import make_release as mr  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)


def wait(cond, ms=5000):
    end = time.time() + ms / 1000
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return True
        QTest.qWait(10)
    return cond()


# ---------------- 준비물 ----------------
def make_project(root, version, extra=None):
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "app" / "version.py").write_text(f'VERSION = "{version}"\n', encoding="utf-8")
    (root / "app" / "logic.py").write_text(f"NAME = '{version}'\n", encoding="utf-8")
    (root / "main.py").write_text(f"print('{version}')\n", encoding="utf-8")
    (root / "requirements.txt").write_text("x\n", encoding="utf-8")
    for name, text in (extra or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(text.encode("utf-8"))


def keypair(tmp_path):
    key = Ed25519PrivateKey.generate()
    priv = tmp_path / "priv.key"
    pub = tmp_path / "update_key.pub"
    priv.write_text(base64.b64encode(key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode())
    pub.write_text(base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode())
    return priv, pub


@pytest.fixture
def release(tmp_path, monkeypatch):
    """새 버전 V.0.99.001 의 서버 폴더(latest.json + tar.gz)를 만든다. (priv, pub, manifest_url, server_dir)"""
    src = tmp_path / "src"
    make_project(src, "V.0.99.001", {"deploy/run.sh": "echo hi\r\n", "app/__pycache__/x.pyc": "junk"})
    monkeypatch.setattr(mr, "ROOT", src)
    files = mr.collect()
    assert "app/__pycache__/x.pyc" not in files                     # 캐시는 넣지 않는다
    blob = mr.build_tar(files, "V.0.99.001")
    assert blob == mr.build_tar(files, "V.0.99.001")                # 같은 내용이면 같은 바이트
    sha = hashlib.sha256(blob).hexdigest()
    priv, pub = keypair(tmp_path)
    server = tmp_path / "server"
    server.mkdir()
    (server / "nformare-V.0.99.001.tar.gz").write_bytes(blob)
    manifest = {"version": "V.0.99.001", "url": "nformare-V.0.99.001.tar.gz", "sha256": sha, "size": len(blob),
                "notes": "테스트 변경", "signature": mr.sign(priv, "V.0.99.001", sha)}
    (server / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return priv, pub, (server / "latest.json").as_uri(), server


def device(tmp_path):
    root = tmp_path / "device"
    make_project(root, "V.0.10.006", {"config.ini": "[app]\n", "data/sensor.json": "{}", "results/r.json": "{}"})
    return root


# ---------------- 버전 ----------------
def test_version_parse_and_compare():
    assert updater.parse_version("V.0.10.006") == (0, 10, 6)
    assert updater.is_newer("V.0.10.007", "V.0.10.006") and updater.is_newer("V.0.11.001", "V.0.10.999")
    assert not updater.is_newer("V.0.10.006", "V.0.10.006") and not updater.is_newer("V.0.9.999", "V.0.10.001")
    with pytest.raises(updater.UpdateError):
        updater.parse_version("새버전")
    assert VERSION.startswith("V.")                                 # 앱 버전 파일


# ---------------- 패키지 → 서명 → 내려받기 → 설치 ----------------
def test_full_update_keeps_user_data_and_prev_version(tmp_path, release):
    _priv, pub, url, _server = release
    m = updater.fetch_manifest(url)
    assert m.version == "V.0.99.001" and m.notes == "테스트 변경" and m.url.endswith(".tar.gz")
    updater.verify_signature(m, True, pub)
    root = device(tmp_path)
    archive = updater.download(m, root / ".update" / "download")
    updater.install(archive, root, m.version)

    assert updater.package_version(root) == "V.0.99.001"            # 새 코드
    assert (root / "VERSION").read_text().strip() == "V.0.99.001"
    assert (root / "deploy" / "run.sh").read_bytes() == b"echo hi\n"  # LF 로 바뀌어 들어감
    assert (root / "config.ini").read_text() == "[app]\n"           # 장비 설정·데이터는 그대로
    assert (root / "data" / "sensor.json").exists() and (root / "results" / "r.json").exists()
    assert (root / ".update" / "prev" / "app" / "version.py").read_text().count("V.0.10.006") == 1
    assert guard.read_state(root) == {"pending": "V.0.99.001", "boots": 0}


def test_signature_rules(tmp_path, release):
    _priv, pub, url, _ = release
    m = updater.fetch_manifest(url)
    updater.verify_signature(m, True, pub)
    bad = dataclasses.replace(m, sha256="0" * 64)                   # 내용이 바뀐 정보
    with pytest.raises(updater.UpdateError, match="서명"):
        updater.verify_signature(bad, True, pub)
    other = tmp_path / "other_pub"
    other.write_text(base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode())
    with pytest.raises(updater.UpdateError, match="서명"):
        updater.verify_signature(m, True, other)                    # 다른 키
    unsigned = dataclasses.replace(m, signature="")
    with pytest.raises(updater.UpdateError, match="서명이 없는"):
        updater.verify_signature(unsigned, True, pub)
    updater.verify_signature(unsigned, False, pub)                  # 서명 불필요 설정이면 통과


def test_corrupted_download_is_rejected_and_removed(tmp_path, release):
    _priv, _pub, url, server = release
    m = updater.fetch_manifest(url)
    (server / "nformare-V.0.99.001.tar.gz").write_bytes(b"broken")
    with pytest.raises(updater.UpdateError, match="체크섬"):
        updater.download(m, tmp_path / "dl")
    assert not (tmp_path / "dl" / "package.tar.gz").exists()


def test_manifest_errors_are_messages(tmp_path):
    with pytest.raises(updater.UpdateError):
        updater.fetch_manifest("")
    with pytest.raises(updater.UpdateError):
        updater.fetch_manifest((tmp_path / "없음.json").as_uri())
    bad = tmp_path / "bad.json"
    bad.write_text('{"version": "V.1.0.0"}', encoding="utf-8")
    with pytest.raises(updater.UpdateError):
        updater.fetch_manifest(bad.as_uri())


def _tar(path, entries):
    with tarfile.open(path, "w:gz") as tf:
        for name, data in entries:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return path


GOOD = [("main.py", b"print(1)\n"), ("app/version.py", b'VERSION = "V.1.0.0"\n')]


@pytest.mark.parametrize("entries,msg", [
    (GOOD + [("../evil.py", b"x")], "허용되지 않는"),
    (GOOD + [("/etc/passwd", b"x")], "허용되지 않는"),
    (GOOD + [("config.ini", b"x")], "허용되지 않는"),                  # 장비 설정을 덮어쓰는 패키지
    (GOOD + [("app/broken.py", b"def (:\n")], "코드가 올바르지"),
    ([("app/version.py", b'VERSION = "V.1.0.0"\n')], "main.py"),
    ([("main.py", b"1\n"), ("app/version.py", b'VERSION = "V.9.9.9"\n')], "버전이 업데이트 정보와"),
])
def test_bad_packages_leave_the_device_untouched(tmp_path, entries, msg):
    root = device(tmp_path)
    before = (root / "app" / "logic.py").read_text()
    with pytest.raises(updater.UpdateError, match=msg):
        updater.install(_tar(tmp_path / "p.tar.gz", entries), root, "V.1.0.0")
    assert (root / "app" / "logic.py").read_text() == before and not (root / ".update" / "staging").exists()


def test_symlink_member_is_refused(tmp_path):
    p = tmp_path / "l.tar.gz"
    with tarfile.open(p, "w:gz") as tf:
        ti = tarfile.TarInfo("app")
        ti.type, ti.linkname = tarfile.SYMTYPE, "/etc"
        tf.addfile(ti)
    with pytest.raises(updater.UpdateError, match="파일 형식"):
        updater.install(p, device(tmp_path), "V.1.0.0")


def test_never_installs_into_a_git_working_tree(tmp_path):
    root = device(tmp_path)
    (root / ".git").mkdir()
    with pytest.raises(updater.UpdateError, match="개발용"):
        updater.install(_tar(tmp_path / "p.tar.gz", GOOD), root, "V.1.0.0")


# ---------------- 되돌리기 ----------------
def test_rollback_after_repeated_unhealthy_boots(tmp_path, release):
    _priv, _pub, url, _ = release
    root = device(tmp_path)
    m = updater.fetch_manifest(url)
    updater.install(updater.download(m, root / ".update" / "download"), root, m.version)
    for _ in range(guard.MAX_BOOTS):
        assert guard.on_startup(root) == "pending"                  # 정상 표시 없이 계속 시작
    assert guard.on_startup(root) == "rolled_back"
    assert updater.package_version(root) == "V.0.10.006"            # 이전 버전
    assert (root / "config.ini").exists() and guard.read_state(root) == {}
    assert guard.on_startup(root) is None


def test_healthy_mark_confirms_the_update(tmp_path, release):
    _priv, _pub, url, _ = release
    root = device(tmp_path)
    m = updater.fetch_manifest(url)
    updater.install(updater.download(m, root / ".update" / "download"), root, m.version)
    assert guard.on_startup(root) == "pending"
    guard.mark_healthy(root)
    assert guard.on_startup(root) is None and updater.package_version(root) == "V.0.99.001"


# ---------------- 컨트롤러 / 화면 ----------------
def make_ctrl(tmp_path, url, blocked="", **cfg_kw):
    cfg = dataclasses.replace(Config(), update_url=url, update_require_signature=False, **cfg_kw)
    restarted = []
    c = UpdateController(cfg, device(tmp_path), blocked=lambda: blocked, restart=lambda: restarted.append(1),
                         restart_delay_ms=10)
    states = []
    c.stateChanged.connect(lambda s, t: states.append((s, t)))
    return c, states, restarted


def test_controller_check_then_user_installs(tmp_path, release):
    _priv, _pub, url, _ = release
    c, states, restarted = make_ctrl(tmp_path, url)
    badge = []
    c.availabilityChanged.connect(badge.append)
    c.check()
    assert wait(lambda: c.state == AVAILABLE)
    assert "V.0.99.001" in states[-1][1] and "테스트 변경" in states[-1][1] and badge == [True]
    assert guard.read_state(c.root) == {}                           # 확인만으로는 아무것도 설치하지 않는다
    c.install()
    assert wait(lambda: c.state == INSTALLED) and wait(lambda: restarted)
    assert updater.package_version(c.root) == "V.0.99.001" and badge[-1] is False
    c.wait()


def test_controller_up_to_date_and_blocked_and_disabled(tmp_path, release):
    _priv, _pub, url, server = release
    m = json.loads((server / "latest.json").read_text(encoding="utf-8"))
    m["version"] = VERSION
    (server / "latest.json").write_text(json.dumps(m), encoding="utf-8")
    c, states, _ = make_ctrl(tmp_path, url)
    c.check()
    assert wait(lambda: c.state == UPTODATE)

    c2, st2, _ = make_ctrl(tmp_path, url, blocked="검사 중에는 업데이트할 수 없습니다.")
    c2.check()
    assert c2.state == ERROR and "검사 중" in st2[-1][1]            # 검사 중에는 확인조차 하지 않는다
    c3, st3, _ = make_ctrl(tmp_path, "")
    c3.check()
    assert c3.state == ERROR and "설정되어" in st3[-1][1]
    c3.check(silent=True)                                           # 조용한 확인은 아무 알림도 내지 않는다
    assert len(st3) == 1


def test_signature_required_by_default(tmp_path, release):
    _priv, _pub, url, server = release
    m = json.loads((server / "latest.json").read_text(encoding="utf-8"))
    m.pop("signature")
    (server / "latest.json").write_text(json.dumps(m), encoding="utf-8")
    cfg = dataclasses.replace(Config(), update_url=url)             # update_require_signature 기본 True
    c = UpdateController(cfg, device(tmp_path), restart=lambda: None)
    c.check()
    assert wait(lambda: c.state == AVAILABLE)
    c.install()
    assert wait(lambda: c.state == ERROR)
    assert updater.package_version(c.root) == "V.0.10.006"          # 서명 없으면 설치되지 않음
    c.wait()


def test_update_tab_and_gear_badge(tmp_path):
    from app.app_window import AppWindow
    from app.display import LANDSCAPE
    cfg = dataclasses.replace(Config(), uart_mock=True, net_mock=True, results_dir=str(tmp_path / "r"))
    win = AppWindow(LANDSCAPE, cfg)
    try:
        assert win.settings.tabs.current_key() in ("wifi",) and win.settings.info.version.text() == VERSION
        win.settings._on_tab("info")
        assert win.settings.stack.currentWidget() is win.settings.info
        win.updates.availabilityChanged.emit(True)
        assert win.gear._badge is True
        win.settings.info.set_state(AVAILABLE, "새 버전")
        assert not win.settings.info.install_btn.isHidden()
        win.settings.info.set_state(UPTODATE, "최신")
        assert win.settings.info.install_btn.isHidden()
        assert win._update_blocked_reason() == ""
    finally:
        win.shutdown()
        win.close()
