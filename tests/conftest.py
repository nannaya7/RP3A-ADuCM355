"""테스트 세션 전체가 하나의 QApplication 을 공유한다.

QCoreApplication 이 먼저 만들어지면 이후 위젯 테스트(QApplication 필요)가 비정상 종료되므로,
가장 위 클래스인 QApplication 을 세션 시작 시 한 번만 만든다.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture(autouse=True)
def _close_leftover_windows():
    """테스트가 만든 최상위 창을 끝날 때 닫고 지운다.
    그대로 두면 보이는 창이 세션 내내 쌓이고, 나중에 파이썬이 정리하는 시점이 다른 창을 그리는 중과 겹쳐 간헐적으로 비정상 종료했다."""
    yield
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    QApplication.sendPostedEvents(None, 0)                  # deleteLater 처리 (DeferredDelete)
    QApplication.processEvents()


@pytest.fixture(autouse=True)
def _isolated_assay_file(tmp_path, monkeypatch):
    """창이 검사 항목 선택을 실제 data/assay.json 에 쓰거나 읽지 않게 한다."""
    import app.app_window as aw
    monkeypatch.setattr(aw, "_assay_path", lambda root: tmp_path / "assay.json")
