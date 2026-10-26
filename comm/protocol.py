"""ADuCM355 펌웨어 UART 프로토콜 (줄 단위 ASCII). Qt 의존 없음.

출력 레코드(`#I/#H/#M/#C/#D/#T/#B`)의 파싱과 명령 문자열 생성을 맡는다.
규격: docs/uart_protocol.md
"""
import re
from dataclasses import dataclass
from typing import Iterable, Optional

MAX_CMD_LEN = 63          # 펌웨어 줄 버퍼 64바이트(종단 문자 포함)
CHANNEL_COUNT = 4         # CH0..CH3 (CH0..CH2 가 센서 3개)
LEVELS = ("INFO", "WARN", "ERR", "STATUS")


class ParseError(ValueError):
    """# 로 시작하지만 형식이 맞지 않는 줄."""


# ---- 레코드 ----------------------------------------------------------------
@dataclass(frozen=True)
class InfoRecord:            # #I,<TS>,<LEVEL>,<msg>
    ts: int
    level: str
    msg: str


@dataclass(frozen=True)
class HeaderRecord:          # #H,FW=..,RCAL=..,MODE=..,COLUMNS=a|b|c   (타임스탬프 없음)
    fw: str
    rcal_ohm: float
    mode: str
    columns: tuple


@dataclass(frozen=True)
class MeasRecord:            # #M  (VERB 에 따라 FULL 13 / COMPACT 9 / RAW 7 필드)
    ts: int
    ch: int
    freq_hz: float
    status: str
    mag_ohm: Optional[float] = None
    phase_deg: Optional[float] = None
    temp_c: Optional[float] = None
    hum_rh: Optional[float] = None
    z_real: Optional[int] = None
    z_imag: Optional[int] = None
    r_ohm: Optional[float] = None
    x_ohm: Optional[float] = None

    @property
    def sat(self) -> bool:
        return self.status == "SAT"


@dataclass(frozen=True)
class CalRefRecord:          # #C,<TS>,AFEn,<RCAL>,<real>,<imag>,OK
    ts: int
    afe: int
    rcal_ohm: float
    real: int
    imag: int
    status: str


@dataclass(frozen=True)
class DcRecord:              # #D,<TS>,CHn,<bias_mv>,<current_ua>,<rtia>,OK|ERR
    ts: int
    ch: int
    bias_mv: float
    current_ua: float
    rtia_ohm: float
    ok: bool


@dataclass(frozen=True)
class ChronoRecord:          # #T,<TS>,CHn,<t_ms>,<current_ua>,<rtia>,OK|SAT
    ts: int
    ch: int
    t_ms: int
    current_ua: float
    rtia_ohm: float
    sat: bool


@dataclass(frozen=True)
class BlockRecord:           # #B,<TS>,HDR|PT,...  (CALSHOW, 서비스용) — 필드는 원문 그대로
    ts: int
    kind: str
    fields: tuple


Record = (InfoRecord, HeaderRecord, MeasRecord, CalRefRecord, DcRecord, ChronoRecord, BlockRecord)


# ---- 파싱 ------------------------------------------------------------------
def _ch(tok: str) -> int:
    m = re.fullmatch(r"CH([0-9])", tok)
    if not m:
        raise ValueError(f"bad channel {tok!r}")
    return int(m.group(1))


def _afe(tok: str) -> int:
    m = re.fullmatch(r"AFE([0-9])", tok)
    if not m:
        raise ValueError(f"bad afe {tok!r}")
    return int(m.group(1))


def _status(tok: str, allowed=("OK", "SAT")) -> str:
    if tok not in allowed:
        raise ValueError(f"bad status {tok!r}")
    return tok


def parse_line(line: str):
    """한 줄을 레코드로 변환한다.

    - `#` 로 시작하지 않는 줄, 알 수 없는 종류(`#X`)는 `None` (무시)
    - 알려진 종류인데 형식이 깨졌으면 `ParseError`
    """
    line = line.strip()
    if len(line) < 2 or line[0] != "#":
        return None
    kind = line[1]
    try:
        if kind == "I":
            parts = line.split(",", 3)
            if len(parts) != 4 or parts[2] not in LEVELS:
                raise ValueError("bad #I")
            return InfoRecord(int(parts[1]), parts[2], parts[3])

        if kind == "H":
            kv = dict(p.split("=", 1) for p in line.split(",")[1:] if "=" in p)
            return HeaderRecord(kv["FW"], float(kv["RCAL"]), kv["MODE"],
                                tuple(kv["COLUMNS"].split("|")))

        f = line.split(",")
        if kind == "M":
            ts, ch, freq = int(f[1]), _ch(f[2]), float(f[3])
            if len(f) == 13:      # FULL
                return MeasRecord(ts, ch, freq, _status(f[12]),
                                  mag_ohm=float(f[6]), phase_deg=float(f[7]),
                                  temp_c=float(f[10]), hum_rh=float(f[11]),
                                  z_real=int(f[4]), z_imag=int(f[5]),
                                  r_ohm=float(f[8]), x_ohm=float(f[9]))
            if len(f) == 9:       # COMPACT
                return MeasRecord(ts, ch, freq, _status(f[8]),
                                  mag_ohm=float(f[4]), phase_deg=float(f[5]),
                                  temp_c=float(f[6]), hum_rh=float(f[7]))
            if len(f) == 7:       # RAW
                return MeasRecord(ts, ch, freq, _status(f[6]),
                                  z_real=int(f[4]), z_imag=int(f[5]))
            raise ValueError(f"#M field count {len(f)}")

        if kind == "C":
            if len(f) != 7:
                raise ValueError("bad #C")
            return CalRefRecord(int(f[1]), _afe(f[2]), float(f[3]), int(f[4]), int(f[5]),
                                _status(f[6], ("OK",)))

        if kind == "D":
            if len(f) != 7:
                raise ValueError("bad #D")
            return DcRecord(int(f[1]), _ch(f[2]), float(f[3]), float(f[4]), float(f[5]),
                            _status(f[6], ("OK", "ERR")) == "OK")

        if kind == "T":
            if len(f) != 7:
                raise ValueError("bad #T")
            return ChronoRecord(int(f[1]), _ch(f[2]), int(f[3]), float(f[4]), float(f[5]),
                                _status(f[6]) == "SAT")

        if kind == "B":
            if len(f) < 3:
                raise ValueError("bad #B")
            return BlockRecord(int(f[1]), f[2], tuple(f[3:]))
    except (ValueError, KeyError, IndexError) as e:
        raise ParseError(f"{line[:60]!r}: {e}") from e
    return None


def parse_kv(msg: str) -> dict:
    """`RUN=0 SWEEP=1000.00:1000.00:1 CHMASK=0x7 ...` 같은 메시지를 {키: 값} 으로."""
    return dict(tok.split("=", 1) for tok in msg.split() if "=" in tok)


# ---- 줄 버퍼 ---------------------------------------------------------------
class LineBuffer:
    """바이트 스트림을 줄 단위로 자른다. CR, LF, CRLF 를 모두 줄 끝으로 본다."""

    def __init__(self, max_len: int = 512) -> None:
        self._buf = bytearray()
        self._max = max_len
        self._overflow = False
        self.dropped_lines = 0

    def feed(self, data: bytes) -> list:
        lines = []
        for b in data:
            if b in (0x0D, 0x0A):
                if self._overflow:
                    self._overflow = False
                    self.dropped_lines += 1
                elif self._buf:
                    lines.append(self._buf.decode("ascii", errors="replace"))
                self._buf.clear()
            elif not self._overflow:
                if len(self._buf) >= self._max:
                    self._overflow = True   # 줄 끝까지 버린다
                    self._buf.clear()
                else:
                    self._buf.append(b)
        return lines


# ---- 명령 생성 -------------------------------------------------------------
def check_cmd(line: str) -> str:
    """명령 줄 검증: ASCII, 줄바꿈 없음, 63자 이하."""
    if not line or "\r" in line or "\n" in line:
        raise ValueError("명령은 비어 있지 않은 한 줄이어야 합니다")
    if not line.isascii():
        raise ValueError("명령은 ASCII 여야 합니다")
    if len(line) > MAX_CMD_LEN:
        raise ValueError(f"명령이 너무 깁니다 ({len(line)} > {MAX_CMD_LEN})")
    return line


def fmt_num(v: float) -> str:
    """지수 표기 없이 최소 자릿수로 (펌웨어 atof 용)."""
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s or "0"


def ch_name(ch: int) -> str:
    return f"CH{ch}"


def cmd_sweep(start_hz: float, stop_hz: float, points: int) -> str:
    return check_cmd(f"SWEEP {fmt_num(start_hz)} {fmt_num(stop_hz)} {int(points)}")


def cmd_chan(channels: Iterable) -> str:
    chs = sorted(set(int(c) for c in channels))
    if not chs or any(not 0 <= c < CHANNEL_COUNT for c in chs):
        raise ValueError("채널은 0..3 중 하나 이상이어야 합니다")
    return check_cmd("CHAN " + ",".join(ch_name(c) for c in chs))


def cmd_verb(mode: str) -> str:
    mode = mode.upper()
    if mode not in ("FULL", "COMPACT", "RAW"):
        raise ValueError("VERB 는 FULL/COMPACT/RAW")
    return f"VERB {mode}"


def cmd_start(cycles: int = 1) -> str:
    if cycles < 0:
        raise ValueError("cycles >= 0")
    return f"START {int(cycles)}"


CMD_STOP = "STOP"
CMD_STATUS = "STATUS"
CMD_ENV = "ENV"
CMD_CALSTATUS = "CALSTATUS"
