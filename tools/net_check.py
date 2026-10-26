"""Pi 에서 실제 nmcli / bluetoothctl 로 Wi-Fi·블루투스 백엔드를 점검한다 (가짜 출력이 아닌 실제 명령).

    python3 tools/net_check.py                      # 읽기만 (상태/목록). 아무것도 바꾸지 않는다
    python3 tools/net_check.py --bt-scan            # 블루투스 8초 검색 포함
    python3 tools/net_check.py --save pi_net.txt    # 실행한 명령과 원본 출력을 파일로 저장 (개발자에게 보내기)
    python3 tools/net_check.py --connect SSID --password PW      # (바꿈) 실제로 연결해 본다
    python3 tools/net_check.py --disconnect-wifi / --forget SSID # (바꿈)
    python3 tools/net_check.py --bt-register MAC / --bt-connect MAC / --bt-remove MAC   # (바꿈)

각 단계는 [원본 출력] 과 [앱이 해석한 결과] 를 나란히 보여 준다. 해석이 이상하면(줄이 버려짐 등) 표시한다.
화면(설정 화면)이 쓰는 것과 같은 net/ 백엔드를 그대로 쓰므로, 여기서 정상이면 화면도 정상이다.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.net.bluetooth import BluetoothctlBackend, parse_devices, parse_info          # noqa: E402
from app.net.errors import NetError                                                    # noqa: E402
from app.net.runner import CmdResult, run                                              # noqa: E402
from app.net.wifi import NmcliWifi, parse_saved, parse_wifi_list, split_terse          # noqa: E402

LOG = []          # (명령, rc, 출력) — --save 로 파일에 쓴다
PROBLEMS = []


def logged(args, timeout=20, input_text=None) -> CmdResult:
    res = run(args, timeout, input_text)
    LOG.append((" ".join(args), res.rc, res.text))
    return res


def say(msg=""):
    print(msg)


def head(title):
    say()
    say("=" * 70)
    say(title)
    say("=" * 70)


def show_cmd(args, timeout=20) -> CmdResult:
    res = logged(args, timeout)
    say(f"$ {' '.join(args)}   → rc={res.rc}")
    for ln in (res.text or "(출력 없음)").splitlines()[:40]:
        say("   | " + ln)
    if len(res.text.splitlines()) > 40:
        say(f"   | … ({len(res.text.splitlines()) - 40}줄 더)")
    return res


def problem(msg):
    PROBLEMS.append(msg)
    say(f"   !! {msg}")


def check_wifi(args):
    head("Wi-Fi (nmcli)")
    if run(["nmcli", "--version"], 5).rc == 127:
        problem("nmcli 가 없습니다 → sudo apt install network-manager")
        return
    be = NmcliWifi(logged)
    r = show_cmd(["nmcli", "radio", "wifi"])
    r2 = show_cmd(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"])
    dev = be.device()
    say(f"[해석] Wi-Fi 장치: {dev}")
    if not dev:
        problem("Wi-Fi 장치를 찾지 못했습니다 (DEVICE:TYPE 출력에 wifi 가 없음)")
    c = show_cmd(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    saved = parse_saved(c.out)
    say(f"[해석] 저장된 Wi-Fi: {sorted(saved) or '없음'}")
    show_cmd(["nmcli", "-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS", "device", "show", dev or "wlan0"])
    say(f"[해석] 현재 연결: {be.current()}")
    show_cmd(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"], 30)
    raw = logged(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "no"], 30)
    nets = parse_wifi_list(raw.out, saved)
    say(f"[해석] 목록 {len(nets)}개:")
    for n in nets:
        say(f"   {'●' if n.in_use else ' '} {n.ssid:<28} {n.signal:>3}%  {n.security or '열림':<12} {'저장됨' if n.saved else ''}")
    lines = [ln for ln in raw.out.splitlines() if ln.strip()]
    bad = [ln for ln in lines if len(split_terse(ln)) != 4]
    if bad:
        problem(f"필드가 4개가 아닌 줄 {len(bad)}개 — 형식이 가정과 다릅니다: {bad[:2]}")
    hidden = [ln for ln in lines if len(split_terse(ln)) == 4 and not split_terse(ln)[1].strip()]
    if hidden:
        say(f"   (이름이 없는 숨은 네트워크 {len(hidden)}개는 목록에서 뺐습니다 → '직접 입력'으로 연결)")
    if lines and not nets:
        problem("검색 줄이 있는데 해석된 목록이 비었습니다")
    if not lines:
        say("   (검색된 네트워크가 없습니다. 안테나/지역 확인)")
    try:
        say(f"[앱 호출] scan() → {len(be.scan(rescan=False))}개, radio() → {be.radio()}")
    except NetError as e:
        problem(f"scan/radio 실패: {e}")


def diag_bt(quiet: bool = False):
    """블루투스가 안 켜질 때의 원인 후보를 한 번에 보여 준다."""
    if quiet:
        return
    say()
    say("[블루투스 진단]")
    show_cmd(["rfkill", "list", "bluetooth"])
    show_cmd(["systemctl", "is-active", "bluetooth"])
    show_cmd(["systemctl", "status", "bluetooth", "--no-pager", "-n", "8"])
    show_cmd(["hciconfig", "-a"])
    show_cmd(["bash", "-c", "ls /sys/class/bluetooth 2>&1; grep -n -i -E 'bt|bluetooth|uart' /boot/firmware/config.txt 2>&1"])
    show_cmd(["bash", "-c", "dmesg 2>/dev/null | grep -i -E 'bluetooth|hci|brcm' | tail -15"])
    why = BluetoothctlBackend(logged).diagnose()
    say(f"[앱의 진단] {why or '명확한 원인을 찾지 못했습니다. 위 출력을 보내 주세요.'}")


def check_bt(args):
    head("블루투스 (bluetoothctl)")
    if run(["bluetoothctl", "--version"], 5).rc == 127:
        problem("bluetoothctl 이 없습니다 → sudo apt install bluez")
        return
    be = BluetoothctlBackend(logged)
    show_cmd(["bluetoothctl", "show"])
    try:
        say(f"[해석] powered() → {be.powered()}")
    except NetError as e:
        problem(f"블루투스 상태: {e}")
        diag_bt()
        return
    diag_bt(quiet=True)
    if args.bt_scan:
        say(f"\n주변 장치를 8초간 검색합니다…")
        show_cmd(["bluetoothctl", "--timeout", "8", "scan", "on"], 16)
    d = show_cmd(["bluetoothctl", "devices"])
    pairs = parse_devices(d.out)
    say(f"[해석] 장치 {len(pairs)}개 (원본 'Device' 줄 {sum(1 for ln in d.out.splitlines() if ln.strip().startswith('Device'))}개)")
    if sum(1 for ln in d.out.splitlines() if ln.strip().startswith("Device")) != len(pairs):
        problem("'Device' 로 시작하는 줄 중 해석되지 않은 것이 있습니다")
    for mac, name in pairs[:6]:
        info = show_cmd(["bluetoothctl", "info", mac])
        say(f"[해석] {mac}: {parse_info(info.out)}")
    try:
        devs = be.devices()
        say("[앱 호출] devices():")
        for x in devs:
            flags = ",".join(f for f, on in (("등록", x.paired), ("신뢰", x.trusted), ("연결", x.connected)) if on)
            say(f"   {x.mac}  {x.name:<26} {flags or '-':<14} rssi={x.rssi}")
    except NetError as e:
        problem(f"devices() 실패: {e}")


def act(title, fn):
    head(f"[실행] {title}")
    try:
        say("   " + str(fn()))
    except NetError as e:
        say(f"   실패: {e}")


def do_actions(args):
    wifi, bt = NmcliWifi(logged), BluetoothctlBackend(logged)
    if args.connect:
        act(f"Wi-Fi 연결 {args.connect}", lambda: wifi.connect(args.connect, args.password or ""))
        say(f"   현재 연결: {wifi.current()}")
    if args.disconnect_wifi:
        act("Wi-Fi 연결 해제", wifi.disconnect)
    if args.forget:
        act(f"Wi-Fi 저장 삭제 {args.forget}", lambda: wifi.forget(args.forget))
    if args.bt_register:
        act(f"블루투스 등록 {args.bt_register} (페어링 최대 30초)", lambda: bt.register(args.bt_register))
    if args.bt_connect:
        act(f"블루투스 연결 {args.bt_connect}", lambda: bt.connect(args.bt_connect))
    if args.bt_disconnect:
        act(f"블루투스 연결 해제 {args.bt_disconnect}", lambda: bt.disconnect(args.bt_disconnect))
    if args.bt_remove:
        act(f"블루투스 등록 삭제 {args.bt_remove}", lambda: bt.remove(args.bt_remove))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wifi-only", action="store_true")
    ap.add_argument("--bt-only", action="store_true")
    ap.add_argument("--bt-scan", action="store_true", help="블루투스 8초 검색 포함")
    ap.add_argument("--save", metavar="FILE", help="실행한 명령과 원본 출력을 이 파일에 저장")
    ap.add_argument("--connect", metavar="SSID")
    ap.add_argument("--password")
    ap.add_argument("--disconnect-wifi", action="store_true")
    ap.add_argument("--forget", metavar="SSID")
    ap.add_argument("--bt-register", metavar="MAC")
    ap.add_argument("--bt-connect", metavar="MAC")
    ap.add_argument("--bt-disconnect", metavar="MAC")
    ap.add_argument("--bt-remove", metavar="MAC")
    args = ap.parse_args()

    if not args.bt_only:
        check_wifi(args)
    if not args.wifi_only:
        check_bt(args)
    do_actions(args)

    head("요약")
    if PROBLEMS:
        for p in PROBLEMS:
            say(f" - {p}")
        say("\n위 항목과 --save 파일을 개발자에게 보내 주세요.")
    else:
        say("해석 문제 없음. 실제 명령 출력이 앱의 해석 방식과 맞습니다.")
    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            for cmd, rc, out in LOG:
                f.write(f"$ {cmd}\n# rc={rc}\n{out}\n\n")
        say(f"\n저장했습니다: {args.save} ({len(LOG)}개 명령)")
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    sys.exit(main())
