"""두벌식 한글 조합기. Qt 의존 없음.

사용법: 키(자모)를 feed() 에 넣으면 (지울 글자 수, 넣을 문자열) 을 돌려준다.
입력란에서는 "현재 조합 중인 글자"만 지우고 다시 쓰면 된다.

    c = HangulComposer()
    c.feed("ㅎ")  -> (0, "ㅎ")
    c.feed("ㅏ")  -> (1, "하")
    c.feed("ㄴ")  -> (1, "한")
    c.feed("ㅏ")  -> (1, "하나")   # 받침이 다음 글자 초성으로 넘어감
"""
from typing import Optional

CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"

# 겹모음 / 겹받침 결합표
VOWEL_PAIRS = {
    ("ㅗ", "ㅏ"): "ㅘ", ("ㅗ", "ㅐ"): "ㅙ", ("ㅗ", "ㅣ"): "ㅚ",
    ("ㅜ", "ㅓ"): "ㅝ", ("ㅜ", "ㅔ"): "ㅞ", ("ㅜ", "ㅣ"): "ㅟ", ("ㅡ", "ㅣ"): "ㅢ",
}
JONG_PAIRS = {
    ("ㄱ", "ㅅ"): "ㄳ", ("ㄴ", "ㅈ"): "ㄵ", ("ㄴ", "ㅎ"): "ㄶ", ("ㄹ", "ㄱ"): "ㄺ",
    ("ㄹ", "ㅁ"): "ㄻ", ("ㄹ", "ㅂ"): "ㄼ", ("ㄹ", "ㅅ"): "ㄽ", ("ㄹ", "ㅌ"): "ㄾ",
    ("ㄹ", "ㅍ"): "ㄿ", ("ㄹ", "ㅎ"): "ㅀ", ("ㅂ", "ㅅ"): "ㅄ",
}
JONG_SPLIT = {v: k for k, v in JONG_PAIRS.items()}

JAMO = frozenset(CHO) | frozenset(JUNG)
# 쌍자음·쌍모음은 Shift 로만 입력되므로 JONG 에 없는 것(ㄸㅃㅉ)은 받침이 될 수 없다
_State = tuple  # (초성|None, 중성|None, 종성|" ")


def is_vowel(k: str) -> bool:
    return k in JUNG


def _render(state: _State) -> str:
    c, v, j = state
    if c and v:
        return chr(0xAC00 + (CHO.index(c) * 21 + JUNG.index(v)) * 28 + JONG.index(j))
    return c or v or ""


def _step(state: _State, k: str):
    """상태에 키 k 를 더한다. (확정할 문자열, 새 상태, 새 상태의 키 이력 시작) 을 돌려준다.

    '이력 시작'은 새 글자가 어떤 키로 시작하는지: 받침이 넘어갈 때는 그 받침 키 + k.
    """
    c, v, j = state
    if is_vowel(k):
        if v is None:
            return "", (c, k, " "), None
        if j == " ":
            if (v, k) in VOWEL_PAIRS:
                return "", (c, VOWEL_PAIRS[(v, k)], " "), None
            return _render(state), (None, k, " "), [k]
        # 받침이 있는 글자 뒤 모음: 받침(겹받침이면 뒤쪽)이 다음 글자 초성이 된다
        if j in JONG_SPLIT:
            keep, move = JONG_SPLIT[j]
            return _render((c, v, keep)), (move, k, " "), [move, k]
        return _render((c, v, " ")), (j, k, " "), [j, k]
    # 자음
    if c is None and v is None:
        return "", (k, None, " "), None
    if c is None or v is None:            # 모음 단독 또는 초성 단독 뒤의 자음
        return _render(state), (k, None, " "), [k]
    if j == " ":
        if k in JONG and k != " ":
            return "", (c, v, k), None
        return _render(state), (k, None, " "), [k]
    if (j, k) in JONG_PAIRS:
        return "", (c, v, JONG_PAIRS[(j, k)]), None
    return _render(state), (k, None, " "), [k]


class HangulComposer:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """조합 중인 글자를 확정하고 새로 시작한다 (커서 이동, 비한글 입력 등)."""
        self._state: _State = (None, None, " ")
        self._hist: list = []

    @property
    def composing(self) -> str:
        return _render(self._state)

    def feed(self, k: str) -> tuple:
        """자모 k 입력. (입력란에서 지울 글자 수, 새로 넣을 문자열)"""
        old = _render(self._state)
        commit, self._state, new_hist = _step(self._state, k)
        if new_hist is not None:
            self._hist = new_hist
        else:
            self._hist.append(k)
        return len(old), commit + _render(self._state)

    def backspace(self) -> Optional[tuple]:
        """조합 중인 글자에서 자모 하나를 지운다. 조합 중이 아니면 None (일반 백스페이스 사용)."""
        if not self._hist:
            return None
        old = _render(self._state)
        hist = self._hist[:-1]
        self.reset()
        for k in hist:  # 이력은 한 글자 안의 키뿐이므로 확정(commit) 없이 재생된다
            _, self._state, _ = _step(self._state, k)
            self._hist.append(k)
        return len(old), _render(self._state)
