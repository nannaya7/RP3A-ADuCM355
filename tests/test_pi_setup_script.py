"""deploy/pi_setup.sh, install_splash.sh 를 가짜 명령(apt-get, raspi-config …)과 임시 부팅 폴더로 처음부터 끝까지 실행한다.

실제 Pi 가 아니어도 '어떤 명령을 어떤 순서로 부르고, 부팅 파일이 어떻게 바뀌는지, 두 번 실행해도 같은지,
되돌리면 복원되는지'를 확인할 수 있다. bash 가 없으면 건너뛴다.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SETUP = ROOT / "deploy" / "pi_setup.sh"
SPLASH = ROOT / "deploy" / "install_splash.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash 없음")

STOCK_CMDLINE = ("console=serial0,115200 console=tty1 root=PARTUUID=abcd1234-02 rootfstype=ext4 fsck.repair=yes "
                 "rootwait quiet splash plymouth.ignore-serial-consoles\n")
STOCK_CONFIG = "dtparam=audio=on\ndtoverlay=vc4-kms-v3d\narm_64bit=1\n\n[cm4]\notg_mode=1\n\n[all]\n"

FAKE_CMDS = {
    # 호출을 기록만 한다
    "apt-get": 'echo "apt-get $*" >> "$NF_CALLS"',
    "usermod": 'echo "usermod $*" >> "$NF_CALLS"',
    "timedatectl": 'echo "timedatectl $*" >> "$NF_CALLS"',
    "hostnamectl": 'echo "hostnamectl $*" >> "$NF_CALLS"',
    "raspi-config": 'echo "raspi-config $*" >> "$NF_CALLS"\ncase "$*" in *get_serial_hw*) echo 0;; *get_serial_cons*) echo 1;; esac',
    # 현재 테마를 묻는 호출(인자 없음)은 pix 를 돌려주고, 설정 호출은 기록한다
    "plymouth-set-default-theme": 'if [ $# -eq 0 ]; then echo pix; else echo "plymouth-set-default-theme $*" >> "$NF_CALLS"; fi',
    # sudo -u USER env ... 같은 호출을 그대로 실행
    "sudo": 'while [ $# -gt 0 ]; do case "$1" in -E) shift;; -u) shift 2;; *) break;; esac; done; exec "$@"',
}


@pytest.fixture
def sandbox(tmp_path):
    boot, state, splash_state, themes, fake = (tmp_path / n for n in ("boot", "state", "splash_state", "themes", "bin"))
    for d in (boot, themes, fake):
        d.mkdir()
    (boot / "cmdline.txt").write_text(STOCK_CMDLINE, encoding="utf-8", newline="\n")
    (boot / "config.txt").write_text(STOCK_CONFIG, encoding="utf-8", newline="\n")
    calls = tmp_path / "calls.log"
    calls.write_text("", encoding="utf-8")
    for name, body in FAKE_CMDS.items():
        f = fake / name
        f.write_text("#!/bin/bash\n" + body + "\n", encoding="utf-8", newline="\n")
        f.chmod(0o755)
    py = fake / "python3"
    py.write_text(f'#!/bin/bash\nexec "{Path(sys.executable).as_posix()}" "$@"\n', encoding="utf-8", newline="\n")
    py.chmod(0o755)
    env = dict(os.environ)
    env.update({
        "PATH": fake.as_posix() + os.pathsep + env["PATH"],
        "NFORMARE_TEST": "1",
        "NFORMARE_BOOT_DIR": boot.as_posix(),
        "NFORMARE_STATE_DIR": state.as_posix(),
        "NFORMARE_SPLASH_STATE": splash_state.as_posix(),
        "NFORMARE_PLYMOUTH_DIR": themes.as_posix(),
        "NF_CALLS": calls.as_posix(),
        "SUDO_USER": "huni",
        "PYTHONIOENCODING": "utf-8",        # Windows 콘솔 인코딩(cp949)과 무관하게 한글 메시지를 비교한다 (Pi 는 UTF-8)
    })

    class Box:
        pass
    b = Box()
    b.boot, b.state, b.splash_state, b.themes, b.calls, b.env = boot, state, splash_state, themes, calls, env
    b.cmdline = lambda: (boot / "cmdline.txt").read_text(encoding="utf-8")
    b.config = lambda: (boot / "config.txt").read_text(encoding="utf-8")
    b.called = lambda: calls.read_text(encoding="utf-8").splitlines()

    def run(script, *args):
        return subprocess.run([BASH, script.as_posix(), *args], env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    b.run = run
    return b


def test_scripts_have_valid_bash_syntax_and_lf_line_endings():
    for s in (SETUP, SPLASH):
        assert subprocess.run([BASH, "-n", s.as_posix()], capture_output=True).returncode == 0, s
        assert b"\r" not in s.read_bytes(), f"{s.name} 에 CR 이 있으면 Pi 에서 실행되지 않는다"


def test_dry_run_changes_nothing_and_lists_the_plan(sandbox):
    r = sandbox.run(SETUP, "--dry-run", "--disable-hdmi", "--timezone", "Asia/Seoul")
    assert r.returncode == 0, r.stdout + r.stderr
    assert sandbox.cmdline() == STOCK_CMDLINE and sandbox.config() == STOCK_CONFIG
    assert sandbox.called() == [] and not sandbox.state.exists() and not (sandbox.themes / "nformare").exists()
    for expected in ("apt-get install -y python3-pyqt5", "raspi-config nonint do_serial_hw 0", "raspi-config nonint do_ssh 0",
                     "timedatectl set-timezone Asia/Seoul"):
        assert expected in r.stdout, expected


def test_full_run_applies_everything(sandbox):
    r = sandbox.run(SETUP, "--skip", "check", "--disable-bt", "--disable-hdmi", "--timezone", "Asia/Seoul",
                    "--dsi-overlay", "dtoverlay=vc4-kms-dsi-waveshare-panel-v2,10_1_inch_a",
                    "--cmdline-token", "video=DSI-1:800x1280@60,rotate=90")
    assert r.returncode == 0, r.stdout + r.stderr
    calls = sandbox.called()
    for expected in ("raspi-config nonint do_serial_hw 0", "raspi-config nonint do_serial_cons 1",
                     "raspi-config nonint do_ssh 0", "raspi-config nonint do_vnc 0", "raspi-config nonint do_blanking 1",
                     "usermod -aG dialout huni", "timedatectl set-timezone Asia/Seoul",
                     "plymouth-set-default-theme -R nformare"):
        assert expected in calls, f"{expected}\n{calls}"
    pkgs = {c.split()[-1] for c in calls if c.startswith("apt-get install")}
    assert {"python3-pyqt5", "python3-serial", "python3-numpy", "qtwayland5", "picocom"} <= pkgs
    # 명령 순서: apt → serial → … → 스플래시 (initramfs 재생성은 마지막 설정 변경 뒤)
    assert calls.index("apt-get update") < calls.index("raspi-config nonint do_serial_hw 0") < calls.index("plymouth-set-default-theme -R nformare")

    cfg = sandbox.config()
    assert cfg.startswith(STOCK_CONFIG)                                       # 기존 내용 보존
    for line in ("enable_uart=1", "dtoverlay=disable-bt", "dtoverlay=vc4-kms-dsi-waveshare-panel-v2,10_1_inch_a",
                 "disable_splash=1"):
        assert cfg.splitlines().count(line) == 1, line
    cmd = sandbox.cmdline()
    assert cmd.count("\n") == 1 and cmd.endswith("\n")                        # 한 줄
    toks = cmd.split()
    assert toks[:len(STOCK_CMDLINE.split())] == STOCK_CMDLINE.split()         # 기존 항목과 순서 보존
    for t in ("video=HDMI-A-1:d", "video=DSI-1:800x1280@60,rotate=90", "logo.nologo", "loglevel=3", "vt.global_cursor_default=0"):
        assert t in toks, t
    assert toks.count("quiet") == 1 and toks.count("splash") == 1
    for f in ("nformare.plymouth", "nformare.script", "logo.png"):
        assert (sandbox.themes / "nformare" / f).is_file(), f
    assert (sandbox.state / "config.txt.orig").read_text(encoding="utf-8") == STOCK_CONFIG     # 처음 상태 백업
    assert (sandbox.state / "cmdline.txt.orig").read_text(encoding="utf-8") == STOCK_CMDLINE
    assert (sandbox.splash_state / "prev-theme").read_text(encoding="utf-8").strip() == "pix"
    assert "재부팅" in r.stdout


def test_second_run_is_idempotent_and_keeps_first_backup(sandbox):
    args = ("--skip", "check", "--disable-hdmi", "--dsi-overlay", "dtoverlay=foo")
    assert sandbox.run(SETUP, *args).returncode == 0
    cfg1, cmd1 = sandbox.config(), sandbox.cmdline()
    assert sandbox.run(SETUP, *args).returncode == 0
    assert sandbox.config() == cfg1 and sandbox.cmdline() == cmd1
    assert (sandbox.state / "config.txt.orig").read_text(encoding="utf-8") == STOCK_CONFIG     # 백업은 처음 것 그대로


def test_skip_option_skips_steps(sandbox):
    r = sandbox.run(SETUP, "--skip", "apt", "--skip", "splash", "--skip", "check", "--skip", "interfaces")
    assert r.returncode == 0, r.stdout + r.stderr
    calls = sandbox.called()
    assert not any(c.startswith("apt-get") for c in calls)
    assert not any("do_ssh" in c for c in calls)
    assert "disable_splash" not in sandbox.config() and not (sandbox.themes / "nformare").exists()
    assert "건너뜀" in r.stdout


def test_uninstall_splash_restores_theme_and_removes_splash_settings(sandbox):
    assert sandbox.run(SETUP, "--skip", "check").returncode == 0
    assert "disable_splash=1" in sandbox.config()
    r = sandbox.run(SETUP, "--uninstall-splash")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "disable_splash" not in sandbox.config()
    assert "logo.nologo" not in sandbox.cmdline()
    assert not (sandbox.themes / "nformare").exists()
    assert "plymouth-set-default-theme -R pix" in sandbox.called()
    assert "enable_uart=1" in sandbox.config()                               # 시리얼 설정은 스플래시와 별개이므로 남는다


def test_multiline_cmdline_is_refused_and_files_untouched(sandbox):
    bad = "root=/dev/sda2\nrootwait\n"
    (sandbox.boot / "cmdline.txt").write_text(bad, encoding="utf-8", newline="\n")
    r = sandbox.run(SETUP, "--skip", "check", "--skip", "apt", "--skip", "splash")
    assert r.returncode != 0
    assert sandbox.cmdline() == bad and sandbox.config() == STOCK_CONFIG
    assert "한 줄" in r.stdout + r.stderr and "실패" in r.stdout


def test_failing_step_does_not_stop_the_others(sandbox):
    (sandbox.boot / "cmdline.txt").write_text("a\nb\n", encoding="utf-8", newline="\n")
    r = sandbox.run(SETUP, "--skip", "check", "--skip", "splash")
    assert r.returncode != 0
    assert any(c.startswith("plymouth") is False for c in sandbox.called())
    assert "raspi-config nonint do_ssh 0" in sandbox.called()                # 뒤 단계도 실행됨
    summary = r.stdout.split("=== 요약 ===")[1]
    assert "bootfiles" in summary and "실패" in summary and "interfaces" in summary


def test_install_splash_logo_option_replaces_the_theme_logo(sandbox, tmp_path):
    """--logo FILE: 장비마다 다른(돌린) 로고를 테마 폴더를 건드리지 않고 설치한다."""
    mine = tmp_path / "my_logo.png"
    mine.write_bytes(b"\x89PNG-landscape-180")
    r = sandbox.run(SPLASH, "--logo", mine.as_posix())
    assert r.returncode == 0, r.stdout + r.stderr
    assert (sandbox.themes / "nformare" / "logo.png").read_bytes() == b"\x89PNG-landscape-180"
    assert "my_logo.png" in r.stdout
    assert (ROOT / "deploy" / "plymouth" / "nformare" / "logo.png").read_bytes() != b"\x89PNG-landscape-180"   # 원본은 그대로


@pytest.mark.parametrize("kind, file", [("landscape", "boot_logo_landscape_90.png"), ("portrait", "boot_logo_rot270.png")])
def test_install_splash_for_option_picks_the_logo_of_that_device_type(sandbox, kind, file):
    """스크립트는 하나이고, 장비 종류(--for)에 따라 로고 이미지만 다르다."""
    r = sandbox.run(SPLASH, "--for", kind)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (sandbox.themes / "nformare" / "logo.png").read_bytes() == (ROOT / "deploy" / file).read_bytes()


def test_install_splash_logo_beats_for_and_bad_for_is_rejected(sandbox, tmp_path):
    mine = tmp_path / "x.png"
    mine.write_bytes(b"\x89PNG-mine")
    assert sandbox.run(SPLASH, "--for", "landscape", "--logo", mine.as_posix()).returncode == 0
    assert (sandbox.themes / "nformare" / "logo.png").read_bytes() == b"\x89PNG-mine"
    r = sandbox.run(SPLASH, "--for", "diagonal")
    assert r.returncode != 0 and "landscape" in r.stderr


@pytest.mark.parametrize("deg, size", [(0, (1029, 326)), (90, (326, 1029)), (180, (1029, 326)), (270, (326, 1029))])
def test_install_splash_rotate_option_turns_the_unrotated_logo(sandbox, deg, size):
    """--rotate DEG: 돌리지 않은 로고를 시계 방향으로 돌려 설치한다 (90/270 은 세로로 선다)."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QImage, QTransform
    r = sandbox.run(SPLASH, "--rotate", str(deg))
    assert r.returncode == 0, r.stdout + r.stderr
    img = QImage(str(sandbox.themes / "nformare" / "logo.png"))
    assert (img.width(), img.height()) == size
    src = QImage(str(ROOT / "deploy" / "boot_logo_centered.png"))
    want = src.transformed(QTransform().rotate(deg), Qt.SmoothTransformation) if deg else src
    assert img.convertToFormat(QImage.Format_ARGB32) == want.convertToFormat(QImage.Format_ARGB32)   # 시계 방향, 화소까지 같다


def test_install_splash_rotate_beats_for_and_rejects_bad_angles(sandbox):
    from PyQt5.QtGui import QImage
    assert sandbox.run(SPLASH, "--for", "landscape", "--rotate", "90").returncode == 0     # --rotate 가 우선: 세로로 선 로고
    img = QImage(str(sandbox.themes / "nformare" / "logo.png"))
    assert img.height() > img.width()
    r = sandbox.run(SPLASH, "--rotate", "45")
    assert r.returncode != 0 and "90" in r.stderr


def test_landscape_logo_file_is_the_unrotated_logo_turned_90_degrees_clockwise():
    """Pi 실기에서 가로 장비는 `--rotate 90` 이 맞았다 (2026-10-26). `--for landscape` 가 쓰는 파일이 그것과 같아야 한다."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QImage, QTransform
    src = QImage(str(ROOT / "deploy" / "boot_logo_centered.png"))
    want = src.transformed(QTransform().rotate(90), Qt.SmoothTransformation)
    got = QImage(str(ROOT / "deploy" / "boot_logo_landscape_90.png"))
    assert got.convertToFormat(QImage.Format_ARGB32) == want.convertToFormat(QImage.Format_ARGB32)
    assert not (ROOT / "deploy" / "boot_logo_landscape_180.png").exists()               # 틀린 각도의 파일은 남기지 않는다


def test_pi_setup_splash_rotate_option_reaches_the_splash_step(sandbox):
    from PyQt5.QtGui import QImage
    r = sandbox.run(SETUP, "--skip", "check", "--splash-rotate", "270")
    assert r.returncode == 0, r.stdout + r.stderr
    img = QImage(str(sandbox.themes / "nformare" / "logo.png"))
    assert (img.width(), img.height()) == (326, 1029)
    assert sandbox.run(SETUP, "--skip", "check", "--splash-rotate", "100").returncode != 0


def test_pi_setup_splash_for_option_reaches_the_splash_step(sandbox):
    """pi_setup.sh --splash-for landscape 로 한 번에 설치해도 가로용(90도) 로고가 들어간다."""
    r = sandbox.run(SETUP, "--skip", "check", "--splash-for", "landscape")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (sandbox.themes / "nformare" / "logo.png").read_bytes() == (ROOT / "deploy" / "boot_logo_landscape_90.png").read_bytes()
    r = sandbox.run(SETUP, "--skip", "check", "--splash-for", "sideways")
    assert r.returncode != 0 and "landscape" in r.stderr


def test_install_splash_without_logo_option_uses_the_theme_logo(sandbox):
    assert sandbox.run(SPLASH).returncode == 0
    assert (sandbox.themes / "nformare" / "logo.png").read_bytes() == (ROOT / "deploy" / "plymouth" / "nformare" / "logo.png").read_bytes()


def test_install_splash_logo_option_errors(sandbox, tmp_path):
    r = sandbox.run(SPLASH, "--logo", (tmp_path / "missing.png").as_posix())
    assert r.returncode != 0 and "로고 파일이 없습니다" in r.stderr and not (sandbox.themes / "nformare").exists()
    r = sandbox.run(SPLASH, "--logo")
    assert r.returncode != 0 and "--logo" in r.stderr


def test_unknown_option_is_rejected(sandbox):
    r = sandbox.run(SETUP, "--no-such-flag")
    assert r.returncode != 0 and "알 수 없는 옵션" in r.stderr


def test_check_step_runs_the_app_self_test_with_mock_firmware(sandbox):
    """설치 확인 단계가 가상 펌웨어로 센서 3개 측정을 실제로 돌려 본다 (화면 없이)."""
    skip_all_but_check = []
    for s in ("apt", "serial", "interfaces", "display", "time", "bootfiles", "splash", "app"):
        skip_all_but_check += ["--skip", s]
    r = sandbox.run(SETUP, *skip_all_but_check)
    assert "앱 자체 시험(가상 펌웨어): ✔" in r.stdout, r.stdout + r.stderr
    assert "CH0" in r.stdout and "'CH2': 4" in r.stdout
