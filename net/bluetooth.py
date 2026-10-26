"""블루투스 관리. 실제 장치는 BlueZ 의 bluetoothctl, PC 개발용은 MockBluetooth.

등록 = 페어링(pair) + 신뢰(trust) + 연결(connect). 신뢰한 장치는 다음부터 자동으로 연결된다.
PIN/확인 숫자가 필요한 장치(키보드 등)는 지원하지 않는다 (NoInputNoOutput 에이전트로 'Just Works' 페어링만).
"""
import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .errors import NetError
from .runner import CmdResult, clean, run

MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", re.I)


@dataclass(frozen=True)
class BtDevice:
    mac: str
    name: str
    paired: bool = False
    connected: bool = False
    trusted: bool = False
    rssi: Optional[int] = None

    @property
    def named(self) -> bool:
        return bool(self.name) and self.name.replace("-", ":").upper() != self.mac.upper()


def parse_devices(text: str) -> List[Tuple[str, str]]:
    """`bluetoothctl devices` → [(mac, name)]"""
    out = []
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) >= 2 and parts[0] == "Device" and MAC_RE.match(parts[1]):
            out.append((parts[1].upper(), parts[2].strip() if len(parts) > 2 else ""))
    return out


def parse_info(text: str) -> dict:
    """`bluetoothctl info MAC` → {'Name':..., 'Paired': 'yes', ...}"""
    d = {}
    for line in text.splitlines():
        k, sep, v = line.strip().partition(":")
        if sep and k in ("Name", "Alias", "Paired", "Trusted", "Connected", "RSSI", "Bonded"):
            d[k] = v.strip()
    return d


def _yes(v: Optional[str]) -> bool:
    return (v or "").strip().lower() == "yes"


def make_device(mac: str, name: str, info: dict) -> BtDevice:
    rssi = None
    m = re.search(r"\((-?\d+)\)", info.get("RSSI", "")) or re.fullmatch(r"\s*(-?\d+)\s*", info.get("RSSI", ""))
    if m:                                     # "0xffffffc4 (-60)" 또는 "-60"
        rssi = int(m.group(1))
    return BtDevice(mac, info.get("Alias") or info.get("Name") or name, _yes(info.get("Paired")),
                    _yes(info.get("Connected")), _yes(info.get("Trusted")), rssi)


def friendly_error(text: str, default: str) -> str:
    t = text.lower()
    if "not available" in t or "no default controller" in t:
        return "블루투스 장치를 찾을 수 없습니다."
    if "rfkill" in t or "blocked" in t:
        return "블루투스가 차단되어 있습니다. 켜기를 눌러 주세요."
    if "authenticationfailed" in t or "authentication failed" in t:
        return "인증에 실패했습니다. 장치의 페어링 모드를 확인하세요."
    if "authenticationcanceled" in t or "authenticationrejected" in t or "authenticationtimeout" in t:
        return "장치가 페어링을 거절했거나 응답하지 않았습니다. PIN 이 필요한 장치는 지원하지 않습니다."
    if "page timeout" in t or "host is down" in t or "connectionattemptfailed" in t:
        return "장치에 닿지 않습니다. 가까이 두고 켜져 있는지 확인하세요."
    if "inprogress" in t:
        return "다른 작업이 진행 중입니다. 잠시 뒤 다시 시도하세요."
    if "not available" in t or "device not found" in t:
        return "장치를 찾을 수 없습니다. 다시 검색해 보세요."
    detail = text.strip().splitlines()[-1] if text.strip() else ""
    return default + (f" ({detail})" if detail else "")


def pair_session(mac: str, timeout: float = 30.0) -> Tuple[bool, str]:
    """bluetoothctl 을 대화 모드로 열어 에이전트를 등록한 뒤 페어링한다. (성공 여부, 출력)

    한 줄짜리 `bluetoothctl pair` 는 에이전트가 없어 실패하는 경우가 있어 이렇게 한다."""
    try:
        p = subprocess.Popen(["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
    except FileNotFoundError:
        return False, "bluetoothctl 이 없습니다."
    lines: "queue.Queue[str]" = queue.Queue()

    def reader():
        for ln in p.stdout:
            lines.put(clean(ln))
        lines.put("")

    threading.Thread(target=reader, daemon=True).start()
    log, ok = [], None
    try:
        for cmd in ("agent NoInputNoOutput", "default-agent", f"pair {mac}"):
            p.stdin.write(cmd + "\n")
            p.stdin.flush()
            time.sleep(0.2)
        deadline = time.monotonic() + timeout
        while ok is None and time.monotonic() < deadline:
            try:
                ln = lines.get(timeout=0.5)
            except queue.Empty:
                continue
            log.append(ln)
            low = ln.lower()
            if "pairing successful" in low or "alreadyexists" in low or "already exists" in low:
                ok = True
            elif "failed to pair" in low:
                ok = False
        if ok is None:
            ok = False
            log.append("페어링 응답이 없습니다.")
    finally:
        try:
            p.stdin.write("quit\n")
            p.stdin.flush()
        except (OSError, ValueError):
            pass
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
    return ok, "\n".join(log)


class BluetoothctlBackend:
    power_detail = ""

    def __init__(self, runner: Callable = run, pairer: Callable = pair_session):
        self._run = runner
        self._pair = pairer

    def available(self) -> bool:
        return shutil.which("bluetoothctl") is not None if self._run is run else True

    # ---- 상태 ----
    def diagnose(self) -> str:
        """블루투스가 켜지지 않는 이유를 찾아 한국어로 알려 준다 (원인 + 해결 명령)."""
        rf = self._run(["rfkill", "list", "bluetooth"], 5)
        t = rf.out.lower()
        if "hard blocked: yes" in t:
            return "하드웨어 스위치로 차단되어 있습니다."
        if "soft blocked: yes" in t:
            return "소프트 차단 상태입니다. 터미널에서: sudo rfkill unblock bluetooth"
        if rf.rc == 0 and "bluetooth" not in t:
            return "블루투스 장치가 시스템에 없습니다. /boot/firmware/config.txt 에 dtoverlay=disable-bt 가 있으면 지우고 재부팅하세요."
        sv = self._run(["systemctl", "is-active", "bluetooth"], 5)
        if sv.out.strip() in ("inactive", "failed"):
            return "bluetooth 서비스가 꺼져 있습니다. 터미널에서: sudo systemctl enable --now bluetooth"
        return ""

    def powered(self) -> bool:
        r = self._run(["bluetoothctl", "show"], 8)
        if r.rc == 127:
            raise NetError("bluetoothctl 이 없습니다. bluez 가 설치되어 있는지 확인하세요.")
        if not r.ok or "Controller" not in r.out:
            why = self.diagnose()
            raise NetError(why or friendly_error(r.text, "블루투스 장치를 찾을 수 없습니다."))
        for _ in range(4):
            ps = re.search(r"PowerState:\s*([\w-]+)", r.out)
            if not ps or ps.group(1) not in ("off-enabling", "on-disabling"):
                break
            time.sleep(1.0)                                           # 켜지는(꺼지는) 중이면 끝날 때까지 잠시 기다린다
            r = self._run(["bluetoothctl", "show"], 8)
        m = re.search(r"Powered:\s*(\w+)", r.out)
        self.power_detail = ", ".join(x.strip() for x in r.out.splitlines()
                                      if x.strip().startswith(("Powered:", "PowerState:")))   # 화면에 보여 원인 파악에 쓴다
        if ps and ps.group(1) == "on":
            return True
        return bool(m) and m.group(1).lower() == "yes"

    def set_power(self, on: bool) -> None:
        """전원을 바꾼다. 'org.bluez.Error.Busy' (직전 전원 요청/초기화가 아직 진행 중)는 잠시 기다렸다 다시 시도한다."""
        if on:
            self._run(["rfkill", "unblock", "bluetooth"], 5)          # 차단되어 있으면 풀고 켠다 (없으면 무시)
        want = "on" if on else "off"
        last = ""
        for attempt in range(12):
            r = self._run(["bluetoothctl", "power", want], 10)
            text = r.text
            if r.ok and "failed" not in text.lower():
                if self._powered_state(on):
                    return
                last = ""                                             # 명령은 성공했는데 상태가 안 바뀜
            else:
                last = (text.strip().splitlines() or [""])[-1]
                if "busy" not in text.lower() and "inprogress" not in text.lower():
                    break                                             # 기다려서 나아질 오류가 아니다
            if self._powered_state(on):                               # 요청이 겹쳐 Busy 가 났어도 이미 바뀌어 있을 수 있다
                return
            time.sleep(1.0)
        why = self.diagnose() if on else ""
        if why:
            raise NetError(why)
        if "busy" in last.lower():
            raise NetError("블루투스 장치가 아직 준비 중입니다(Busy). 몇 초 뒤 다시 눌러 보세요. 계속되면 재부팅하거나 "
                           "sudo systemctl restart bluetooth 를 실행하세요.")
        raise NetError("블루투스를 " + ("켜지" if on else "끄지") + " 못했습니다." + (f" ({last})" if last else ""))

    def _powered_state(self, on: bool) -> bool:
        r = self._run(["bluetoothctl", "show"], 8)
        m = re.search(r"Powered:\s*(\w+)", r.out)
        return bool(m) and (m.group(1).lower() == "yes") == on

    # ---- 검색 ----
    def devices(self) -> List[BtDevice]:
        r = self._run(["bluetoothctl", "devices"], 10)
        if not r.ok:
            raise NetError(friendly_error(r.text, "장치 목록을 읽지 못했습니다."))
        out = []
        for mac, name in parse_devices(r.out):
            info = parse_info(self._run(["bluetoothctl", "info", mac], 8).out)
            out.append(make_device(mac, name, info))
        # 이름이 있는 것 먼저, 연결됨 > 등록됨 > 신호 센 순
        return sorted(out, key=lambda d: (not d.connected, not d.paired, not d.named, -(d.rssi if d.rssi is not None else -200),
                                          d.name.lower()))

    def scan(self, seconds: int = 8) -> List[BtDevice]:
        r = self._run(["bluetoothctl", "--timeout", str(int(seconds)), "scan", "on"], seconds + 8)
        if r.rc not in (0, 124) and "Discovery started" not in r.out:
            raise NetError(friendly_error(r.text, "장치를 검색하지 못했습니다."))
        return self.devices()

    # ---- 등록 / 연결 ----
    def _check(self, r: CmdResult, success: str, default: str) -> None:
        if success.lower() not in r.out.lower():
            raise NetError(friendly_error(r.text, default))

    def register(self, mac: str) -> str:
        """페어링 + 신뢰 + 연결. 연결만 실패하면 등록은 된 것으로 알린다."""
        ok, log = self._pair(mac)
        if not ok:
            raise NetError(friendly_error(log, "등록(페어링)에 실패했습니다."))
        self._run(["bluetoothctl", "trust", mac], 10)
        r = self._run(["bluetoothctl", "connect", mac], 25)
        if "connection successful" in r.out.lower():
            return "등록하고 연결했습니다."
        return "등록했습니다. 연결은 되지 않았습니다. [연결]을 눌러 보세요."

    def connect(self, mac: str) -> str:
        r = self._run(["bluetoothctl", "connect", mac], 25)
        self._check(r, "connection successful", "연결하지 못했습니다.")
        return "연결했습니다."

    def disconnect(self, mac: str) -> str:
        r = self._run(["bluetoothctl", "disconnect", mac], 15)
        self._check(r, "successful", "연결을 끊지 못했습니다.")
        return "연결을 해제했습니다."

    def remove(self, mac: str) -> str:
        r = self._run(["bluetoothctl", "remove", mac], 15)
        self._check(r, "removed", "삭제하지 못했습니다.")
        return "등록을 삭제했습니다."


class MockBluetooth:
    """PC 에서 화면을 시험하기 위한 가상 블루투스."""

    def __init__(self, delay: float = 0.4):
        self._delay = delay
        self._on = True
        self._seen = False
        self._dev = {
            "AA:BB:CC:00:00:01": BtDevice("AA:BB:CC:00:00:01", "Nformare Printer", True, False, True, -55),
            "AA:BB:CC:00:00:02": BtDevice("AA:BB:CC:00:00:02", "Barcode Scanner", False, False, False, -62),
            "AA:BB:CC:00:00:03": BtDevice("AA:BB:CC:00:00:03", "JBL Speaker", False, False, False, -48),
            "AA:BB:CC:00:00:04": BtDevice("AA:BB:CC:00:00:04", "AA-BB-CC-00-00-04", False, False, False, -80),
        }
        self._order_unpaired = ["AA:BB:CC:00:00:02", "AA:BB:CC:00:00:03", "AA:BB:CC:00:00:04"]

    def _wait(self):
        if self._delay:
            time.sleep(self._delay)

    def available(self) -> bool:
        return True

    def powered(self) -> bool:
        return self._on

    def set_power(self, on: bool) -> None:
        self._wait()
        self._on = on

    def _need_on(self):
        if not self._on:
            raise NetError("블루투스가 꺼져 있습니다. 먼저 켜 주세요.")

    def devices(self) -> List[BtDevice]:
        self._need_on()
        vis = [d for m, d in self._dev.items() if d.paired or self._seen]
        return sorted(vis, key=lambda d: (not d.connected, not d.paired, not d.named, -(d.rssi or -200)))

    def scan(self, seconds: int = 8) -> List[BtDevice]:
        self._need_on()
        self._wait()
        self._seen = True
        return self.devices()

    def _set(self, mac: str, **kw) -> None:
        d = self._dev[mac]
        self._dev[mac] = BtDevice(mac, kw.get("name", d.name), kw.get("paired", d.paired),
                                  kw.get("connected", d.connected), kw.get("trusted", d.trusted), d.rssi)

    def register(self, mac: str) -> str:
        self._need_on()
        self._wait()
        if mac.endswith("04"):
            raise NetError("장치가 페어링을 거절했거나 응답하지 않았습니다. PIN 이 필요한 장치는 지원하지 않습니다.")
        self._set(mac, paired=True, trusted=True, connected=True)
        return "등록하고 연결했습니다."

    def connect(self, mac: str) -> str:
        self._need_on()
        self._wait()
        self._set(mac, connected=True)
        return "연결했습니다."

    def disconnect(self, mac: str) -> str:
        self._wait()
        self._set(mac, connected=False)
        return "연결을 해제했습니다."

    def remove(self, mac: str) -> str:
        self._wait()
        self._set(mac, paired=False, trusted=False, connected=False)
        return "등록을 삭제했습니다."
