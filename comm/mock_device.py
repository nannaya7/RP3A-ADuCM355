"""가상 ADuCM355 펌웨어. Transport 인터페이스를 구현하며 PC 개발·테스트용.

실제 펌웨어(docs/uart_protocol.md)의 명령과 출력 형식을 흉내 낸다:
  - 센서는 CH0 → CH1 → CH2 순서로 **채널마다 전체 스윕**을 끝낸 뒤 다음 채널로 간다
  - START 마다 `#H`, `measurement started`, AFE 별 첫 점 직전 `#C`, 점마다 `#M`,
    채널 끝에 `RANGE`, 사이클 끝에 `CYCLE=n done`, 지정 사이클이 끝나면 `measurement stopped`
  - STOP 은 실행 중일 때만 응답한다
  - 오류 후에도 측정이 멈추지 않고 같은 사이클을 처음부터 다시 시도한다 (실제 펌웨어 동작)
결함 주입: fault_after_points, hang_after_points, reboot(), fail_next_read()
"""
import cmath
import math
import time
from typing import Callable, Optional

from .protocol import LineBuffer, MAX_CMD_LEN

FW_VERSION = "V.0.03.305"
BANNER = "ADuCM355 3-wire bio-impedance, " + FW_VERSION
FREQ_MIN, FREQ_MAX, POINTS_MAX = 0.016, 200000.0, 500


def troponin_demo_z(fw):
    """데모용: 단계(START 횟수)마다 Troponin 모델이 QC 를 통과하는 곡선. 센서 3개는 거의 같은 값."""
    def z(ch: int, f: float) -> complex:
        stage = (fw.start_count - 1) % 3
        w = 2.0 * math.pi * f
        z1 = 100.0 + 5000.0 / (1.0 + 1j * w * 5000.0 * 1e-6)
        if stage == 0:
            v = z1
        elif stage == 1:
            v = 150.0 - 112.0j      # c0 = 첫 측정(약 72 Ω)보다 약 40 Ω 큰 −Im → B 가 정상 범위 (과거 Day-1 기준 240 Ω 일 때는 280)
        else:
            v = z1 + abs(z1) * 0.01j * 15.0
        return complex(v * (1.0 + 0.002 * ch))
    return z


def synthetic_z(ch: int, freq_hz: float) -> complex:
    """Randles 형 임피던스 (채널마다 약간 다른 값)."""
    rs = 100.0 + 20.0 * ch
    rct = 5000.0 * (1.0 + 0.3 * ch)
    c = 1.0e-6
    w = 2.0 * math.pi * freq_hz
    return rs + rct / (1.0 + 1j * w * rct * c)


class MockFirmware:
    name = "mock-firmware"

    def __init__(self, point_interval: float = 0.005, boot_banner: bool = False,
                 z_func: Callable = synthetic_z) -> None:
        self.point_interval = point_interval
        self.boot_banner = boot_banner
        self.z_func = z_func
        # 결함 주입 (None = 끔)
        self.fault_after_points: Optional[int] = None   # 사이클 안에서 N점 후 ERR
        self.hang_after_points: Optional[int] = None    # N점 후 출력 중단
        self.cal_valid = True
        self.board_id = 1
        self.sent_lines: list = []                      # 받은 명령 기록 (테스트용)
        self.start_count = 0                            # START 를 받은 횟수 (테스트에서 단계별 곡선 선택용)
        self._open = False
        self._fail_read = False
        self._t0 = time.monotonic()
        self._rx = LineBuffer()
        self._immediate: list = []
        self._gen = None
        self._due = 0.0
        self.running = False
        self._reset_config()

    def _reset_config(self) -> None:
        self.start_hz = self.stop_hz = 1000.0
        self.points = 1
        self.mask = 0x7
        self.verb = "FULL"
        self.rcal = 1000.0
        self.signal = (300.0, "X0P2", "X0P25")
        self.cycles = 0
        self.cycle_done = 0

    # ---- Transport ----------------------------------------------------------
    def open(self) -> None:
        self._open = True
        self._t0 = time.monotonic()
        if self.boot_banner:
            self._boot()

    def close(self) -> None:
        self._open = False
        self._gen = None
        self.running = False
        self._immediate.clear()

    def read(self) -> bytes:
        if not self._open or self._fail_read:
            self._fail_read = False
            raise OSError("mock read failed")
        now = time.monotonic()
        out = list(self._immediate)
        self._immediate.clear()
        while self._gen is not None and now >= self._due:
            try:
                line, delay = next(self._gen)
            except StopIteration:
                self._gen = None
                break
            if line:
                out.append(line)
            self._due += delay
        if not out:
            time.sleep(0.002)
            return b""
        return ("\r\n".join(out) + "\r\n").encode("ascii")

    def write(self, data: bytes) -> None:
        if not self._open:
            raise OSError("mock closed")
        for line in self._rx.feed(data):
            self.sent_lines.append(line)
            self._exec(line)

    # ---- 테스트용 조작 --------------------------------------------------------
    def reboot(self) -> None:
        """모듈 리셋: 진행 중 측정이 사라지고 부팅 배너가 나온다."""
        self._boot()

    def fail_next_read(self) -> None:
        self._fail_read = True

    def _boot(self) -> None:
        self._gen = None
        self.running = False
        self._reset_config()
        self._t0 = time.monotonic()
        self._info("INFO", BANNER)
        self._info("INFO", "HDC2010 ready (1Hz auto measurement)")
        self._info("INFO", "System ready - send START to begin")

    # ---- 출력 헬퍼 -----------------------------------------------------------
    def _ts(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    def _info(self, level: str, msg: str) -> None:
        self._immediate.append(f"#I,{self._ts():06d},{level},{msg}")

    def _line_info(self, level: str, msg: str) -> str:
        return f"#I,{self._ts():06d},{level},{msg}"

    # ---- 명령 ----------------------------------------------------------------
    def _exec(self, line: str) -> None:
        if len(line) > MAX_CMD_LEN:
            self._info("ERR", "command too long")
            return
        words = line.upper().split()
        if not words:
            return
        handler = getattr(self, "_cmd_" + words[0].lower(), None)
        if handler is None:
            self._info("ERR", "unknown command")
            return
        handler(words)

    def _cmd_sweep(self, w) -> None:
        if len(w) < 4:
            self._info("ERR", "usage: SWEEP <START_HZ> <STOP_HZ> <POINTS>")
            return
        start = min(max(float(w[1]), FREQ_MIN), FREQ_MAX)
        stop = min(max(float(w[2]), FREQ_MIN), FREQ_MAX)
        points = min(max(int(float(w[3])), 1), POINTS_MAX)
        if points == 1:
            stop = start
        self.start_hz, self.stop_hz, self.points = start, stop, points
        self._info("INFO", f"SWEEP set {start:.2f} {stop:.2f} {points}")

    def _cmd_chan(self, w) -> None:
        if len(w) < 2:
            self._info("ERR", "usage: CHAN <CH0..CH3 | list | 0xMASK | ALL | DEFAULT>")
            return
        mask = 0
        for tok in " ".join(w[1:]).replace(",", " ").split():
            if tok == "ALL":
                mask |= 0xF
            elif tok == "DEFAULT":
                mask |= 0x7
            elif tok.startswith("0X"):
                mask |= int(tok[2:], 16)
            elif len(tok) == 3 and tok.startswith("CH") and tok[2] in "0123":
                mask |= 1 << int(tok[2])
            else:
                self._info("ERR", "unknown channel")
                return
        if mask == 0:
            self._info("ERR", "no channel selected")
            return
        if mask & ~0xF:
            self._info("ERR", "channel mask out of range")
            return
        self.mask = mask
        self._info("INFO", f"CHMASK=0x{mask:X}")

    def _cmd_verb(self, w) -> None:
        if len(w) < 2:
            self._info("ERR", "usage: VERB <FULL|COMPACT|RAW>")
        elif w[1] in ("FULL", "COMPACT", "RAW"):
            self.verb = w[1]
            self._info("INFO", f"VERB={w[1]}")
        else:
            self._info("ERR", "unknown verbosity")

    def _cmd_signal(self, w) -> None:
        if len(w) < 4:
            self._info("ERR", "usage: SIGNAL <DACVOLTPP_MV> <X1|X0P2> <X2|X0P25>")
            return
        mv = min(max(float(w[1]), 0.0), 800.0)
        self.signal = (mv, w[2], w[3])
        self._info("INFO", f"SIGNAL set {mv:.1f} {w[2]} {w[3]}")

    def _cmd_rcal(self, w) -> None:
        if len(w) < 2:
            self._info("ERR", "usage: RCAL <OHM>")
            return
        self.rcal = min(max(float(w[1]), 1.0), 1.0e7)
        self._info("INFO", f"RCAL set {self.rcal:.1f}")

    def _cmd_status(self, w) -> None:
        mv, g1, g2 = self.signal
        self._info("STATUS",
                   f"RUN={int(self.running)} SWEEP={self.start_hz:.2f}:{self.stop_hz:.2f}:{self.points} "
                   f"CHMASK=0x{self.mask:X} MODE=SEQ VERB={self.verb} SIGNAL={mv:.1f}:{g1}:{g2} "
                   f"RCAL={self.rcal:.1f} RTIA=AUTO PWRMODE=AUTO CYCLES={self.cycles} "
                   f"DONE={self.cycle_done} DCEN=0 DCBIAS=100.0")

    def _cmd_env(self, w) -> None:
        self._info("INFO", "ENV TEMP_C=24.3 HUM_RH=41.2")

    def _cmd_calstatus(self, w) -> None:
        bid = str(self.board_id) if self.cal_valid else "UNSET"
        self._info("STATUS", f"CAL VALID={int(self.cal_valid)} ENABLED={int(self.cal_valid)} BOARD_ID={bid}")

    def _cmd_start(self, w) -> None:
        cycles = int(w[1]) if len(w) >= 2 and w[1].isdigit() else 1
        self.cycles, self.cycle_done, self.running = cycles, 0, True
        self.start_count += 1
        freqs = self._freqs()
        self._immediate.append(
            f"#H,FW={FW_VERSION},RCAL={self.rcal:.1f},MODE=SEQ,COLUMNS=TIMESTAMP|CH|FREQ_HZ|Z_REAL|"
            "Z_IMAG|MAG_OHM|PHASE_DEG|R_OHM|X_OHM|TEMP_C|HUM_RH|STATUS")
        self._info("INFO", "measurement started, continuous" if cycles == 0
                   else f"measurement started, {cycles} cycle(s)")
        self._gen = self._run(freqs)
        self._due = time.monotonic()

    def _cmd_stop(self, w) -> None:
        if not self.running:
            return                       # 실제 펌웨어: 실행 중이 아니면 응답 없음
        self.running = False
        self._gen = None
        self._info("INFO", "measurement stopped")

    # ---- 측정 시뮬레이션 --------------------------------------------------------
    def _freqs(self) -> list:
        if self.points == 1:
            return [self.start_hz]
        r = (self.stop_hz / self.start_hz) ** (1.0 / (self.points - 1))
        return [self.start_hz * r ** k for k in range(self.points)]

    def _meas_line(self, ch: int, f: float) -> str:
        z = self.z_func(ch, f)
        mag, ph = abs(z), math.degrees(cmath.phase(z))
        ts = self._ts()
        if self.verb == "RAW":
            return f"#M,{ts:06d},CH{ch},{f:.2f},{int(z.real * 10)},{int(z.imag * 10)},OK"
        if self.verb == "COMPACT":
            return f"#M,{ts:06d},CH{ch},{f:.2f},{mag:.2f},{ph:.2f},24.3,41.2,OK"
        return (f"#M,{ts:06d},CH{ch},{f:.2f},{int(z.real * 10)},{int(z.imag * 10)},"
                f"{mag:.2f},{ph:.2f},{z.real:.2f},{z.imag:.2f},24.3,41.2,OK")

    def _run(self, freqs):
        """(줄, 다음 줄까지 지연) 을 내놓는 제너레이터. 실제 펌웨어의 BIA_Process 루프에 해당."""
        reported_afe = set()
        while self.running:
            restart = False
            n_points = 0
            for ch in range(4):
                if not self.mask & (1 << ch):
                    continue
                afe = 0 if ch < 2 else 1
                if afe not in reported_afe:
                    reported_afe.add(afe)
                    yield f"#C,{self._ts():06d},AFE{afe},{self.rcal:.1f},-1200,340,OK", 0.0
                for f in freqs:
                    if self.hang_after_points is not None and n_points >= self.hang_after_points:
                        while True:             # 출력 중단 (AFE 정지 흉내)
                            yield None, 0.05
                    if self.fault_after_points is not None and n_points >= self.fault_after_points:
                        yield self._line_info("ERR", "measurement timeout"), 0.01
                        restart = True          # 펌웨어는 멈추지 않고 사이클을 다시 시작한다
                        break
                    yield self._meas_line(ch, f), self.point_interval
                    n_points += 1
                if restart:
                    break
                yield self._line_info("INFO", f"RANGE CH{ch} RTIA=1000..20000 RETRY=0 SAT=0"), 0.0
            if restart:
                continue
            self.cycle_done += 1
            yield self._line_info("INFO", f"CYCLE={self.cycle_done} done"), 0.0
            if self.cycles != 0:
                self.cycles -= 1
                if self.cycles == 0:
                    self.running = False
                    yield self._line_info("INFO", "measurement stopped"), 0.0
                    return
