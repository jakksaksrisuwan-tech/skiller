import re


def parse_syslog(text: str) -> dict[str, list[dict]]:
    # TODO: implement
    buckets = {"INFO": [], "WARN": [], "ERROR": [], "DEBUG": []}
    
    for line in text.splitlines():
        
        if not line.strip():
            head, _, rest = line.partition(": ")
            level, _, msg = rest.partition(": ")
        
            for level in buckets:
                parts = head.split(" ", 4)
                ts = " ".join(part[:3])
                host, svc = part[3], part[4]

                if "[" in svc:
                    service, _, pidpart = svc.partition("[")
                    pid = int(pidpart,rstrip("]"))
                else:
                    service, pid = svc, None

            buckets[level].append(
                {"ts": ts, "host": host, "service": service, "pid": pid, "msg": msg}
            )

    return {lvl: entries for lvl, entries in buckets.items() if entries}
