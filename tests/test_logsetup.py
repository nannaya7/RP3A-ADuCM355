"""시작 시 콘솔 출력 정리: 로그 수준, 실행 폴더 권한, 무해한 Qt 경고."""
import logging
import os
import stat

import pytest

from app.config import load_config
from app.logsetup import fix_runtime_dir, is_harmless, level_from

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX 권한 시험")


def test_default_level_is_warning_and_verbose_flags():
    assert level_from("warning") == logging.WARNING
    assert level_from("", 0) == logging.WARNING and level_from("nonsense") == logging.WARNING
    assert level_from("debug") == logging.DEBUG and level_from("INFO") == logging.INFO
    assert level_from("warning", 1) == logging.INFO and level_from("warning", 2) == logging.DEBUG   # -v / -vv 가 우선


def test_config_log_level(tmp_path):
    p = tmp_path / "c.ini"
    assert load_config(p).log_level == "warning"                  # 파일 없음 → 기본
    p.write_text("[app]\nlog_level = Info\n", encoding="utf-8")
    assert load_config(p).log_level == "info"


def test_known_noise_is_filtered_but_real_warnings_are_not():
    assert is_harmless("Wayland does not support QWindow::requestActivate()")
    assert is_harmless("QStandardPaths: wrong permissions on runtime directory /run/user/1000, 0770 instead of 0700")
    assert not is_harmless("qt.qpa.xcb: could not connect to display")
    assert not is_harmless("This application failed to start because no Qt platform plugin could be initialized")


@posix_only
def test_fix_runtime_dir_repairs_own_dir(tmp_path, monkeypatch):
    d = tmp_path / "run"
    d.mkdir()
    os.chmod(d, 0o770)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(d))
    assert fix_runtime_dir() is True
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    assert fix_runtime_dir() is False                              # 이미 0700 이면 건드리지 않는다


def test_fix_runtime_dir_ignores_missing_or_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert fix_runtime_dir() is False
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "nope"))
    assert fix_runtime_dir() is False
