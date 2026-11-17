"""Wi-Fi / 블루투스 관리 (Raspberry Pi OS: NetworkManager 의 nmcli, BlueZ 의 bluetoothctl).

화면(ui/settings_page.py)은 여기 백엔드 객체의 메서드만 부른다. PC 개발용 가상 백엔드(Mock*)도 같은 모양이다.
"""
import sys

from .bluetooth import BluetoothctlBackend, BtDevice, MockBluetooth
from .errors import NetError
from .wifi import MockWifi, NmcliWifi, WifiNetwork

__all__ = ["BluetoothctlBackend", "BtDevice", "MockBluetooth", "MockWifi", "NetError", "NmcliWifi", "WifiNetwork",
           "create_bluetooth", "create_wifi"]


def create_wifi(mock: bool = False):
    """mock=True 이거나 Windows PC 이면 가상 백엔드, 아니면 nmcli."""
    return MockWifi() if (mock or sys.platform == "win32") else NmcliWifi()


def create_bluetooth(mock: bool = False):
    return MockBluetooth() if (mock or sys.platform == "win32") else BluetoothctlBackend()
