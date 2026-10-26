"""UART 확인용 콘솔 도구 (펌웨어 텍스트 프로토콜).

    # 가상 펌웨어로 한 단계(센서 0,1,2 순차 측정) 시연
    python tools/uart_demo.py --mock --measure --points 5

    # 수신 모니터: 상대(예: PC 의 Tera Term)가 보낸 줄을 원문 + 파싱 결과로 출력
    python tools/uart_demo.py --port /dev/serial0 --listen 60

    # 명령 보내기: Tera Term 에 그대로 보이는지 확인
    python tools/uart_demo.py --port /dev/serial0 --send STATUS --send "SWEEP 10 200000 101" --listen 5

    # 실제 모듈 점검: STATUS / CALSTATUS / ENV 조회
    python tools/uart_demo.py --port /dev/serial0 --probe
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import QCoreApplication, QTimer  # noqa: E402

from app.config import load_config  # noqa: E402
from comm import protocol as p  # noqa: E402
from comm.firmware_client import FirmwareClient  # noqa: E402
from comm.transport import create_transport  # noqa: E402
from comm.uart_worker import UartWorker  # noqa: E402


def main() -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true", help="가상 펌웨어 사용")
    ap.add_argument("--port", default=cfg.uart_port)
    ap.add_argument("--baud", type=int, default=cfg.uart_baudrate)
    ap.add_argument("--probe", action="store_true", help="STATUS/CALSTATUS/ENV 조회")
    ap.add_argument("--send", action="append", default=[], metavar="LINE", help="명령 줄 전송 (여러 번 가능)")
    ap.add_argument("--measure", action="store_true", help="한 단계 측정: SWEEP/CHAN/VERB 설정 후 START 1")
    ap.add_argument("--start-hz", type=float, default=10.0)
    ap.add_argument("--stop-hz", type=float, default=200000.0)
    ap.add_argument("--points", type=int, default=101)
    ap.add_argument("--channels", default="0,1,2")
    ap.add_argument("--listen", type=float, default=0.0, metavar="SEC", help="이 시간 동안 수신 줄 출력")
    ap.add_argument("--timeout", type=float, default=600.0, help="--measure 최대 대기(초)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    app = QCoreApplication(sys.argv)
    worker = UartWorker(create_transport(a.port, a.baud, a.mock))
    client = FirmwareClient(worker)
    exit_code = [0]

    client.rawLine.connect(lambda l: print("RX  ", l))
    client.parseError.connect(lambda l, why: print("BAD ", why))
    # --measure 중에는 #M 이 너무 많아 파싱 결과를 숨기고 점 수만 센다. 그 외(모니터/전송)는 모두 출력.
    client.recordReceived.connect(
        lambda r: None if (a.measure and isinstance(r, p.MeasRecord)) else print("     ->", r))
    client.commandFinished.connect(lambda t, ok, m: print(f"CMD  {t!r} {'OK' if ok else 'FAIL'}: {m}"))
    client.firmwareError.connect(lambda m: print("ERR ", m))
    client.measurementFailed.connect(lambda m: (print("FAILED", m), exit_code.__setitem__(0, 1), app.quit()))
    counts = {0: 0, 1: 0, 2: 0, 3: 0}

    def on_rec(r):
        if isinstance(r, p.MeasRecord):
            counts[r.ch] += 1

    client.recordReceived.connect(on_rec)

    def run_actions():
        if a.probe:
            client.query_status(); client.query_cal_status(); client.query_env()
        for line in a.send:
            client.send_command(line)
        if a.measure:
            chans = [int(c) for c in a.channels.split(",")]
            client.set_sweep(a.start_hz, a.stop_hz, a.points)
            client.set_channels(chans)
            client.set_verb("FULL")
            client.start(1)
            client.measurementStopped.connect(finish_measure)
            QTimer.singleShot(int(a.timeout * 1000), lambda: (print("시간 초과"), exit_code.__setitem__(0, 1), app.quit()))
        elif a.listen:
            QTimer.singleShot(int(a.listen * 1000), app.quit)
        else:
            QTimer.singleShot(2000, app.quit)

    def finish_measure():
        print("점 수:", {f"CH{c}": n for c, n in counts.items() if n})
        app.quit()

    client.connectionChanged.connect(lambda ok: print("연결됨" if ok else "연결 끊김"))
    first = [True]

    def on_connected(ok):
        if ok and first[0]:
            first[0] = False
            run_actions()

    client.connectionChanged.connect(on_connected)
    app.aboutToQuit.connect(worker.stop)
    worker.start()
    app.exec_()
    return exit_code[0]


if __name__ == "__main__":
    sys.exit(main())
