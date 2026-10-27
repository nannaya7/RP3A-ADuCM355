"""앱 최상위 창. 페이지는 QStackedWidget 한 곳에서 관리하고, 전환은 go_to() 로만 한다."""
import dataclasses
import logging
import time

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QApplication, QLayout, QMessageBox, QStackedWidget, QWidget

from pathlib import Path

from app.auth.skip_auth import SkipAuth
from app.comm.firmware_client import FirmwareClient
from app.comm.traffic_log import TrafficLog
from app.comm.sensor import BUILTIN, OFF, PATCH, SensorStore, describe, make_transport, normalize
from app.comm.uart_worker import UartWorker
from app.measure.controller import MeasureController, State
from app.measure.stages import MeasureSettings, troponin_stages
from app.measure.profiles import ProfileStore
from app.measure.store import SessionStore
from app.net import create_bluetooth, create_wifi
from app.ui.gear_button import GearButton
from app.update import guard
from app.update.controller import UpdateController, restart_process
from app.version import VERSION
from app.ui.dashboard_page import DashboardPage
from app.ui.dashboard_portrait import PortraitDashboard
from app.ui.history_page import HistoryPage
from app.ui.login_page import LoginPage
from app.ui.monitor_page import MonitorPage
from app.ui.profile_edit_page import ProfileEditPage
from app.ui.settings_page import SettingsPage
from app.ui.virtual_keyboard import VirtualKeyboard

from .config import Config
from .display import DisplayProfile
from .state import Session

log = logging.getLogger(__name__)


# 우측 상단 설정 버튼: (크기, 오른쪽 여백, 위 여백). 측정 화면의 '뒤로' 버튼과 세로 중심이 같도록 잡았다.
GEAR_PORTRAIT = (44, 12, 12)
GEAR_LANDSCAPE = (44, 24, 12)

# 세로 패널은 보이는 영역이 실제 해상도보다 조금 작아 맨 아래 글자가 잘린다 → 아래쪽에 쓰지 않는 여백을 두고 화면을 그만큼 올린다.
# (기본 20px, config.ini [display] bottom_margin 으로 조절)
BG_DEFAULT, BG_BLUE = QColor("#E9F1ED"), QColor("#F2F6FB")       # theme.qss 의 페이지 배경 (초록 계열 / 측정·프로필·이력 파랑 계열)
BLUE_PAGES = ("dashPage", "profilePage", "historyPage")
PATCH_NOT_CONNECTED = "먼저 센서를 연결해 주세요."


class AppWindow(QStackedWidget):
    def __init__(self, profile: DisplayProfile, cfg: Config):
        super().__init__()
        self.profile = profile
        self.cfg = cfg
        self.session = Session()
        self.auth = SkipAuth()  # 단계 5 에서 서버 인증으로 교체
        self.setWindowTitle("Vital")
        if cfg.fullscreen:
            self.setWindowFlag(Qt.FramelessWindowHint, True)
        else:
            self.setFixedSize(profile.size)

        # 페이지 내용의 최소 높이가 창 크기를 키우지 못하게 한다 (전체화면에서 창이 화면보다 커져 아래가 잘렸다)
        self.layout().setSizeConstraint(QLayout.SetNoConstraint)
        self._bottom_safe = cfg.bottom_margin if profile.is_portrait else 0
        self.setContentsMargins(0, 0, 0, self._bottom_safe)

        self.login = LoginPage(show_skip=cfg.skip_login, portrait=profile.is_portrait)
        # UART → 펌웨어 클라이언트 → 측정 컨트롤러 (화면은 컨트롤러의 ViewState 만 그린다)
        root = Path(__file__).resolve().parent.parent
        self.sensor_store = SensorStore(root / "data" / "sensor.json")      # 설정 > 센서 에서 고른 센서 (재시작해도 유지)
        self.sensor_mode = self.sensor_store.load(normalize(cfg.sensor_default))
        self._link_error = ""
        self._link_up = False
        self._probe = None                                    # 패치 센서를 켜는 중이면 진행 정보
        self.probe_timeout_s = 20.0                           # 포트 열기 + STATUS 응답을 기다리는 최대 시간
        self._patch_sel = self.sensor_store.load_patch()      # 설정 > 센서 에서 고른 패치 센서 (주소, 이름). 없으면 config.ini 기준
        self.worker = UartWorker(make_transport(self.sensor_mode, self._sensor_cfg()))
        self.client = FirmwareClient(self.worker)
        root = Path(__file__).resolve().parent.parent
        results = Path(cfg.results_dir)
        self.controller = MeasureController(
            self.client, self._measure_settings(cfg), troponin_stages(cfg.reaction_wait_s, cfg.auto_start_last),
            store=SessionStore(results if results.is_absolute() else root / results))
        self.traffic = TrafficLog(self.worker)                  # 앱이 켜져 있는 동안 UART 송수신을 계속 기록한다
        self.monitor = MonitorPage(self.traffic, portrait=profile.is_portrait,
                                   save_dir=results if results.is_absolute() else root / results)
        results_dir = results if results.is_absolute() else root / results
        self.profiles = ProfileStore(root / "data" / "profiles.json")     # 세로 화면의 프로필(가족 구성원) 목록
        self.profile_edit = self.history_page = None
        if profile.is_portrait:
            self.measure = PortraitDashboard(cfg, self.profiles, results_dir=results_dir)
            self.profile_edit = ProfileEditPage(self.profiles)
            self.history_page = HistoryPage(results_dir)
        else:
            self.measure = DashboardPage(cfg, results_dir=results_dir)
        self.measure.bind(self.controller)
        self.bluetooth = create_bluetooth(cfg.net_mock)
        self.settings = SettingsPage(create_wifi(cfg.net_mock), self.bluetooth,
                                     portrait=profile.is_portrait)
        self.settings.bt.scan_guard = self._bt_scan_block_reason
        self._probe_timer = QTimer(self)                     # 패치 센서 확인 중에만 도는 타이머 (창에 묶여 있어 안전)
        self._probe_timer.setInterval(150)
        self._probe_timer.timeout.connect(self._probe_tick)
        self.settings.sensor.set_mode(self.sensor_mode)
        self.settings.sensorModeRequested.connect(self._on_sensor_mode)
        self.settings.sensor.set_picked(*self._patch_sel)
        self.settings.sensor.scanRequested.connect(self._on_patch_scan)
        self.settings.sensor.patchSelected.connect(self._on_patch_selected)
        self.settings.sensor.patchCleared.connect(self._on_patch_cleared)
        self.worker.connectionChanged.connect(self._on_link_changed)
        self.controller.viewChanged.connect(self._on_controller_view)      # STATUS 확인 결과 반영
        self.worker.errorOccurred.connect(self._on_link_error)
        self._refresh_sensor_status()
        self.addWidget(self.login)
        self.addWidget(self.measure)
        self.addWidget(self.settings)
        self.addWidget(self.monitor)
        self._overlays = [self.settings, self.monitor]       # 설정 버튼을 숨기는(자체 뒤로 버튼이 있는) 화면들
        for extra in (self.profile_edit, self.history_page):
            if extra is not None:
                self.addWidget(extra)
                self._overlays.append(extra)
        self._return_page = self.login               # 설정 화면에서 '뒤로' 갔을 때 돌아갈 화면

        # 우측 상단 설정 버튼 (로그인/측정 화면 위에 얹는다)
        size, self._gear_right, self._gear_top = GEAR_PORTRAIT if profile.is_portrait else GEAR_LANDSCAPE
        self.gear = GearButton(self, size)
        self.gear.clicked.connect(self._open_settings)
        self._place_gear()

        # 업데이트: 확인·설치는 설정 > 정보 에서 사용자가 버튼으로 한다. 새 버전이 있으면 톱니바퀴에 점이 뜬다.
        self.updates = UpdateController(cfg, root, blocked=self._update_blocked_reason, restart=self._restart_app, parent=self)
        self.settings.info.set_info(VERSION, cfg.update_url)
        self.settings.info.checkRequested.connect(lambda: self.updates.check())
        self.settings.info.installRequested.connect(self._confirm_install)
        self.updates.stateChanged.connect(self.settings.info.set_state)
        self.updates.availabilityChanged.connect(self.gear.set_badge)
        self._update_root = root
        self._start_timer = QTimer(self)                     # 시작 후 한 번 조용히 새 버전 확인
        self._start_timer.setSingleShot(True)
        self._start_timer.timeout.connect(lambda: self.updates.check(silent=True))
        if cfg.update_check_on_start and self.updates.enabled:
            self._start_timer.start(20000)
        self._healthy_timer = QTimer(self)                   # 한동안 정상으로 떠 있으면 방금 한 업데이트를 확정
        self._healthy_timer.setSingleShot(True)
        self._healthy_timer.timeout.connect(lambda: guard.mark_healthy(self._update_root))
        self._healthy_timer.start(30000)

        # 앱 내장 터치 키보드 (페이지 위에 겹쳐 표시)
        self.keyboard = VirtualKeyboard(self, key_height=profile.touch_min, compact=profile.is_portrait)
        self.keyboard.visibilityChanged.connect(self._on_keyboard)
        if cfg.virtual_keyboard:
            self.keyboard.attach(QApplication.instance())
        self.currentChanged.connect(lambda _i: self.keyboard.hide_keyboard())
        self.currentChanged.connect(lambda _i: self._update_gear())

        self.login.skipRequested.connect(self._on_skip)
        self.login.loginRequested.connect(self._on_login_requested)
        self.measure.backRequested.connect(self._on_back)
        self.settings.backRequested.connect(self._close_settings)
        self.measure.monitorRequested.connect(self._open_monitor)
        self.monitor.backRequested.connect(self._close_monitor)
        if self.profile_edit is not None:
            self.measure.historyRequested.connect(self._open_history)
            self.history_page.backRequested.connect(self._close_overlay)
            self.measure.profileEditRequested.connect(self._open_profile_edit)
            self.profile_edit.cancelled.connect(self._close_overlay)
            self.profile_edit.saved.connect(self._on_profile_saved)
            self.profile_edit.deleted.connect(self._on_profile_deleted)
        self._update_gear()

    @staticmethod
    def _measure_settings(cfg: Config) -> MeasureSettings:
        chans = tuple(int(c) for c in cfg.channels.replace(" ", "").split(",") if c != "")
        return MeasureSettings(start_hz=cfg.sweep_start_hz, stop_hz=cfg.sweep_stop_hz, points=cfg.sweep_points,
                               channels=chans or (0, 1, 2), rtia_ohm=cfg.rtia_ohm, elapsed_min=cfg.elapsed_min,
                               c0_source=cfg.c0_source if cfg.c0_source in ("first", "none") else "first",
                               reaction_timer_start=cfg.reaction_timer_start)

    # ---- 설정 > 센서 (패치 센서 = 블루투스 / 내장 센서 = UART, 동시에 하나만) ----
    def _test_in_progress(self) -> bool:
        """측정 중이거나 검사가 진행 중(1단계 이상, 아직 끝나지 않음)인가."""
        v = self.controller.snapshot()
        busy = v.state in (State.CONFIGURING, State.MEASURING, State.STOPPING, State.COMPUTING)
        return busy or (v.stage_index > 0 and v.state not in (State.DONE, State.ERROR))

    def _sensor_switch_blocked(self) -> str:
        """센서를 바꿀 수 없는 이유 (바꿀 수 있으면 빈 문자열). 측정 중이거나 검사가 진행 중이면 다른 센서 값이 섞인다."""
        if self._test_in_progress():
            return "검사 중에는 센서를 바꿀 수 없습니다. 검사를 끝내거나 측정 화면에서 [처음부터]를 누른 뒤 바꿔 주세요."
        return ""

    # ---- 업데이트 ----
    def _update_blocked_reason(self) -> str:
        if self._test_in_progress():
            return "검사 중에는 업데이트할 수 없습니다. 검사를 끝낸 뒤에 해 주세요."
        return ""

    def _confirm_install(self) -> None:
        m = self.updates.manifest
        if m is None:
            return
        box = QMessageBox(QMessageBox.Question, "업데이트", f"{m.version} 을(를) 설치하고 앱을 다시 시작할까요?",
                          QMessageBox.Yes | QMessageBox.No, self)
        box.setDefaultButton(QMessageBox.No)
        if box.exec_() == QMessageBox.Yes:
            self.updates.install()

    def _restart_app(self) -> None:
        self.shutdown()
        restart_process()

    def _on_sensor_mode(self, mode: str) -> None:
        mode = normalize(mode, OFF)
        why = self._sensor_switch_blocked()
        if why:
            self.settings.sensor.show_msg(why, "error")
            self.settings.sensor.set_mode(self.sensor_mode)          # 토글을 제자리로
            return
        if mode == PATCH:                                           # 패치 센서는 실제로 연결해 모듈이 응답해야 켠다
            self._probe_patch()
            return
        self._apply_sensor_mode(mode)

    def _apply_sensor_mode(self, mode: str) -> None:
        self.set_sensor_mode(mode)
        names = {PATCH: "패치 센서", BUILTIN: "내장 센서"}
        self.settings.sensor.show_msg(f"{names[mode]}를 켰습니다." if mode in names else "센서를 모두 껐습니다.")

    # ---- 패치 센서 켜기: 연결 → STATUS 조회 → 응답이 있으면 확정, 없으면 되돌리고 팝업 ----
    def _probe_patch(self) -> None:
        """패치 센서 연결로 바꾸고 컨트롤러의 모듈 확인(STATUS/CALSTATUS/ENV)이 끝나기를 기다린다.
        응답(READY)이면 켜진 것으로 저장하고, 포트가 안 열리거나 모듈이 응답하지 않으면 이전 센서로 되돌린다."""
        self._probe = {"prev": self.sensor_mode, "t0": time.monotonic(), "restarted": False}
        self._link_up = False                                         # 새 연결이 올라온 뒤의 상태만 본다
        self.set_sensor_mode(PATCH, persist=False)
        self.settings.sensor.set_locked(True)
        self.settings.sensor.show_msg("패치 센서에 연결하고 모듈을 확인하는 중…")
        self._probe_timer.start()

    def _probe_tick(self) -> None:
        pr = self._probe
        if pr is None:
            self._probe_timer.stop()
            return
        if self._link_up:
            st = self.controller.state
            if st in (State.DONE, State.ERROR) and not pr["restarted"]:
                pr["restarted"] = True                                # 검사가 끝난 상태에서는 모듈 확인이 저절로 다시 돌지 않는다
                self.controller.restart()
            elif st == State.READY:
                return self._probe_done(True)
            elif st == State.NO_MODULE:
                return self._probe_done(False)
        if time.monotonic() - pr["t0"] > self.probe_timeout_s:        # 포트가 안 열리거나 확인이 끝나지 않음
            self._probe_done(False)

    def _probe_done(self, ok: bool) -> None:
        pr, self._probe = self._probe, None
        self._probe_timer.stop()
        self.settings.sensor.set_locked(False)
        if ok:
            self.sensor_store.save(PATCH)
            self.settings.sensor.show_msg("패치 센서를 켰습니다.")
            return
        self.set_sensor_mode(pr["prev"], persist=False)               # 이전 센서로 되돌린다 (토글도 제자리)
        self.settings.sensor.show_msg(PATCH_NOT_CONNECTED, "error")
        self.notify(PATCH_NOT_CONNECTED)

    # ---- 패치 센서 선택 (센서가 여러 대일 때) ----
    def _sensor_cfg(self) -> Config:
        """고른 패치 센서가 있으면 그 주소로 연결하도록 바꾼 설정 (config.ini 의 patch_address 보다 우선)."""
        addr = self._patch_sel[0]
        return dataclasses.replace(self.cfg, patch_address=addr) if addr else self.cfg

    def _on_patch_scan(self) -> None:
        from app.comm.ble_transport import BleFound, scan_patch_sensors
        why = self._bt_scan_block_reason() or self._sensor_switch_blocked()
        if why:
            self.settings.sensor.show_msg(why, "error")
            return
        sp = self.settings.sensor
        sp.show_msg("패치 센서를 검색하는 중…")
        sp.set_scanning(True)
        if self.cfg.uart_mock:                                      # 가상 모드: 실제 라디오 없이 화면만 확인
            fake = [BleFound("nFor20-t01", "CB:74:84:B6:2B:63", -58), BleFound("nFor20-t02", "FD:41:B5:7D:8E:23", -71)]
            self.settings.runner.submit(lambda: fake, self._on_patch_scanned)
            return
        self.settings.runner.submit(lambda: scan_patch_sensors(self.cfg.patch_name), self._on_patch_scanned)

    def _on_patch_scanned(self, found, err: str) -> None:
        sp = self.settings.sensor
        sp.set_scanning(False)
        if err:
            sp.set_found([])
            sp.show_msg(f"검색하지 못했습니다. {err}", "error")
        elif not found:
            sp.set_found([])
            sp.show_msg("패치 센서를 찾지 못했습니다. 센서 전원과 거리를 확인하세요. (이미 연결된 센서는 검색되지 않습니다)", "error")
        else:
            sp.set_found(found)
            sp.show_msg(f"{len(found)}대를 찾았습니다. 연결할 센서를 선택하세요.")

    def _on_patch_selected(self, address: str, name: str) -> None:
        why = self._sensor_switch_blocked()
        if why:
            self.settings.sensor.show_msg(why, "error")
            return
        self._set_patch_sel(address, name)
        self.settings.sensor.show_msg(f"패치 센서 {name or address} 을(를) 선택했습니다.")

    def _on_patch_cleared(self) -> None:
        why = self._sensor_switch_blocked()
        if why:
            self.settings.sensor.show_msg(why, "error")
            return
        self._set_patch_sel("", "")
        self.settings.sensor.show_msg("선택을 해제했습니다. 이름이 nFor 로 시작하는 장치에 자동으로 연결합니다.")

    def _set_patch_sel(self, address: str, name: str) -> None:
        self._patch_sel = (address, name)
        self.sensor_store.save_patch(address, name)
        self.settings.sensor.set_picked(address, name)
        if self.sensor_mode == PATCH:                               # 패치 센서가 켜져 있으면 새 장치로 다시 연결한다
            self.set_sensor_mode(PATCH, persist=False)

    def notify(self, text: str) -> None:
        """사용자에게 알리는 팝업 (확인 버튼 하나)."""
        box = QMessageBox(QMessageBox.Information, "센서", text, QMessageBox.Ok, self)
        box.exec_()

    def set_sensor_mode(self, mode: str, persist: bool = True) -> None:
        """센서를 바꾼다(persist 이면 저장도). 워커가 이전 연결을 닫고 새 장치로 다시 연결한다."""
        self.sensor_mode = mode
        self._link_error = ""
        if persist:
            self.sensor_store.save(mode)
        self.worker.set_transport(make_transport(mode, self._sensor_cfg()))
        self.settings.sensor.set_mode(mode)
        self._refresh_sensor_status()
        log.info("sensor mode: %s", mode)

    def _bt_scan_block_reason(self) -> str:
        """패치 센서(블루투스)로 검사하는 중에는 블루투스 검색을 막는다 (검색이 센서 통신을 느리게/끊기게 할 수 있다)."""
        if self.sensor_mode == PATCH and (self._probe is not None or self._sensor_switch_blocked()):
            return "패치 센서를 사용하는 중에는 블루투스 검색을 할 수 없습니다. 검사가 끝난 뒤에 검색해 주세요."
        return ""

    def _on_controller_view(self, _view=None) -> None:
        self._refresh_sensor_status()

    def _on_link_changed(self, connected: bool) -> None:
        if connected:
            self._link_error = ""
        self._refresh_sensor_status(connected)

    def _on_link_error(self, msg: str) -> None:
        self._link_error = msg
        self._refresh_sensor_status()

    def _refresh_sensor_status(self, connected=None) -> None:
        if connected is not None:
            self._link_up = connected
        on = self.sensor_mode != OFF
        up = self._link_up and on
        detail = describe(self.sensor_mode, self._sensor_cfg()) if on else ""
        checking = False
        if up:                                                        # 포트가 열려도 모듈이 STATUS 에 응답해야 '연결됨'
            st = self.controller.state
            if st == State.CHECKING:
                checking = True
            elif st == State.NO_MODULE:
                up, detail = False, "모듈이 응답하지 않음 (" + detail + ")"
        if not up and self._link_error:
            detail = self._link_error
        self.settings.sensor.set_connection(up, detail, checking)

    def start_uart(self) -> None:
        self.worker.start()

    def shutdown(self) -> None:
        """앱 종료 시: UART 스레드와 결과 파일을 정리한다."""
        self.worker.stop()
        self.updates.wait(3000)
        self.settings.shutdown()
        if self.controller.store is not None:
            self.controller.store.close()

    def _on_keyboard(self, visible: bool, height: int) -> None:
        self._update_gear(keyboard=visible)
        page = self.currentWidget()
        if hasattr(page, "on_keyboard"):
            page.on_keyboard(visible, height)

    # ---- 설정 버튼 ----
    def _place_gear(self) -> None:
        self.gear.move(self.width() - self._gear_right - self.gear.width(), self._gear_top)

    def _update_gear(self, keyboard=None) -> None:
        """설정 화면에서는 숨기고, 키보드가 열려 있을 때도 숨긴다(입력란과 겹치므로). 그 외에는 항상 맨 위에 보인다."""
        show = self.currentWidget() not in self._overlays and not (self.keyboard.isVisible() if keyboard is None else keyboard)
        self.gear.setVisible(show)
        if show:
            self._place_gear()
            self.gear.raise_()

    def _open_settings(self) -> None:
        self._return_page = self.currentWidget()
        self.go_to(self.settings)
        self.settings.open()

    def _close_settings(self) -> None:
        self.go_to(self._return_page)

    def _open_monitor(self) -> None:
        self._return_page = self.currentWidget()
        self.go_to(self.monitor)

    def _close_monitor(self) -> None:
        self.go_to(self._return_page)

    # ---- 세로 화면: 프로필 편집 / 검사 이력 ----
    def _close_overlay(self) -> None:
        self.go_to(self._return_page)

    def _open_history(self) -> None:
        self._return_page = self.currentWidget()
        self.go_to(self.history_page)

    def _open_profile_edit(self, pid: str) -> None:
        self._return_page = self.currentWidget()
        if pid:
            self.profile_edit.open_edit(pid)
        else:
            self.profile_edit.open_new()
        self.go_to(self.profile_edit)

    def _on_profile_saved(self, pid: str) -> None:
        self.measure.refresh_profiles(select=pid)             # 방금 저장한 프로필을 바로 고른다
        self._close_overlay()

    def _on_profile_deleted(self, _pid: str) -> None:
        self.measure.refresh_profiles()
        self._close_overlay()

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        if self._bottom_safe:                         # 맨 아래 여백 띠: 지금 페이지의 배경색으로 이어 칠한다
            page = self.currentWidget()
            color = BG_BLUE if page is not None and page.objectName() in BLUE_PAGES else BG_DEFAULT
            QPainter(self).fillRect(0, self.height() - self._bottom_safe, self.width(), self._bottom_safe, color)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._place_gear()
        if self.keyboard.isVisible():
            self.keyboard.reposition()

    def go_to(self, page: QWidget) -> None:
        self.setCurrentWidget(page)

    def _on_skip(self) -> None:
        result = self.auth.login("", "", "")
        if result.ok:
            self.go_to(self.measure)

    def _on_login_requested(self, role, user_id, _password, _remember) -> None:
        log.info("login requested (role=%s, id=%s) - server auth is not implemented yet", role, user_id)

    def _on_back(self) -> None:
        self.session.clear()
        self.go_to(self.login)
