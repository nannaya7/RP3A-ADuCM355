"""Vital 로그인 페이지 — frontend/vital LoginPage 의 PyQt5 UI 재현. 창 크기·제목은 AppWindow 가 관리한다.

가로(1280x800): 배경 사진 위에 중앙 카드.
세로(480x800): 위쪽 사진 → 헤드라인 → 역할 탭 → ID/PW → 로그인 → 건너뛰기(개발용) → 하단 로고.
"""
import re
from typing import Optional

from PyQt5.QtCore import QEvent, QStringListModel, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PyQt5.QtWidgets import (QCheckBox, QCompleter, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                             QWidget)

from .theme import ASSETS
from .widgets import BrandLockup, Field, RoleTabs

CARD_WIDTH = 500
PAGE_BG = QColor("#E9F1ED")
LOGO_MARGIN_X, LOGO_MARGIN_Y = 20, 18       # 세로 화면 좌측 상단 로고 위치 (사진 위)
LANDSCAPE_HEADLINE_POS = (42, 40)           # 가로 화면 좌측 상단 헤드라인 위치
CARD_DROP = 110                             # 가로 화면 로그인 카드를 가운데에서 아래로 내린 양
SIGNUP_GAP, SIGNUP_H = 8, 24               # 세로 화면 회원가입 안내 (버튼 아래)
BODY_LIFT = 51                              # 세로 화면 입력 영역을 위로 올린 양 (아래 여백으로 구현)
HEADLINE_CENTER_Y = 380                     # 세로 화면 헤드라인의 세로 중심 (사진 아래쪽 흐려지는 부분 위)

ROLE_TABS = [("GENERAL", "일반"), ("MEDICAL", "의료진"), ("HOSPITAL", "기관")]
ROLE_TABS_PORTRAIT = [("GENERAL", "일반 회원"), ("MEDICAL", "의료진"), ("HOSPITAL", "의료기관")]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

HEADLINE_HTML = ('<span style="color:#2B2B2B;">보다 나은 삶,</span><br>'
                 '<span style="color:#0C8444;">진단에서 시작합니다.</span>')

SIGNUP_HTML = ('아직 엔포마레 회원이 아니신가요? <a href="#signup" style="color:#0C8444; '
               'font-weight:600; text-decoration:none;">회원가입</a>')


class HeroImage(QWidget):
    """세로 로그인 위쪽 사진. 폭에 맞춰 축소하고 위쪽을 기준으로 아래를 잘라 낸 뒤, 아래쪽을 배경색으로 페이드한다."""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._src = QPixmap(str(path))
        self._cache = None
        self._key = None
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._overlay = None          # (위젯, 세로 중심) — 사진 위에 얹는 헤드라인

    def place_center(self, widget, center_y: int) -> None:
        self._overlay = (widget, center_y)
        self._place()

    def _place(self):
        if self._overlay:
            w, cy = self._overlay
            h = w.sizeHint().height()
            w.setGeometry(0, cy - h // 2, self.width(), h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()

    def _scaled(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        key = (self.width(), dpr)
        if self._key != key:
            pm = self._src.scaledToWidth(round(self.width() * dpr), Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self._cache, self._key = pm, key
        return self._cache

    def paintEvent(self, _):
        if self._src.isNull() or self.width() <= 0:
            return
        p = QPainter(self)
        pm = self._scaled()
        shown_h = pm.height() / pm.devicePixelRatio()
        p.drawPixmap(0, 0, pm)
        if shown_h > self.height():          # 잘렸으면 잘린 가장자리가 보이지 않게 아래를 배경색으로 녹인다
            fade = max(40, int(self.height() * 0.35))
            g = QLinearGradient(0, self.height() - fade, 0, self.height())
            g.setColorAt(0, QColor(PAGE_BG.red(), PAGE_BG.green(), PAGE_BG.blue(), 0))
            g.setColorAt(1, PAGE_BG)
            p.fillRect(0, self.height() - fade, self.width(), fade + 1, g)


class LoginPage(QWidget):
    # (role, email, password, remember_me) — 1차는 UI 만이라 연결 대상 없음
    loginRequested = pyqtSignal(str, str, str, bool)
    skipRequested = pyqtSignal()  # 개발용 건너뛰기

    def __init__(self, show_skip: bool = True, portrait: bool = False):
        super().__init__()
        self._show_skip = show_skip
        self._portrait = portrait
        self.hero: Optional[HeroImage] = None
        self.setFocusPolicy(Qt.StrongFocus)
        self._bg = QPixmap(str(ASSETS / "login-bg.jpg"))
        if portrait:
            self._build_portrait()
        else:
            self._build()
        self._wire()

    # 배경: 가로는 창 크기에 cover 로 채움, 세로는 단색(위쪽 사진은 HeroImage 가 그린다)
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), PAGE_BG)
        if self._portrait or self._bg.isNull():
            return
        scaled = self._bg.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        p.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)

    # ---- 가로 ----
    def _build(self):
        root = QHBoxLayout(self)
        root.setAlignment(Qt.AlignCenter)
        self._root = root
        root.setContentsMargins(0, 2 * CARD_DROP, 0, 0)     # 위쪽 여백을 주면 가운데 정렬된 카드가 그 절반만큼 내려간다

        # 좌측 상단 헤드라인 (세로 화면과 같은 글꼴·색). 레이아웃 밖에 얹는다.
        self.headline = QLabel(HEADLINE_HTML, self, objectName="landscapeHeadline")
        self.headline.setTextFormat(Qt.RichText)
        self.headline.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.headline.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.headline.adjustSize()
        self.headline.move(*LANDSCAPE_HEADLINE_POS)

        card = QFrame(objectName="card")
        card.setFixedWidth(CARD_WIDTH)
        col = QVBoxLayout(card)
        col.setContentsMargins(30, 30, 30, 30)
        col.setSpacing(0)

        col.addWidget(BrandLockup(1.4), 0, Qt.AlignHCenter)
        col.addSpacing(34)

        # 역할 세그먼트
        self.roles = RoleTabs(ROLE_TABS)
        col.addWidget(self.roles)
        col.addSpacing(30)

        self.banner = QLabel(objectName="errorBanner", wordWrap=True)
        self.banner.hide()
        col.addWidget(self.banner)

        self.email = Field("ID")
        self.password = Field("PW", password=True)
        col.addWidget(self.email)
        col.addSpacing(12)
        col.addWidget(self.password)
        col.addSpacing(10)

        # 옵션 행
        opts = QHBoxLayout()
        self.remember = QCheckBox("로그인 유지", cursor=Qt.PointingHandCursor)
        forgot = QPushButton("비밀번호 찾기", objectName="linkBtn", cursor=Qt.PointingHandCursor)
        opts.addWidget(self.remember)
        opts.addStretch(1)
        opts.addWidget(forgot)
        col.addLayout(opts)
        col.addSpacing(29)  # 웹: form gap 12 + 버튼 mt 17

        self.login_btn = QPushButton("로그인", objectName="loginBtn", cursor=Qt.PointingHandCursor)
        self.login_btn.setFixedHeight(44)
        self.login_btn.setDefault(True)

        # 로그인(3) : 건너뛰기(2) 를 한 줄에 (세로 화면과 같다). skip_login=false 이면 만들지 않고 로그인 버튼이 전폭이 된다.
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.login_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        actions.addWidget(self.login_btn, 3)
        self.skip_btn = None
        if self._show_skip:
            self.skip_btn = QPushButton("건너뛰기", objectName="skipBtn", cursor=Qt.PointingHandCursor)
            self.skip_btn.setFixedHeight(44)
            self.skip_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            self.skip_btn.clicked.connect(self.skipRequested)
            actions.addWidget(self.skip_btn, 2)
        col.addLayout(actions)
        col.addSpacing(30)

        # 회원가입 안내 (간편 로그인 영역은 1차 범위 제외)
        signup = QLabel(SIGNUP_HTML, objectName="signupText")
        signup.setAlignment(Qt.AlignCenter)
        signup.setCursor(Qt.PointingHandCursor)
        col.addWidget(signup)

        root.addWidget(card)

    # ---- 세로 (480x800) ----
    def _build_portrait(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.hero = HeroImage(ASSETS / "login-hero-photo.png")
        root.addWidget(self.hero, 100)

        body = QVBoxLayout()
        body.setContentsMargins(20, 0, 20, self._bottom_margin())
        body.setSpacing(0)
        self._body = body
        root.addLayout(body)

        # 헤드라인은 사진 아래쪽(흐려지는 부분)에 얹는다. 레이아웃에서는 빠진다. 사진의 자식이라 키보드가 열려 사진이 접히면 함께 숨는다.
        self.headline = QLabel(HEADLINE_HTML, objectName="portraitHeadline", parent=self.hero)
        self.headline.setTextFormat(Qt.RichText)
        self.headline.setAlignment(Qt.AlignCenter)
        self.headline.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hero.place_center(self.headline, HEADLINE_CENTER_Y)
        body.addSpacing(14)

        self.roles = RoleTabs(ROLE_TABS_PORTRAIT, height=46, font_px=14, track="#CFE3D9")
        body.addWidget(self.roles)
        body.addSpacing(12)

        self.banner = QLabel(objectName="errorBanner", wordWrap=True)
        self.banner.hide()
        body.addWidget(self.banner)

        self.email = Field("ID", height=52, large=True)
        self.password = Field("PW", password=True, height=52, large=True)
        body.addWidget(self.email)
        body.addSpacing(8)
        body.addWidget(self.password)
        body.addSpacing(4)

        opts = QHBoxLayout()
        self.remember = QCheckBox("로그인 유지")
        self.remember.setProperty("touch", True)
        self.remember.setMinimumHeight(40)
        forgot = QPushButton("비밀번호 찾기", objectName="linkBtn")
        forgot.setMinimumHeight(40)
        opts.addWidget(self.remember)
        opts.addStretch(1)
        opts.addWidget(forgot)
        body.addLayout(opts)
        body.addSpacing(6)

        self.login_btn = QPushButton("로그인", objectName="loginBtn")
        self.login_btn.setProperty("touch", True)
        self.login_btn.setFixedHeight(52)
        self.login_btn.setDefault(True)

        # 로그인(3) : 건너뛰기(2) 를 한 줄에. 폭 정책을 Ignored 로 두어 글자 길이와 무관하게 정확히 3:2 가 된다.
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.login_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        actions.addWidget(self.login_btn, 3)
        self.skip_btn = None
        if self._show_skip:                       # skip_login=false 이면 만들지 않고, 로그인 버튼이 전폭이 된다
            self.skip_btn = QPushButton("건너뛰기", objectName="skipBtn")
            self.skip_btn.setProperty("touch", True)
            self.skip_btn.setFixedHeight(52)
            self.skip_btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            self.skip_btn.clicked.connect(self.skipRequested)
            actions.addWidget(self.skip_btn, 2)
        body.addLayout(actions)

        # 회원가입 안내. 이 줄이 차지하는 만큼 아래 여백을 줄여, 위쪽 요소의 위치는 그대로 둔다.
        body.addSpacing(SIGNUP_GAP)
        self.signup = QLabel(SIGNUP_HTML, objectName="signupText")
        self.signup.setAlignment(Qt.AlignCenter)
        self.signup.setFixedHeight(SIGNUP_H)
        body.addWidget(self.signup)

        self._tail = body.addStretch(0)

        # 로고: 위쪽 사진의 좌측 상단에 얹는다 (레이아웃에 들어가지 않으므로 다른 요소의 위치는 그대로).
        # 사진의 자식이라 사진이 접히면(키보드 표시) 로고도 함께 숨는다.
        self.logo = BrandLockup(1.1, parent=self.hero)
        self.logo.move(LOGO_MARGIN_X, LOGO_MARGIN_Y)
        self.logo.raise_()

    @staticmethod
    def _bottom_margin() -> int:
        return 14 + BODY_LIFT - SIGNUP_GAP - SIGNUP_H

    def on_keyboard(self, visible: bool, height: int = 0) -> None:
        """터치 키보드가 열리면 세로 화면은 위쪽 사진(과 그 위의 로고)을 접어 입력란과 로그인 버튼이 가려지지 않게 한다."""
        if not self._portrait:                # 가로: 카드를 가운데로 되돌려 키보드와 겹침을 줄인다
            self._root.setContentsMargins(0, 0 if visible else 2 * CARD_DROP, 0, 0)
            self.headline.setVisible(not visible)
            return
        self.hero.setVisible(not visible)
        self.signup.setVisible(not visible)
        if visible:
            self._body.setContentsMargins(20, 20, 20, 14)
        else:
            self._body.setContentsMargins(20, 0, 20, self._bottom_margin())   # 사진이 접히면 위쪽 여백을 준다
        self.layout().invalidate()

    # ---- 최근 로그인 ID ----
    def set_recent_ids(self, ids) -> None:
        """ID 입력란을 누르면 이 목록(최신순, 최대 5개)이 아래로 펼쳐지고, 고르면 ID 가 채워진다. 글자를 치면 앞부분이 같은 것만 남는다."""
        self._recent_model.setStringList(list(ids))

    def _setup_recent(self) -> None:
        self._recent_model = QStringListModel(self)
        comp = QCompleter(self._recent_model, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setMaxVisibleItems(5)
        comp.activated.connect(lambda _text: self.password.edit.setFocus())      # 고르면 바로 비밀번호 입력으로
        self.email.edit.setCompleter(comp)
        self._recent_completer = comp
        self.email.edit.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self.email.edit and ev.type() in (QEvent.FocusIn, QEvent.MouseButtonPress)                 and not self.email.edit.text() and self._recent_model.rowCount():
            QTimer.singleShot(0, self._show_recent)               # 입력란이 비어 있을 때만 전체 목록을 펼친다
        return super().eventFilter(obj, ev)

    def _show_recent(self) -> None:
        if self.email.edit.hasFocus() and not self.email.edit.text():
            self._recent_completer.setCompletionPrefix("")
            self._recent_completer.complete()

    def _wire(self):
        self._setup_recent()
        self.login_btn.clicked.connect(self._submit)
        self.email.edit.returnPressed.connect(self._submit)
        self.password.edit.returnPressed.connect(self._submit)
        self.setFocus()  # 웹처럼 처음엔 어떤 입력란에도 포커스를 주지 않는다

    def show_error(self, text: str) -> None:
        """서버 로그인 실패 문구를 배너로 보인다."""
        self.banner.setText(text)
        self.banner.setVisible(bool(text))

    def set_busy(self, busy: bool) -> None:
        """로그인 요청 중에는 버튼을 막는다 (두 번 눌러도 한 번만 보낸다)."""
        self.login_btn.setEnabled(not busy)
        self.login_btn.setText("로그인 중…" if busy else "로그인")

    def _submit(self):
        self.banner.hide()
        email_ok = bool(EMAIL_RE.match(self.email.text().strip()))
        pw_ok = bool(self.password.text())
        self.email.set_error("" if email_ok else "올바른 이메일을 입력해주세요.")
        self.password.set_error("" if pw_ok else "비밀번호를 입력해주세요.")
        if email_ok and pw_ok:
            role = self.roles.current_key()
            self.loginRequested.emit(role, self.email.text().strip(), self.password.text(),
                                     self.remember.isChecked())
