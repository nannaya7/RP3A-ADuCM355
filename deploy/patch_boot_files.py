#!/usr/bin/env python3
"""부팅 설정 파일(cmdline.txt, config.txt)을 안전하게 고친다. 표준 라이브러리만 사용.

- cmdline.txt 는 **반드시 한 줄**이어야 한다. 여러 줄이면 아무것도 쓰지 않고 중단한다.
- 같은 명령을 여러 번 실행해도 결과가 같다(멱등). 기존 항목의 순서는 바꾸지 않는다.
- 쓰기 전 원본은 호출하는 셸 스크립트(install_splash.sh, pi_setup.sh)가 백업한다. --dry-run 은 변경 내용만 보여 준다.

    # 스플래시(무지개 화면 끄기, quiet splash logo.nologo …)
    python3 patch_boot_files.py --cmdline /boot/firmware/cmdline.txt --config /boot/firmware/config.txt
    # 스플래시는 건드리지 않고 임의 줄/항목만 추가
    python3 patch_boot_files.py --cmdline ... --config ... --no-splash --config-line enable_uart=1 --cmdline-token video=HDMI-A-1:d
"""
import argparse
import re
import sys
from pathlib import Path

# 값 없이 있기만 하면 되는 항목
FLAG_TOKENS = ("quiet", "splash", "plymouth.ignore-serial-consoles", "logo.nologo")
# key=value 항목: 같은 key 가 이미 있으면 값을 바꾼다
VALUE_TOKENS = {"loglevel": "3", "vt.global_cursor_default": "0"}
# 값을 덮어써도 되는 key. 그 밖의 key=value (예: video=HDMI-A-1:d, video=DSI-1:…, console=…)는 여러 번 나올 수 있으므로
# 똑같은 항목이 없을 때만 덧붙이고 기존 항목은 건드리지 않는다.
REPLACEABLE_KEYS = frozenset(VALUE_TOKENS)


def patch_cmdline(text: str, splash: bool = True, extra_tokens=()) -> str:
    """cmdline.txt 내용에 항목을 더한다. 한 줄이 아니면 ValueError.

    splash=True 이면 스플래시용 항목(quiet splash logo.nologo …)을 더하고, extra_tokens 는 없을 때만 덧붙인다
    (`key=value` 항목은 같은 key 가 있으면 값을 바꾼다).
    """
    body = text.rstrip("\r\n")
    if not body.strip():
        raise ValueError("cmdline.txt 가 비어 있습니다")
    if "\n" in body or "\r" in body:
        raise ValueError("cmdline.txt 는 한 줄이어야 하는데 여러 줄입니다 — 수정하지 않습니다")
    tokens = body.split()

    def ensure(token: str) -> None:
        key = token.split("=", 1)[0]
        if "=" in token and key in REPLACEABLE_KEYS:
            idx = [i for i, t in enumerate(tokens) if t.split("=", 1)[0] == key]
            if idx:
                for i in idx:
                    tokens[i] = token
            else:
                tokens.append(token)
        elif token not in tokens:
            tokens.append(token)

    if splash:
        for flag in FLAG_TOKENS:
            ensure(flag)
        for key, value in VALUE_TOKENS.items():
            ensure(f"{key}={value}")
    for tok in extra_tokens:
        if not tok or any(c.isspace() for c in tok):
            raise ValueError(f"cmdline 항목이 비어 있거나 공백이 있습니다: {tok!r}")
        ensure(tok)
    return " ".join(tokens) + "\n"


def patch_config(text: str, splash: bool = True, extra_lines=()) -> str:
    """config.txt 를 고친다.

    splash=True 이면 disable_splash=1 (무지개 화면 끄기)을 보장한다. 이미 있으면 값만 1로 맞춘다.
    extra_lines 는 **똑같은 줄이 없을 때만** 맨 끝([all] 섹션)에 덧붙인다 (예: enable_uart=1, dtoverlay=...).
    """
    lines = text.splitlines()
    want = []
    if splash:
        found = False                                  # 모든 모델에 적용되는 자리([all] 또는 섹션 표시 앞)에 있는가
        section = ""
        for i, line in enumerate(lines):
            m = re.match(r"\s*\[(.*)\]\s*$", line)
            if m:
                section = m.group(1).strip().lower()
            elif re.match(r"\s*disable_splash\s*=", line):
                lines[i] = "disable_splash=1"
                if section in ("", "all"):
                    found = True                       # [cm5] 같은 특정 모델 섹션 안의 줄은 이 Pi 에 적용되지 않을 수 있다
        if not found:
            want.append("disable_splash=1")
    present = {ln.strip() for ln in lines}
    for ln in extra_lines:
        ln = ln.strip()
        if not ln or "\n" in ln or "\r" in ln:
            raise ValueError(f"config.txt 에 넣을 줄이 올바르지 않습니다: {ln!r}")
        if ln not in present and ln not in want:
            want.append(ln)
    out = "\n".join(lines) + ("\n" if lines else "")
    if not want:
        return out
    sections = [ln.strip() for ln in lines if re.match(r"\s*\[.*\]\s*$", ln)]
    if sections and sections[-1].lower() != "[all]":
        out += "\n[all]\n"                       # 마지막 섹션이 특정 모델용이면 모든 모델에 적용되도록 [all] 로 되돌린다
    return out + "\n".join(want) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cmdline", required=True, type=Path)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-splash", action="store_true",
                    help="스플래시용 항목(disable_splash, quiet splash …)은 건드리지 않는다")
    ap.add_argument("--config-line", action="append", default=[], metavar="LINE",
                    help="config.txt 에 없으면 덧붙일 줄 (여러 번 가능)")
    ap.add_argument("--cmdline-token", action="append", default=[], metavar="TOKEN",
                    help="cmdline.txt 에 없으면 덧붙일 항목 (여러 번 가능)")
    a = ap.parse_args(argv)

    try:
        old_cmd = a.cmdline.read_text(encoding="utf-8")
        old_cfg = a.config.read_text(encoding="utf-8")
        new_cmd = patch_cmdline(old_cmd, splash=not a.no_splash, extra_tokens=a.cmdline_token)
        new_cfg = patch_config(old_cfg, splash=not a.no_splash, extra_lines=a.config_line)
    except (OSError, ValueError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1

    print(f"cmdline.txt 이전: {old_cmd.strip()}")
    print(f"cmdline.txt 이후: {new_cmd.strip()}")
    if new_cfg == old_cfg:
        print("config.txt: 변경 없음")
    else:
        old_lines = set(old_cfg.splitlines())
        added = [ln for ln in new_cfg.splitlines() if ln.strip() and ln not in old_lines]
        print("config.txt: 변경됨 → " + (", ".join(added) if added else "값 수정"))
    if a.dry_run:
        print("(dry-run: 파일을 쓰지 않았습니다)")
        return 0
    a.cmdline.write_text(new_cmd, encoding="utf-8", newline="\n")
    a.config.write_text(new_cfg, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
