"""외부 명령 실행. 백엔드는 runner 를 주입받으므로 시험에서는 가짜 runner 로 바꾼다."""
import re
import subprocess
from dataclasses import dataclass

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\r")


@dataclass(frozen=True)
class CmdResult:
    rc: int
    out: str = ""
    err: str = ""

    @property
    def ok(self) -> bool:
        return self.rc == 0

    @property
    def text(self) -> str:
        return (self.out + ("\n" + self.err if self.err else "")).strip()


def clean(text: str) -> str:
    """터미널 색상 코드와 CR 을 지운다 (bluetoothctl 출력)."""
    return ANSI.sub("", text)


def run(args, timeout: float = 20.0, input_text=None) -> CmdResult:
    """명령을 실행해 결과를 돌려준다. 명령이 없거나 시간이 넘어가도 예외 대신 rc 로 알린다 (127 / 124)."""
    try:
        p = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout, input=input_text,
                           encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return CmdResult(127, "", f"명령을 찾을 수 없습니다: {args[0]}")
    except subprocess.TimeoutExpired:
        return CmdResult(124, "", "시간이 초과되었습니다.")
    except OSError as e:
        return CmdResult(126, "", str(e))
    return CmdResult(p.returncode, clean(p.stdout or ""), clean(p.stderr or ""))
