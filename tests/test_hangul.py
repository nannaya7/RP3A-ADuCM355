import pytest

from ui.hangul import HangulComposer


def type_text(keys: str) -> str:
    """입력란을 흉내 내서 feed/backspace 결과를 적용한다."""
    c, out = HangulComposer(), ""
    for k in keys:
        n, text = c.feed(k)
        out = out[:len(out) - n] + text
    return out


@pytest.mark.parametrize("keys,expected", [
    ("ㅎㅏㄴㄱㅡㄹ", "한글"),
    ("ㄱㅏㄴㅏ", "가나"),            # 받침이 다음 초성으로 이동
    ("ㅇㅏㄴㄴㅕㅇ", "안녕"),
    ("ㅎㅏㄱㄱㅛ", "학교"),
    ("ㄱㅏㅂㅅ", "값"),               # 겹받침
    ("ㄱㅏㅂㅅㅣ", "갑시"),          # 겹받침 분리: 뒤쪽이 다음 초성으로
    ("ㄱㅏㅂㅅㅇㅣ", "값이"),
    ("ㅎㅗㅏㅈㅏㅇ", "화장"),         # 겹모음
    ("ㅇㅢㅅㅏ", "의사"),
    ("ㅁㅜㅓㅇㅑ", "뭐야"),
    ("ㅇㅏㄹㄱㅏ", "알가"),           # ㄹ 받침 뒤 모음: ㄹ+ㄱ 이 아니라 ㄹ 유지, ㄱ 이동
    ("ㄱㅏㄸㅏ", "가따"),            # ㄸ 은 받침 불가 → 다음 글자 초성
    ("ㅏㅏ", "ㅏㅏ"),                # 모음 단독
    ("ㄱㄴ", "ㄱㄴ"),                # 자음 단독
    ("ㅇㅏㅁㅏ", "아마"),
])
def test_compose(keys, expected):
    assert type_text(keys) == expected


def test_backspace_jamo_level():
    c = HangulComposer()
    for k in "ㅎㅏㄴ":
        c.feed(k)
    assert c.backspace() == (1, "하")
    assert c.backspace() == (1, "ㅎ")
    assert c.backspace() == (1, "")
    assert c.backspace() is None  # 조합 중 아님 → 일반 백스페이스


def test_backspace_after_split():
    c = HangulComposer()
    out = ""
    for k in "ㄱㅏㄴㅏ":
        n, t = c.feed(k)
        out = out[:len(out) - n] + t
    assert out == "가나"
    n, t = c.backspace()     # 나 → ㄴ
    out = out[:len(out) - n] + t
    assert out == "가ㄴ"
    n, t = c.backspace()     # ㄴ 제거
    out = out[:len(out) - n] + t
    assert out == "가"


def test_compound_final_backspace_restores_single():
    c = HangulComposer()
    for k in "ㄱㅏㅂㅅ":
        c.feed(k)
    assert c.backspace() == (1, "갑")


def test_reset_commits():
    c = HangulComposer()
    c.feed("ㅎ"); c.feed("ㅏ")
    c.reset()
    assert c.feed("ㄴ") == (0, "ㄴ")
