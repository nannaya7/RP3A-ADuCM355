"""Wi-Fi 관리. 실제 장치는 NetworkManager 의 nmcli (Raspberry Pi OS Bookworm/Trixie 기본), PC 개발용은 MockWifi.

연결에 성공하면 NetworkManager 가 접속 정보를 저장하므로(= 등록) 다음부터는 비밀번호 없이 자동으로 붙는다.
"""
import shutil
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .errors import NetError
from .runner import CmdResult, run


@dataclass(frozen=True)
class WifiNetwork:
    ssid: str
    signal: int = 0                 # 0~100 (%)
    security: str = ""              # "WPA2" 등. 열린 네트워크는 빈 문자열
    in_use: bool = False            # 지금 연결되어 있음
    saved: bool = False             # 등록(저장)되어 있음

    @property
    def secured(self) -> bool:
        return bool(self.security)


def split_terse(line: str) -> List[str]:
    """nmcli -t 출력 한 줄을 ':' 로 나눈다. 값 안의 ':' 는 '\\:' , '\\' 는 '\\\\' 로 나온다."""
    out, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def parse_wifi_list(text: str, saved=frozenset()) -> List[WifiNetwork]:
    """`nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY dev wifi list` 출력 → 같은 SSID 는 신호가 가장 센 것 하나만."""
    best = {}
    for line in text.splitlines():
        f = split_terse(line)
        if len(f) < 4:
            continue
        in_use, ssid, sig, sec = f[0].strip() == "*", f[1], f[2].strip(), f[3].strip()
        if not ssid.strip():
            continue                                  # 숨은 네트워크(이름 없음)는 목록에서 뺀다 → '직접 입력'으로 추가
        signal = int(sig) if sig.isdigit() else 0
        net = WifiNetwork(ssid, signal, "" if sec in ("", "--") else sec, in_use, ssid in saved)
        old = best.get(ssid)
        if old is None or net.in_use or (not old.in_use and net.signal > old.signal):
            best[ssid] = net
    return sorted(best.values(), key=lambda n: (not n.in_use, not n.saved, -n.signal, n.ssid.lower()))


def parse_saved(text: str) -> frozenset:
    """`nmcli -t -f NAME,TYPE connection show` → 무선 연결 이름 집합 (이름 = SSID 로 만들어진다)."""
    names = set()
    for line in text.splitlines():
        f = split_terse(line)
        if len(f) >= 2 and f[1].strip() in ("802-11-wireless", "wifi"):
            names.add(f[0])
    return frozenset(names)


def friendly_error(res: CmdResult, default: str) -> str:
    t = res.text.lower()
    if res.rc == 127:
        return "nmcli 가 없습니다. NetworkManager 가 설치되어 있는지 확인하세요."
    if res.rc == 124:
        return "시간이 초과되었습니다. 신호가 약하거나 응답이 없습니다."
    if "secrets were required" in t or "password" in t or "802-1x" in t or "4-way" in t:
        return "비밀번호가 맞지 않습니다."
    if "no network with ssid" in t or "not found" in t:
        return "네트워크를 찾을 수 없습니다. 다시 검색해 보세요."
    if "not authorized" in t or "permission" in t:
        return "권한이 없습니다. 데스크톱에 로그인한 사용자로 실행해야 합니다."
    if "rfkill" in t or "wi-fi is disabled" in t or "wifi is disabled" in t:
        return "Wi-Fi 가 꺼져 있습니다. 먼저 켜 주세요."
    detail = res.text.splitlines()[-1] if res.text else ""
    return f"{default}" + (f" ({detail})" if detail else "")


class NmcliWifi:
    """nmcli 로 Wi-Fi 를 관리한다. 모든 메서드는 블로킹이므로 화면에서는 백그라운드(net/tasks.py)로 부른다."""

    def __init__(self, runner: Callable = run):
        self._run = runner

    def available(self) -> bool:
        return shutil.which("nmcli") is not None if self._run is run else True

    # ---- 상태 ----
    def radio(self) -> bool:
        r = self._run(["nmcli", "radio", "wifi"], 8)
        if not r.ok:
            raise NetError(friendly_error(r, "Wi-Fi 상태를 읽지 못했습니다."))
        return r.out.strip().lower().startswith("enabled")

    def set_radio(self, on: bool) -> None:
        r = self._run(["nmcli", "radio", "wifi", "on" if on else "off"], 10)
        if not r.ok:
            raise NetError(friendly_error(r, "Wi-Fi 를 바꾸지 못했습니다."))

    def device(self) -> Optional[str]:
        r = self._run(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"], 8)
        for line in r.out.splitlines():
            f = split_terse(line)
            if len(f) >= 2 and f[1] == "wifi":
                return f[0]
        return None

    def saved_names(self) -> frozenset:
        r = self._run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"], 10)
        return parse_saved(r.out) if r.ok else frozenset()

    def current(self) -> Tuple[Optional[str], str]:
        """(연결된 SSID 또는 None, IP 주소 또는 '')"""
        dev = self.device()
        if not dev:
            return None, ""
        r = self._run(["nmcli", "-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS", "device", "show", dev], 8)
        if not r.ok:
            return None, ""
        ssid, ip, up = None, "", False
        for line in r.out.splitlines():
            key, _, val = line.partition(":")
            if key == "GENERAL.STATE":
                up = val.strip().startswith("100")
            elif key == "GENERAL.CONNECTION" and val.strip() not in ("", "--"):
                ssid = val.strip()
            elif key.startswith("IP4.ADDRESS") and not ip:
                ip = val.strip().split("/")[0]
        return (ssid if up else None), ip

    # ---- 검색 / 연결 ----
    def scan(self, rescan: bool = True) -> List[WifiNetwork]:
        r = self._run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                       "--rescan", "yes" if rescan else "no"], 30)
        if not r.ok:
            raise NetError(friendly_error(r, "Wi-Fi 를 검색하지 못했습니다."))
        return parse_wifi_list(r.out, self.saved_names())

    def connect(self, ssid: str, password: str = "", hidden: bool = False) -> str:
        """등록된 네트워크면 비밀번호 없이 연결, 새 네트워크면 비밀번호로 연결하면서 저장한다."""
        saved = ssid in self.saved_names()
        if saved and password:
            self.forget(ssid)                         # 비밀번호를 새로 입력했다면 옛 정보를 지우고 다시 만든다
            saved = False
        if saved:
            r = self._run(["nmcli", "-w", "30", "connection", "up", "id", ssid], 45)
        else:
            cmd = ["nmcli", "-w", "30", "device", "wifi", "connect", ssid]
            if password:
                cmd += ["password", password]
            if hidden:
                cmd += ["hidden", "yes"]
            r = self._run(cmd, 45)
        if not r.ok:
            if not saved:
                self._run(["nmcli", "connection", "delete", "id", ssid], 10)   # 실패한 반쪽짜리 등록을 남기지 않는다
            raise NetError(friendly_error(r, "연결하지 못했습니다."))
        return f"'{ssid}' 에 연결되었습니다."

    def disconnect(self) -> str:
        dev = self.device()
        if not dev:
            raise NetError("Wi-Fi 장치를 찾을 수 없습니다.")
        r = self._run(["nmcli", "device", "disconnect", dev], 15)
        if not r.ok:
            raise NetError(friendly_error(r, "연결을 끊지 못했습니다."))
        return "연결을 해제했습니다."

    def forget(self, ssid: str) -> str:
        r = self._run(["nmcli", "connection", "delete", "id", ssid], 15)
        if not r.ok:
            raise NetError(friendly_error(r, "저장된 정보를 지우지 못했습니다."))
        return f"'{ssid}' 저장 정보를 삭제했습니다."


class MockWifi:
    """PC 에서 화면을 시험하기 위한 가상 Wi-Fi. 비밀번호가 '12345678' 이면 성공한다."""
    PASSWORD = "12345678"

    def __init__(self, delay: float = 0.4):
        self._delay = delay
        self._on = True
        self._connected: Optional[str] = None
        self._saved = {"Nformare-Lab"}
        self._nets = [("Nformare-Lab", 82, "WPA2"), ("Office_5G", 64, "WPA2 WPA3"), ("Cafe Free", 48, ""),
                      ("AndroidAP_3F2A", 35, "WPA2"), ("Neighbor:Home", 22, "WPA2")]

    def _wait(self):
        if self._delay:
            time.sleep(self._delay)

    def available(self) -> bool:
        return True

    def radio(self) -> bool:
        return self._on

    def set_radio(self, on: bool) -> None:
        self._wait()
        self._on = on
        if not on:
            self._connected = None

    def current(self) -> Tuple[Optional[str], str]:
        return (self._connected, "192.168.0.23") if self._connected else (None, "")

    def scan(self, rescan: bool = True) -> List[WifiNetwork]:
        if not self._on:
            raise NetError("Wi-Fi 가 꺼져 있습니다. 먼저 켜 주세요.")
        if rescan:
            self._wait()
        return sorted((WifiNetwork(s, sig, sec, s == self._connected, s in self._saved) for s, sig, sec in self._nets),
                      key=lambda n: (not n.in_use, not n.saved, -n.signal))

    def connect(self, ssid: str, password: str = "", hidden: bool = False) -> str:
        self._wait()
        known = {s: sec for s, _, sec in self._nets}
        if not self._on:
            raise NetError("Wi-Fi 가 꺼져 있습니다. 먼저 켜 주세요.")
        if ssid not in known and not hidden:
            raise NetError("네트워크를 찾을 수 없습니다. 다시 검색해 보세요.")
        if ssid in self._saved and not password:
            pass
        elif known.get(ssid, "WPA2") and password != self.PASSWORD:
            raise NetError("비밀번호가 맞지 않습니다.")
        self._saved.add(ssid)
        if ssid not in known:
            self._nets.append((ssid, 30, "WPA2"))
        self._connected = ssid
        return f"'{ssid}' 에 연결되었습니다."

    def disconnect(self) -> str:
        self._wait()
        self._connected = None
        return "연결을 해제했습니다."

    def forget(self, ssid: str) -> str:
        self._wait()
        self._saved.discard(ssid)
        if self._connected == ssid:
            self._connected = None
        return f"'{ssid}' 저장 정보를 삭제했습니다."
