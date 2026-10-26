"""SD 카드 이미지 복제 준비: deploy/prepare_image.sh 와 첫 부팅 설정 deploy/firstboot.sh.

실제 시스템 파일은 건드리지 않고, 모든 경로를 임시 폴더로 돌려서 실행한다 (NFORMARE_TEST=1 이면 systemctl/apt 도 부르지 않는다).
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PREPARE = ROOT / "deploy" / "prepare_image.sh"
FIRSTBOOT = ROOT / "deploy" / "firstboot.sh"
UNIT = ROOT / "deploy" / "nformare-firstboot.service"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash 없음")

WIFI = "[connection]\nid=Office\ntype=wifi\n\n[wifi-security]\npsk=secret-password\n"
ETH = "[connection]\nid=wired\ntype=ethernet\n"


@pytest.fixture
def box(tmp_path):
    app, nm, bt, ssh, units, sbin, home, root_home = (tmp_path / n for n in
                                                      ("app", "nm", "bt", "ssh", "units", "sbin", "home", "roothome"))
    for d in (app / "results" / "20261026_troponin", app / "data", nm, bt / "AA-BB" / "cache", ssh, home, root_home):
        d.mkdir(parents=True)
    (app / "main.py").write_text("print('app')\n", encoding="utf-8")
    (app / "config.ini").write_text("[uart]\nport = /dev/serial0\n", encoding="utf-8")
    (app / "results" / "20261026_troponin" / "result.json").write_text('{"patient": {"name": "홍길동"}}', encoding="utf-8")
    (app / "data" / "profiles.json").write_text('{"profiles": [{"name": "홍길동"}]}', encoding="utf-8")
    (app / "data" / "sensor.json").write_text('{"mode": "patch"}', encoding="utf-8")
    (nm / "Office.nmconnection").write_text(WIFI, encoding="utf-8")
    (nm / "wired.nmconnection").write_text(ETH, encoding="utf-8")
    (bt / "AA-BB" / "info").write_text("[General]\nName=patch\n", encoding="utf-8")
    for k in ("rsa", "ecdsa", "ed25519"):
        (ssh / f"ssh_host_{k}_key").write_text("PRIVATE", encoding="utf-8")
        (ssh / f"ssh_host_{k}_key.pub").write_text("PUBLIC", encoding="utf-8")
    (ssh / "sshd_config").write_text("Port 22\n", encoding="utf-8")                  # 설정 파일은 남아야 한다
    (tmp_path / "machine-id").write_text("0123456789abcdef0123456789abcdef\n", encoding="utf-8")
    (home / "huni").mkdir()
    (home / "huni" / ".bash_history").write_text("sudo something\n", encoding="utf-8")
    (root_home / ".bash_history").write_text("x\n", encoding="utf-8")
    done = tmp_path / "firstboot.done"
    done.write_text("old\n", encoding="utf-8")
    env = dict(os.environ)
    env.update({"NFORMARE_TEST": "1", "NFORMARE_ROOT": app.as_posix(), "NFORMARE_NM_DIR": nm.as_posix(),
                "NFORMARE_BT_DIR": bt.as_posix(), "NFORMARE_SSH_DIR": ssh.as_posix(),
                "NFORMARE_MACHINE_ID": (tmp_path / "machine-id").as_posix(), "NFORMARE_SYSTEMD_DIR": units.as_posix(),
                "NFORMARE_SBIN_DIR": sbin.as_posix(), "NFORMARE_FIRSTBOOT_DONE": done.as_posix(),
                "NFORMARE_HOMES": f"{(home / 'huni').as_posix()} {root_home.as_posix()}", "PYTHONIOENCODING": "utf-8"})

    class Box:
        pass
    b = Box()
    b.app, b.nm, b.bt, b.ssh, b.units, b.sbin, b.home, b.root_home, b.done, b.env = \
        app, nm, bt, ssh, units, sbin, home, root_home, done, env
    b.machine_id = tmp_path / "machine-id"
    b.run = lambda *a: subprocess.run([BASH, PREPARE.as_posix(), *a], env=env, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace")
    return b


def test_scripts_have_valid_syntax_lf_and_a_unit_file():
    for s in (PREPARE, FIRSTBOOT):
        assert subprocess.run([BASH, "-n", s.as_posix()], capture_output=True).returncode == 0, s
        assert b"\r" not in s.read_bytes(), f"{s.name} 에 CR 이 있으면 Pi 에서 실행되지 않는다"
    assert b"\r" not in UNIT.read_bytes()
    text = UNIT.read_text(encoding="utf-8")
    assert "Before=ssh.service" in text and "ConditionPathExists=!/var/lib/nformare-firstboot.done" in text


def test_dry_run_changes_nothing(box):
    r = box.run("--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (box.app / "data" / "profiles.json").exists() and (box.nm / "Office.nmconnection").exists()
    assert len(list(box.ssh.glob("ssh_host_*"))) == 6 and box.machine_id.read_text().strip() != ""
    assert box.done.exists() and not box.sbin.exists() and not box.units.exists()
    assert "dry-run" in r.stdout


def test_prepare_removes_device_specific_data_but_keeps_config(box):
    r = box.run("--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert list((box.app / "results").iterdir()) == [] and list((box.app / "data").iterdir()) == []   # 환자 정보·센서 선택
    assert (box.app / "config.ini").read_text(encoding="utf-8").startswith("[uart]")                 # 설정은 남는다
    assert not (box.nm / "Office.nmconnection").exists()                                            # Wi-Fi 비밀번호 삭제
    assert (box.nm / "wired.nmconnection").exists()                                                 # 유선 설정은 남는다
    assert list(box.bt.iterdir()) == []                                                             # 블루투스 페어링
    assert list(box.ssh.glob("ssh_host_*")) == [] and (box.ssh / "sshd_config").exists()
    assert box.machine_id.read_text() == ""
    assert not (box.home / "huni" / ".bash_history").exists() and not (box.root_home / ".bash_history").exists()
    # 첫 부팅 서비스 설치, 복제본에서 다시 실행되도록 완료 표시를 지움
    assert (box.sbin / "nformare-firstboot.sh").exists() and (box.units / "nformare-firstboot.service").exists()
    assert os.access(box.sbin / "nformare-firstboot.sh", os.X_OK)
    assert not box.done.exists()
    assert "홍길동" not in "".join(p.read_text(encoding="utf-8", errors="ignore") for p in box.app.rglob("*") if p.is_file())


def test_keep_options_leave_wifi_and_bluetooth(box):
    r = box.run("--yes", "--keep-wifi", "--keep-bluetooth")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (box.nm / "Office.nmconnection").exists() and (box.bt / "AA-BB" / "info").exists()
    assert list(box.ssh.glob("ssh_host_*")) == []                                                   # SSH 키는 항상 지운다


def test_second_run_is_safe(box):
    assert box.run("--yes").returncode == 0
    r = box.run("--yes")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (box.app / "config.ini").exists()


def test_refuses_a_folder_that_is_not_the_project_and_unknown_options(box, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    env = dict(box.env, NFORMARE_ROOT=empty.as_posix())
    r = subprocess.run([BASH, PREPARE.as_posix(), "--yes"], env=env, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode != 0 and "main.py" in r.stderr and (box.nm / "Office.nmconnection").exists()
    r = box.run("--no-such-flag")
    assert r.returncode != 0 and "알 수 없는 옵션" in r.stderr


# ---------------- 첫 부팅 ----------------
@pytest.fixture
def fb(tmp_path):
    ssh, boot = tmp_path / "ssh", tmp_path / "boot"
    ssh.mkdir()
    boot.mkdir()
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1\tlocalhost\n127.0.1.1\traspberrypi\n", encoding="utf-8")
    done = tmp_path / "state" / "firstboot.done"
    env = dict(os.environ, NFORMARE_TEST="1", NFORMARE_SSH_DIR=ssh.as_posix(), NFORMARE_BOOT_DIR=boot.as_posix(),
               NFORMARE_HOSTS_FILE=hosts.as_posix(), NFORMARE_FIRSTBOOT_DONE=done.as_posix())

    class Box:
        pass
    b = Box()
    b.ssh, b.boot, b.hosts, b.done = ssh, boot, hosts, done
    b.run = lambda: subprocess.run([BASH, FIRSTBOOT.as_posix()], env=env, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace")
    return b


def test_firstboot_creates_ssh_keys_sets_hostname_once(fb):
    (fb.boot / "nformare-device.txt").write_text("# 장치 설정\r\nhostname = nf-001\r\n", encoding="utf-8")
    r = fb.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert list(fb.ssh.glob("ssh_host_*_key"))                               # SSH 키가 없었으면 새로 만든다
    hosts = fb.hosts.read_text(encoding="utf-8")
    assert "127.0.1.1\tnf-001" in hosts and "raspberrypi" not in hosts and "localhost" in hosts
    assert fb.done.exists()
    fb.hosts.write_text("127.0.1.1\tother\n", encoding="utf-8")
    assert fb.run().returncode == 0 and fb.hosts.read_text(encoding="utf-8") == "127.0.1.1\tother\n"   # 두 번째는 아무것도 안 한다


def test_firstboot_rejects_bad_hostname_and_works_without_device_file(fb):
    (fb.boot / "nformare-device.txt").write_text("hostname=bad name!\n", encoding="utf-8")
    r = fb.run()
    assert r.returncode == 0 and "올바르지 않아" in r.stdout
    assert "raspberrypi" in fb.hosts.read_text(encoding="utf-8") and fb.done.exists()


def test_firstboot_keeps_existing_ssh_keys(fb):
    key = fb.ssh / "ssh_host_ed25519_key"
    key.write_text("MINE", encoding="utf-8")
    assert fb.run().returncode == 0
    assert key.read_text(encoding="utf-8") == "MINE"
