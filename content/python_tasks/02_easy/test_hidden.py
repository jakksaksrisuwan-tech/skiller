from solution import parse_syslog


def test_blank_lines_skipped():
    text = "\n\nJan 1 00:00:00 h s: INFO: x\n\n\n"
    out = parse_syslog(text)
    assert out == {
        "INFO": [
            {"ts": "Jan 1 00:00:00", "host": "h", "service": "s",
             "pid": None, "msg": "x"}
        ]
    }


def test_unknown_level_skipped():
    out = parse_syslog("Jan 1 00:00:00 h s: TRACE: noisy\n")
    assert out == {}


def test_multiple_levels_preserve_order():
    text = (
        "Jan 1 00:00:00 h s: INFO: one\n"
        "Jan 1 00:00:01 h s: ERROR: two\n"
        "Jan 1 00:00:02 h s: INFO: three\n"
    )
    out = parse_syslog(text)
    assert [e["msg"] for e in out["INFO"]] == ["one", "three"]
    assert out["ERROR"][0]["msg"] == "two"


def test_message_with_colon():
    out = parse_syslog("Jan 1 00:00:00 h s[7]: ERROR: foo: bar: baz\n")
    assert out["ERROR"][0]["msg"] == "foo: bar: baz"


def test_double_digit_pid():
    out = parse_syslog("Jan 1 00:00:00 h kernel[99999]: DEBUG: ok\n")
    assert out["DEBUG"][0]["pid"] == 99999


def test_returns_no_empty_levels():
    out = parse_syslog("Jan 1 00:00:00 h s: ERROR: x\n")
    assert "INFO" not in out
    assert "WARN" not in out
    assert "DEBUG" not in out
