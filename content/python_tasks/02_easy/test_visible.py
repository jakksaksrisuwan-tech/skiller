from solution import parse_syslog


def test_empty():
    assert parse_syslog("") == {}


def test_single_error():
    out = parse_syslog("Jan 12 09:23:01 host svc[1234]: ERROR: foo\n")
    assert out == {
        "ERROR": [
            {"ts": "Jan 12 09:23:01", "host": "host", "service": "svc",
             "pid": 1234, "msg": "foo"}
        ]
    }


def test_no_pid():
    out = parse_syslog("Jan 12 09:23:02 host svc: WARN: bar")
    assert out["WARN"][0]["pid"] is None
    assert out["WARN"][0]["service"] == "svc"
    assert out["WARN"][0]["msg"] == "bar"


def test_skips_garbage():
    out = parse_syslog("garbage line\nJan 12 09:23:03 h s: INFO: hi\n")
    assert "INFO" in out and len(out["INFO"]) == 1
