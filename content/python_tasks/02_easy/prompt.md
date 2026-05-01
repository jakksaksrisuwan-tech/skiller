# Easy — parse_syslog

Suggested time: 30 minutes.

## Task
Parse a multi-line syslog string. Each line looks like:

```
Jan 12 09:23:01 host service[1234]: ERROR: connection refused
Jan 12 09:23:02 host service: WARN: retry in 5s
```

Implement `parse_syslog(text: str) -> dict[str, list[dict]]` that returns a
mapping from log **level** to a list of parsed entries.

Each entry is a dict with these keys:

- `ts`     — full timestamp string (e.g. `"Jan 12 09:23:01"`)
- `host`   — hostname
- `service` — service name (without `[pid]`)
- `pid`    — int or `None` if no `[pid]` block
- `msg`    — message after the level

Levels to recognize: `INFO`, `WARN`, `ERROR`, `DEBUG`. Lines that don't match
the expected shape, or whose level isn't recognized, are **skipped silently**.

## Example
```python
text = (
    "Jan 12 09:23:01 host svc[1234]: ERROR: foo\n"
    "Jan 12 09:23:02 host svc: WARN: bar\n"
    "garbage line\n"
)
parse_syslog(text) == {
    "ERROR": [{"ts": "Jan 12 09:23:01", "host": "host", "service": "svc",
               "pid": 1234, "msg": "foo"}],
    "WARN":  [{"ts": "Jan 12 09:23:02", "host": "host", "service": "svc",
               "pid": None, "msg": "bar"}],
}
```

Empty input returns `{}`. Levels with no entries are not present in the result.

Hidden tests cover edge cases: blank lines, mixed levels, weird whitespace.
