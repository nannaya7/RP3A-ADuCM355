import pytest

from comm import protocol as p


# ---- 레코드 파싱 -----------------------------------------------------------
def test_info_record_keeps_commas_in_message():
    r = p.parse_line("#I,000123,INFO,RANGE CH0 RTIA=1000..20000 RETRY=0 SAT=0")
    assert r == p.InfoRecord(123, "INFO", "RANGE CH0 RTIA=1000..20000 RETRY=0 SAT=0")
    r = p.parse_line("#I,000001,ERR,a,b,c")
    assert r.msg == "a,b,c"


def test_timestamp_wider_than_six_digits():
    # %06lu 는 999999ms(16.7분)를 넘으면 자릿수가 늘어난다
    assert p.parse_line("#I,1234567,INFO,x").ts == 1234567


def test_header():
    r = p.parse_line("#H,FW=V.0.03.305,RCAL=1000.0,MODE=SEQ,COLUMNS=TIMESTAMP|CH|FREQ_HZ|STATUS")
    assert r == p.HeaderRecord("V.0.03.305", 1000.0, "SEQ", ("TIMESTAMP", "CH", "FREQ_HZ", "STATUS"))


def test_meas_full():
    r = p.parse_line("#M,000500,CH1,1000.00,-1200,340,1250.50,-15.20,1206.00,-328.00,24.3,41.2,OK")
    assert (r.ch, r.freq_hz, r.status) == (1, 1000.0, "OK")
    assert (r.z_real, r.z_imag) == (-1200, 340)
    assert (r.mag_ohm, r.phase_deg, r.r_ohm, r.x_ohm) == (1250.5, -15.2, 1206.0, -328.0)
    assert (r.temp_c, r.hum_rh) == (24.3, 41.2) and not r.sat


def test_meas_compact_and_raw():
    c = p.parse_line("#M,000500,CH0,10.00,5000.10,-2.50,24.3,41.2,SAT")
    assert c.mag_ohm == 5000.1 and c.z_real is None and c.sat
    r = p.parse_line("#M,000500,CH2,200000.00,-1200,340,OK")
    assert (r.z_real, r.z_imag, r.mag_ohm, r.temp_c) == (-1200, 340, None, None)


def test_meas_nan_and_negative():
    r = p.parse_line("#M,1,CH0,10.00,5,5,nan,-0.00,1.00,-2.00,0.0,0.0,SAT")
    assert r.mag_ohm != r.mag_ohm and r.x_ohm == -2.0


def test_other_records():
    assert p.parse_line("#C,000010,AFE0,1000.0,-1200,340,OK") == p.CalRefRecord(10, 0, 1000.0, -1200, 340, "OK")
    assert p.parse_line("#D,000010,CH2,100.0,1.25,20000.0,OK").ok
    assert not p.parse_line("#D,000010,CH2,100.0,1.25,20000.0,ERR").ok
    t = p.parse_line("#T,000010,CH0,500,0.55,1000.0,SAT")
    assert (t.t_ms, t.sat) == (500, True)
    b = p.parse_line("#B,000010,PT,CH0,3,100.00,110.1234,0.5000")
    assert (b.kind, b.fields[0]) == ("PT", "CH0")


@pytest.mark.parametrize("line", [
    "#M,1,CH0,10.00,OK",                    # 필드 수 부족
    "#M,1,CHX,10.00,5,5,OK",                # 잘못된 채널
    "#M,1,CH0,abc,5,5,OK",                  # 숫자 아님
    "#M,1,CH0,10.00,5,5,MAYBE",             # 잘못된 상태
    "#I,1,DEBUG,x", "#I,xx,INFO,x", "#I,1",
    "#H,FW=1", "#C,1,AFE0", "#T,1,CH0",
])
def test_malformed_known_records_raise(line):
    with pytest.raises(p.ParseError):
        p.parse_line(line)


@pytest.mark.parametrize("line", ["", "hello", "# ", "#", "#X,1,2", "  random text  "])
def test_non_records_return_none(line):
    assert p.parse_line(line) is None


def test_parse_kv_status():
    kv = p.parse_kv("RUN=0 SWEEP=1000.00:1000.00:1 CHMASK=0x7 VERB=FULL SIGNAL=300.0:X0P2:X0P25 RTIA=AUTO")
    assert kv["RUN"] == "0" and kv["CHMASK"] == "0x7" and kv["SWEEP"] == "1000.00:1000.00:1"
    assert p.parse_kv("CAL VALID=1 ENABLED=1 BOARD_ID=UNSET")["BOARD_ID"] == "UNSET"


# ---- 줄 버퍼 -------------------------------------------------------------
def test_line_buffer_handles_cr_lf_crlf_and_split():
    lb = p.LineBuffer()
    assert lb.feed(b"abc") == []
    assert lb.feed(b"def\r\nghi\n") == ["abcdef", "ghi"]
    assert lb.feed(b"jkl\r") == ["jkl"]
    assert lb.feed(b"\n\r\n\r\nmno\r\n") == ["mno"]       # 빈 줄 무시


def test_line_buffer_byte_by_byte():
    lb, out = p.LineBuffer(), []
    for b in b"#I,1,INFO,hi\r\n":
        out += lb.feed(bytes([b]))
    assert out == ["#I,1,INFO,hi"]


def test_line_buffer_overlong_line_dropped_then_recovers():
    lb = p.LineBuffer(max_len=16)
    out = lb.feed(b"x" * 100 + b"\r\n" + b"ok\r\n")
    assert out == ["ok"] and lb.dropped_lines == 1


def test_line_buffer_non_ascii_does_not_raise():
    assert p.LineBuffer().feed(b"a\xffb\r\n") == ["a�b"]


# ---- 명령 생성 -----------------------------------------------------------
def test_command_builders():
    assert p.cmd_sweep(10, 200000, 101) == "SWEEP 10 200000 101"
    assert p.cmd_sweep(0.5, 1e5, 5) == "SWEEP 0.5 100000 5"      # 지수 표기 없음
    assert p.cmd_chan([2, 0, 1, 1]) == "CHAN CH0,CH1,CH2"
    assert p.cmd_verb("full") == "VERB FULL"
    assert p.cmd_start() == "START 1" and p.cmd_start(0) == "START 0"


@pytest.mark.parametrize("fn,args", [
    (p.cmd_chan, ([],)), (p.cmd_chan, ([4],)), (p.cmd_verb, ("LOUD",)), (p.cmd_start, (-1,)),
])
def test_command_builders_reject_bad_input(fn, args):
    with pytest.raises(ValueError):
        fn(*args)


def test_check_cmd_limits():
    assert p.check_cmd("A" * 63)
    for bad in ("A" * 64, "", "A\nB", "한글"):
        with pytest.raises(ValueError):
            p.check_cmd(bad)
