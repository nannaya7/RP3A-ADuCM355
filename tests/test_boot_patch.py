"""deploy/patch_boot_files.py — 부팅 설정 파일 수정 로직 (잘못 고치면 부팅이 안 되므로 꼼꼼히 시험한다)."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("patch_boot_files", Path(__file__).resolve().parent.parent / "deploy" / "patch_boot_files.py")
pb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pb)

# 실제 Pi OS 의 전형적인 cmdline.txt (PARTUUID 는 예시)
STOCK = "console=serial0,115200 console=tty1 root=PARTUUID=abcd1234-02 rootfstype=ext4 fsck.repair=yes rootwait quiet splash plymouth.ignore-serial-consoles cfg80211.ieee80211_regdom=KR\n"

# 사용자가 붙여 준 config.txt 와 같은 구조 (끝이 [all])
CONFIG = """# comment
dtparam=audio=on
camera_auto_detect=1
display_auto_detect=1
auto_initramfs=1
dtoverlay=vc4-kms-v3d
max_framebuffers=2
disable_fw_kms_setup=1
arm_64bit=1
disable_overscan=1
arm_boost=1

[cm4]
otg_mode=1

[cm5]
dtoverlay=dwc2,dr_mode=host

[pi5]
dtoverlay=nospi10

[all]
"""


def test_cmdline_adds_missing_tokens_and_keeps_existing_order():
    out = pb.patch_cmdline(STOCK)
    toks = out.split()
    assert toks[:len(STOCK.split())] == STOCK.split()                    # 기존 항목은 그대로, 순서도 그대로
    for t in ("quiet", "splash", "logo.nologo", "plymouth.ignore-serial-consoles", "loglevel=3", "vt.global_cursor_default=0"):
        assert t in toks
    assert out.endswith("\n") and out.count("\n") == 1                   # 한 줄


def test_cmdline_is_idempotent():
    once = pb.patch_cmdline(STOCK)
    assert pb.patch_cmdline(once) == once


def test_cmdline_does_not_duplicate_existing_flags():
    out = pb.patch_cmdline(STOCK).split()
    assert out.count("quiet") == 1 and out.count("splash") == 1


def test_cmdline_replaces_existing_loglevel_value():
    out = pb.patch_cmdline("root=/dev/sda2 loglevel=7 rootwait\n").split()
    assert "loglevel=3" in out and "loglevel=7" not in out and out.count("loglevel=3") == 1


def test_cmdline_without_trailing_newline_and_extra_spaces():
    out = pb.patch_cmdline("root=/dev/sda2   rootwait")
    assert out.startswith("root=/dev/sda2 rootwait ") and out.endswith("\n")


@pytest.mark.parametrize("bad", ["", "   \n", "root=/dev/sda2\nrootwait\n", "a\r\nb\r\n"])
def test_cmdline_refuses_empty_or_multiline(bad):
    with pytest.raises(ValueError):
        pb.patch_cmdline(bad)


def test_config_appends_disable_splash_in_all_section():
    out = pb.patch_config(CONFIG)
    assert out.endswith("[all]\ndisable_splash=1\n") and out.count("disable_splash") == 1
    assert out.startswith(CONFIG)                                        # 기존 내용은 그대로


def test_config_is_idempotent_and_fixes_zero():
    once = pb.patch_config(CONFIG)
    assert pb.patch_config(once) == once
    assert "disable_splash=1" in pb.patch_config("disable_splash=0\n[all]\n")
    assert "disable_splash=0" not in pb.patch_config("disable_splash=0\n[all]\n")


def test_config_not_ending_in_all_gets_all_section_first():
    out = pb.patch_config("arm_64bit=1\n[pi5]\ndtoverlay=nospi10\n")
    assert out.endswith("[all]\ndisable_splash=1\n")                     # [pi5] 아래에 두면 다른 모델에는 적용되지 않는다


def test_config_without_sections_and_without_trailing_newline():
    assert pb.patch_config("arm_64bit=1") == "arm_64bit=1\ndisable_splash=1\n"
    assert pb.patch_config("") == "disable_splash=1\n"


def test_cli_dry_run_writes_nothing_and_real_run_writes(tmp_path):
    cmd, cfg = tmp_path / "cmdline.txt", tmp_path / "config.txt"
    cmd.write_text(STOCK, encoding="utf-8")
    cfg.write_text(CONFIG, encoding="utf-8")
    assert pb.main(["--cmdline", str(cmd), "--config", str(cfg), "--dry-run"]) == 0
    assert cmd.read_text(encoding="utf-8") == STOCK and cfg.read_text(encoding="utf-8") == CONFIG
    assert pb.main(["--cmdline", str(cmd), "--config", str(cfg)]) == 0
    assert "logo.nologo" in cmd.read_text(encoding="utf-8") and "disable_splash=1" in cfg.read_text(encoding="utf-8")
    assert b"\r\n" not in cmd.read_bytes() and b"\r\n" not in cfg.read_bytes()      # LF 로 쓴다 (Windows 에서 돌려도)


def test_cli_leaves_files_untouched_on_multiline_cmdline(tmp_path, capsys):
    cmd, cfg = tmp_path / "cmdline.txt", tmp_path / "config.txt"
    cmd.write_text("root=/dev/sda2\nrootwait\n", encoding="utf-8")
    cfg.write_text(CONFIG, encoding="utf-8")
    assert pb.main(["--cmdline", str(cmd), "--config", str(cfg)]) == 1
    assert cmd.read_text(encoding="utf-8") == "root=/dev/sda2\nrootwait\n" and cfg.read_text(encoding="utf-8") == CONFIG
    assert "한 줄" in capsys.readouterr().err


# ---- 확장: 스플래시 없이 임의 줄/항목만 추가 (pi_setup.sh 가 시리얼, DSI overlay 등에 사용) ----
def test_config_extra_lines_only_without_splash():
    out = pb.patch_config(CONFIG, splash=False, extra_lines=["enable_uart=1", "dtoverlay=vc4-kms-dsi-waveshare-panel-v2,10_1_inch_a"])
    assert "disable_splash" not in out
    assert out.endswith("[all]\nenable_uart=1\ndtoverlay=vc4-kms-dsi-waveshare-panel-v2,10_1_inch_a\n")


def test_config_extra_lines_are_idempotent_and_exact_match():
    once = pb.patch_config(CONFIG, splash=False, extra_lines=["enable_uart=1"])
    assert pb.patch_config(once, splash=False, extra_lines=["enable_uart=1"]) == once
    assert pb.patch_config("dtoverlay=vc4-kms-v3d\n[all]\n", splash=False, extra_lines=["dtoverlay=vc4-kms-v3d"]) == "dtoverlay=vc4-kms-v3d\n[all]\n"


def test_config_no_changes_returns_same_content():
    assert pb.patch_config(CONFIG, splash=False) == CONFIG


def test_config_rejects_bad_extra_line():
    for bad in ("", "a\nb"):
        with pytest.raises(ValueError):
            pb.patch_config(CONFIG, splash=False, extra_lines=[bad])


def test_cmdline_extra_tokens_without_splash():
    out = pb.patch_cmdline(STOCK, splash=False, extra_tokens=["video=HDMI-A-1:d"])
    assert out == STOCK.rstrip("\n") + " video=HDMI-A-1:d\n"
    assert pb.patch_cmdline(out, splash=False, extra_tokens=["video=HDMI-A-1:d"]) == out


def test_cmdline_extra_key_value_replaces_existing_value():
    out = pb.patch_cmdline("root=/dev/sda2 vt.global_cursor_default=1\n", splash=False,
                           extra_tokens=["vt.global_cursor_default=0"]).split()
    assert out.count("vt.global_cursor_default=0") == 1 and "vt.global_cursor_default=1" not in out


def test_cmdline_rejects_token_with_space():
    with pytest.raises(ValueError):
        pb.patch_cmdline(STOCK, splash=False, extra_tokens=["a b"])


def test_cli_extra_options(tmp_path):
    cmd, cfg = tmp_path / "cmdline.txt", tmp_path / "config.txt"
    cmd.write_text(STOCK, encoding="utf-8")
    cfg.write_text(CONFIG, encoding="utf-8")
    assert pb.main(["--cmdline", str(cmd), "--config", str(cfg), "--no-splash", "--config-line", "enable_uart=1",
                    "--cmdline-token", "video=HDMI-A-1:d"]) == 0
    assert "enable_uart=1" in cfg.read_text(encoding="utf-8") and "disable_splash" not in cfg.read_text(encoding="utf-8")
    assert cmd.read_text(encoding="utf-8").endswith("video=HDMI-A-1:d\n") and "logo.nologo" not in cmd.read_text(encoding="utf-8")


def test_cmdline_repeatable_keys_like_video_are_not_overwritten():
    out = pb.patch_cmdline("root=/dev/sda2 video=DSI-1:800x1280@60,rotate=90\n", splash=False,
                           extra_tokens=["video=HDMI-A-1:d"]).split()
    assert "video=DSI-1:800x1280@60,rotate=90" in out and "video=HDMI-A-1:d" in out      # 둘 다 남는다
    again = pb.patch_cmdline(" ".join(out) + "\n", splash=False, extra_tokens=["video=HDMI-A-1:d"]).split()
    assert again.count("video=HDMI-A-1:d") == 1                                          # 중복 없음


def test_disable_splash_inside_model_specific_section_is_not_enough():
    """[cm5] 안에만 있는 disable_splash=1 은 다른 Pi 에 적용되지 않으므로 [all] 에 다시 넣는다."""
    out = pb.patch_config("dtoverlay=vc4-kms-v3d\n[cm5]\ndisable_splash=1\n")
    lines = out.splitlines()
    assert lines.index("[all]") > lines.index("[cm5]") and lines[-1] == "disable_splash=1"
    assert pb.patch_config(out) == out                                # 두 번째에는 변화 없음


def test_disable_splash_already_in_all_section_is_left_alone():
    text = "[all]\nenable_uart=1\ndisable_splash=1\n"
    assert pb.patch_config(text) == text
