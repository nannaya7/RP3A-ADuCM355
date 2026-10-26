"""net/ — nmcli / bluetoothctl 출력 해석, 백엔드 명령 구성, 가상 백엔드."""
import pytest

from app.net.bluetooth import (BluetoothctlBackend, MockBluetooth, friendly_error as bt_err, make_device, parse_devices,
                           parse_info)
from app.net.errors import NetError
from app.net.runner import CmdResult, clean
from app.net.wifi import MockWifi, NmcliWifi, parse_saved, parse_wifi_list, split_terse


def test_split_terse_handles_escaped_colon():
    assert split_terse(r"*:My\:Net:78:WPA2") == ["*", "My:Net", "78", "WPA2"]
    assert split_terse(r"a\\b:c") == ["a\\b", "c"]


def test_parse_wifi_list_dedup_sort_and_hidden():
    text = "\n".join([" :Office:40:WPA2", " :Office:70:WPA2", "*:Home:55:WPA2 WPA3", " ::30:WPA2", " :Cafe:80:--",
                      " :Saved:20:WPA2"])
    nets = parse_wifi_list(text, saved=frozenset({"Saved", "Home"}))
    assert [n.ssid for n in nets] == ["Home", "Saved", "Cafe", "Office"]          # 연결됨 > 저장됨 > 신호
    assert nets[0].in_use and nets[0].saved and nets[0].secured
    assert not [n for n in nets if n.ssid == "Cafe"][0].secured                   # '--' = 열린 네트워크
    assert [n for n in nets if n.ssid == "Office"][0].signal == 70                # 같은 이름은 센 신호 하나


def test_parse_saved_only_wifi():
    assert parse_saved("Home:802-11-wireless\nWired connection 1:802-3-ethernet\nlo:loopback") == frozenset({"Home"})


class FakeRunner:
    """명령 앞부분이 일치하는 응답을 돌려주고, 부른 명령을 기록한다."""

    def __init__(self, table):
        self.table, self.calls = table, []

    def __call__(self, args, timeout=20, input_text=None):
        self.calls.append(list(args))
        for prefix, res in self.table:
            if list(args)[:len(prefix)] == prefix:
                return res(args) if callable(res) else res
        return CmdResult(1, "", "unknown")


NM_LIST = CmdResult(0, " :Office:60:WPA2\n*:Home:75:WPA2\n")
NM_CONN = CmdResult(0, "Home:802-11-wireless\n")


def test_nmcli_scan_marks_saved():
    r = FakeRunner([(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY"], NM_LIST),
                    (["nmcli", "-t", "-f", "NAME,TYPE"], NM_CONN)])
    nets = NmcliWifi(r).scan(rescan=False)
    assert nets[0].ssid == "Home" and nets[0].saved and nets[0].in_use
    assert ["--rescan", "no"] == r.calls[0][-2:]


def test_nmcli_connect_new_uses_password_and_saved_skips_it():
    r = FakeRunner([(["nmcli", "-t", "-f", "NAME,TYPE"], NM_CONN), (["nmcli", "-w"], CmdResult(0, "ok"))])
    w = NmcliWifi(r)
    w.connect("Office", "pass1234")
    assert r.calls[-1] == ["nmcli", "-w", "30", "device", "wifi", "connect", "Office", "password", "pass1234"]
    w.connect("Home")
    assert r.calls[-1] == ["nmcli", "-w", "30", "connection", "up", "id", "Home"]
    w.connect("Hid", "pass1234", hidden=True)
    assert r.calls[-1][-2:] == ["hidden", "yes"]


def test_nmcli_connect_saved_with_new_password_recreates():
    r = FakeRunner([(["nmcli", "-t", "-f", "NAME,TYPE"], NM_CONN), (["nmcli", "connection", "delete"], CmdResult(0)),
                    (["nmcli", "-w"], CmdResult(0))])
    NmcliWifi(r).connect("Home", "newpass99")
    assert ["nmcli", "connection", "delete", "id", "Home"] in r.calls
    assert r.calls[-1][:5] == ["nmcli", "-w", "30", "device", "wifi"]


def test_nmcli_failed_connect_removes_half_made_profile_and_explains():
    r = FakeRunner([(["nmcli", "-t", "-f", "NAME,TYPE"], CmdResult(0, "")),
                    (["nmcli", "-w"], CmdResult(4, "", "Error: Connection activation failed: Secrets were required")),
                    (["nmcli", "connection", "delete"], CmdResult(0))])
    with pytest.raises(NetError, match="비밀번호가 맞지 않습니다"):
        NmcliWifi(r).connect("Office", "wrongpass")
    assert ["nmcli", "connection", "delete", "id", "Office"] in r.calls


def test_nmcli_missing_command_message():
    r = FakeRunner([(["nmcli"], CmdResult(127, "", "x"))])
    with pytest.raises(NetError, match="nmcli"):
        NmcliWifi(r).radio()


def test_nmcli_current_reads_ssid_and_ip():
    out = "GENERAL.STATE:100 (connected)\nGENERAL.CONNECTION:Home\nIP4.ADDRESS[1]:192.168.0.7/24\n"
    r = FakeRunner([(["nmcli", "-t", "-f", "DEVICE,TYPE"], CmdResult(0, "wlan0:wifi\neth0:ethernet\n")),
                    (["nmcli", "-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS"], CmdResult(0, out))])
    assert NmcliWifi(r).current() == ("Home", "192.168.0.7")


def test_mock_wifi_flow():
    w = MockWifi(delay=0)
    assert w.scan()[0].ssid == "Nformare-Lab"
    with pytest.raises(NetError):
        w.connect("Office_5G", "wrong")
    w.connect("Office_5G", MockWifi.PASSWORD)
    assert w.current()[0] == "Office_5G" and w.scan()[0].in_use
    w.set_radio(False)
    assert w.current()[0] is None
    with pytest.raises(NetError):
        w.scan()


# ---------------- Bluetooth ----------------
def test_parse_devices_and_info():
    assert parse_devices("Device AA:BB:CC:DD:EE:FF My Phone\nDevice 11:22:33:44:55:66 \nfoo\n") == [
        ("AA:BB:CC:DD:EE:FF", "My Phone"), ("11:22:33:44:55:66", "")]
    info = parse_info("Device AA:BB:CC:DD:EE:FF (public)\n\tName: Phone\n\tAlias: My Phone\n\tPaired: yes\n"
                      "\tTrusted: yes\n\tConnected: no\n\tRSSI: 0xffffffc4 (-60)\n")
    d = make_device("AA:BB:CC:DD:EE:FF", "x", info)
    assert (d.name, d.paired, d.trusted, d.connected, d.rssi) == ("My Phone", True, True, False, -60)


def test_clean_strips_ansi():
    assert clean("\x1b[0;94m[bluetooth]\x1b[0m# ok\r") == "[bluetooth]# ok"


def test_bt_devices_sorted_and_unnamed_last():
    info = {"AA:00:00:00:00:01": "Alias: Printer\nPaired: yes\nConnected: yes\n",
            "AA:00:00:00:00:02": "Alias: Speaker\nRSSI: -50\n",
            "AA:00:00:00:00:03": "Alias: AA-00-00-00-00-03\nRSSI: -40\n"}
    r = FakeRunner([(["bluetoothctl", "devices"], CmdResult(0, "\n".join(f"Device {m} {m}" for m in info))),
                    (["bluetoothctl", "info"], lambda a: CmdResult(0, info[a[2]]))])
    devs = BluetoothctlBackend(r).devices()
    assert [d.mac[-2:] for d in devs] == ["01", "02", "03"]
    assert not devs[2].named


def test_bt_powered_and_errors():
    ok = FakeRunner([(["bluetoothctl", "show"], CmdResult(0, "Controller AA:BB:CC:DD:EE:FF (public)\n\tPowered: yes\n"))])
    assert BluetoothctlBackend(ok).powered() is True
    none = FakeRunner([(["bluetoothctl", "show"], CmdResult(0, "No default controller available\n"))])
    with pytest.raises(NetError, match="찾을 수 없습니다"):
        BluetoothctlBackend(none).powered()
    miss = FakeRunner([(["bluetoothctl"], CmdResult(127, "", "x"))])
    with pytest.raises(NetError, match="bluez"):
        BluetoothctlBackend(miss).powered()


def test_bt_register_pairs_trusts_connects():
    r = FakeRunner([(["bluetoothctl", "trust"], CmdResult(0, "trust succeeded")),
                    (["bluetoothctl", "connect"], CmdResult(0, "Connection successful"))])
    be = BluetoothctlBackend(r, pairer=lambda mac: (True, "Pairing successful"))
    assert "연결" in be.register("AA:BB:CC:DD:EE:FF")
    assert ["bluetoothctl", "trust", "AA:BB:CC:DD:EE:FF"] in r.calls


def test_bt_register_pair_failure_and_connect_failure():
    be = BluetoothctlBackend(FakeRunner([]),
                             pairer=lambda mac: (False, "Failed to pair: org.bluez.Error.AuthenticationFailed"))
    with pytest.raises(NetError, match="인증"):
        be.register("AA:BB:CC:DD:EE:FF")
    r = FakeRunner([(["bluetoothctl", "trust"], CmdResult(0, "")),
                    (["bluetoothctl", "connect"], CmdResult(0, "Failed to connect: org.bluez.Error.Failed"))])
    msg = BluetoothctlBackend(r, pairer=lambda m: (True, "")).register("AA:BB:CC:DD:EE:FF")
    assert "등록했습니다" in msg                          # 등록은 됐고 연결만 안 된 경우


def test_bt_connect_disconnect_remove_check_text():
    r = FakeRunner([(["bluetoothctl", "connect"], CmdResult(0, "Failed to connect: org.bluez.Error.Failed page timeout")),
                    (["bluetoothctl", "disconnect"], CmdResult(0, "Successful disconnected")),
                    (["bluetoothctl", "remove"], CmdResult(0, "Device has been removed"))])
    be = BluetoothctlBackend(r)
    with pytest.raises(NetError, match="닿지 않습니다"):
        be.connect("AA:BB:CC:DD:EE:FF")
    assert "해제" in be.disconnect("AA:BB:CC:DD:EE:FF")
    assert "삭제" in be.remove("AA:BB:CC:DD:EE:FF")


def test_bt_friendly_error_default_includes_detail():
    assert bt_err("something odd", "실패").startswith("실패 (")


def test_mock_bluetooth_flow():
    b = MockBluetooth(delay=0)
    assert [d.paired for d in b.devices()] == [True]               # 검색 전에는 등록된 장치만
    seen = b.scan()
    assert len(seen) == 4
    b.register("AA:BB:CC:00:00:03")
    assert [d for d in b.devices() if d.mac.endswith("03")][0].connected
    with pytest.raises(NetError):
        b.register("AA:BB:CC:00:00:04")
    b.remove("AA:BB:CC:00:00:03")
    assert not [d for d in b.devices() if d.mac.endswith("03")][0].paired


def _fast(monkeypatch):
    import app.net.bluetooth as nb
    monkeypatch.setattr(nb.time, "sleep", lambda s: None)


def test_bt_power_on_that_does_not_stick_is_reported_with_cause(monkeypatch):
    _fast(monkeypatch)
    show_off = CmdResult(0, "Controller AA:BB:CC:DD:EE:FF (public)\n\tPowered: no\n")
    soft = CmdResult(0, "0: hci0: Bluetooth\n\tSoft blocked: yes\n\tHard blocked: no\n")
    r = FakeRunner([(["rfkill", "unblock"], CmdResult(0)),
                    (["bluetoothctl", "power"], CmdResult(0, "Changing power on succeeded")),
                    (["bluetoothctl", "show"], show_off), (["rfkill", "list"], soft)])
    with pytest.raises(NetError, match="rfkill unblock"):
        BluetoothctlBackend(r).set_power(True)


def test_bt_power_on_busy_retries_until_it_works(monkeypatch):
    """실기 오류: 'Failed to set power on: org.bluez.Error.Busy' — 잠시 뒤 다시 시도하면 켜진다."""
    _fast(monkeypatch)
    state = {"n": 0}

    def power(args):
        state["n"] += 1
        return (CmdResult(0, "Failed to set power on: org.bluez.Error.Busy") if state["n"] < 3
                else CmdResult(0, "Changing power on succeeded"))

    def show(args):
        return CmdResult(0, "Controller X\n\tPowered: " + ("yes" if state["n"] >= 3 else "no") + "\n")

    r = FakeRunner([(["rfkill", "unblock"], CmdResult(0)), (["bluetoothctl", "power"], power),
                    (["bluetoothctl", "show"], show)])
    BluetoothctlBackend(r).set_power(True)
    assert state["n"] == 3


def test_bt_power_on_busy_but_already_on_is_success(monkeypatch):
    _fast(monkeypatch)
    r = FakeRunner([(["rfkill", "unblock"], CmdResult(0)),
                    (["bluetoothctl", "power"], CmdResult(0, "Failed to set power on: org.bluez.Error.Busy")),
                    (["bluetoothctl", "show"], CmdResult(0, "Controller X\n\tPowered: yes\n"))])
    BluetoothctlBackend(r).set_power(True)


def test_bt_power_on_busy_forever_gives_clear_message(monkeypatch):
    _fast(monkeypatch)
    r = FakeRunner([(["rfkill", "unblock"], CmdResult(0)),
                    (["bluetoothctl", "power"], CmdResult(0, "Failed to set power on: org.bluez.Error.Busy")),
                    (["bluetoothctl", "show"], CmdResult(0, "Controller X\n\tPowered: no\n")),
                    (["rfkill", "list"], CmdResult(0, "0: hci0: Bluetooth\n\tSoft blocked: no\n\tHard blocked: no\n")),
                    (["systemctl", "is-active"], CmdResult(0, "active"))])
    with pytest.raises(NetError, match="Busy"):
        BluetoothctlBackend(r).set_power(True)


def test_bt_diagnose_service_inactive_and_missing_device():
    ok_dev = CmdResult(0, "0: hci0: Bluetooth\n\tSoft blocked: no\n\tHard blocked: no\n")
    r = FakeRunner([(["rfkill", "list"], ok_dev), (["systemctl", "is-active"], CmdResult(3, "inactive"))])
    assert "systemctl enable --now bluetooth" in BluetoothctlBackend(r).diagnose()
    none = FakeRunner([(["rfkill", "list"], CmdResult(0, ""))])
    assert "disable-bt" in BluetoothctlBackend(none).diagnose()


def test_bt_power_off_works(monkeypatch):
    _fast(monkeypatch)
    r = FakeRunner([(["bluetoothctl", "power"], CmdResult(0, "Changing power off succeeded")),
                    (["bluetoothctl", "show"], CmdResult(0, "Controller X\n\tPowered: no\n"))])
    BluetoothctlBackend(r).set_power(False)


def test_bt_powered_waits_while_adapter_is_enabling(monkeypatch):
    _fast(monkeypatch)
    seq = iter(["Controller X\n\tPowered: no\n\tPowerState: off-enabling\n", "Controller X\n\tPowered: yes\n\tPowerState: on\n"])
    r = FakeRunner([(["bluetoothctl", "show"], lambda a: CmdResult(0, next(seq)))])
    assert BluetoothctlBackend(r).powered() is True
