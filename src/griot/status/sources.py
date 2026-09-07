"""Data sources for the right pane. Parsers are pure; fetchers never raise."""
import json
import re
import socket
import subprocess
from dataclasses import dataclass
from datetime import date, datetime

import httpx

WMO = {
    0: ("☀", "Clear"), 1: ("🌤", "Mostly clear"), 2: ("⛅", "Partly cloudy"),
    3: ("☁", "Overcast"), 45: ("🌫", "Fog"), 51: ("🌦", "Drizzle"),
    61: ("🌧", "Rain"), 63: ("🌧", "Rain"), 65: ("🌧", "Heavy rain"),
    71: ("🌨", "Snow"), 80: ("🌦", "Showers"), 95: ("⛈", "Thunderstorm"),
}


@dataclass(frozen=True)
class Status:
    ok: bool
    text: str


def run_cmd(cmd: list[str], timeout: float = 10.0) -> str:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    ).stdout


# --- pure parsers ---

def parse_pmset(out: str) -> Status:
    m = re.search(r"(\d{1,3})%;\s*(\w+)", out)
    if not m:
        return Status(False, "?")
    pct, state = m.group(1), m.group(2)
    icon = "⚡" if state in ("charging", "charged", "finishing") else "↓"
    return Status(True, f"{pct}% {icon}")


def parse_scutil_nc(out: str) -> Status:
    for line in out.splitlines():
        if "(Connected)" in line:
            m = re.search(r'"([^"]+)"', line)
            return Status(True, m.group(1) if m else "connected")
    return Status(False, "down")


def parse_wifi(out: str) -> Status:
    m = re.search(r"^\s*SSID : (.+)$", out, re.MULTILINE)
    if not m or not m.group(1).strip():
        return Status(False, "off")
    ssid = m.group(1).strip()
    # macOS 14+/26 returns "<redacted>" unless the process has Location
    # permission — we're associated, just can't see the name. Show connected.
    if ssid.strip("<>").lower() == "redacted":
        return Status(True, "on")
    return Status(True, ssid)


def parse_open_meteo(data: dict) -> Status:
    try:
        cur = data["current"]
        temp = round(float(cur["temperature_2m"]))
        icon, desc = WMO.get(int(cur["weather_code"]), ("·", ""))
        return Status(True, f"{icon} {temp}°F {desc}".strip())
    except (KeyError, TypeError, ValueError):
        return Status(False, "?")


def _humanize_tokens(n: int) -> str:
    for unit, size in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if n >= size:
            return f"{n / size:.1f}{unit}".replace(".0", "")
    return str(n)


def parse_pmset_detail(out: str) -> dict:
    """Parse `pmset -g batt` into pct / on_ac / status / remaining_min."""
    on_ac = "AC Power" in out
    pct_m = re.search(r"(\d{1,3})%", out)
    status_m = re.search(r"%;\s*(\w+)", out)
    rem_m = re.search(r"(\d+):(\d\d)\s+remaining", out)
    remaining = None
    if rem_m:
        mins = int(rem_m.group(1)) * 60 + int(rem_m.group(2))
        remaining = mins if mins > 0 else None
    return {
        "pct": int(pct_m.group(1)) if pct_m else 0,
        "on_ac": on_ac,
        "status": status_m.group(1) if status_m else "?",
        "remaining_min": remaining,
    }


def battery_estimates(pct: int, on_ac: bool, status: str,
                      remaining_min: int | None) -> dict:
    """Drain rate (%/hr) and ETA-to-10% (min) from pmset's own estimate.
    Only meaningful while discharging with an estimate available."""
    if on_ac or status != "discharging" or not remaining_min or pct <= 0:
        return {"drain_pct_per_hr": None, "eta_10_min": None}
    drain = pct / (remaining_min / 60)
    eta_10 = round(remaining_min * (pct - 10) / pct) if pct > 10 else 0
    return {"drain_pct_per_hr": drain, "eta_10_min": eta_10}


def parse_default_iface(route_out: str) -> str | None:
    m = re.search(r"^\s*interface:\s*(\S+)", route_out, re.MULTILINE)
    return m.group(1) if m else None


def parse_lsof_listen(out: str) -> list[dict]:
    """Parse `lsof -nP -iTCP -sTCP:LISTEN` into deduped {proc, pid, port, addr}."""
    seen: set[tuple[str, int]] = set()
    rows: list[dict] = []
    pat = re.compile(r"^(\S+)\s+(\d+)\s+.*\bTCP\s+(\S+):(\d+)\s+\(LISTEN\)")
    for line in out.splitlines():
        m = pat.match(line)
        if not m:
            continue
        proc, pid, addr, port = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        proc = proc.replace(r"\x20", " ")  # lsof escapes spaces in COMMAND
        key = (proc, port)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"proc": proc, "pid": pid, "port": port, "addr": addr})
    return rows


def parse_ccusage_breakdown(data: dict, month: str) -> dict | None:
    for e in data.get("monthly", []):
        if (e.get("period") or e.get("month")) == month:
            return {
                "total": int(e.get("totalTokens", 0)),
                "input": int(e.get("inputTokens", 0)),
                "output": int(e.get("outputTokens", 0)),
                "cache_read": int(e.get("cacheReadTokens", 0)),
                "cache_create": int(e.get("cacheCreationTokens", 0)),
            }
    return None


def parse_ccusage_tokens(data: dict, month: str) -> Status:
    # Report token VOLUME, not dollars: ccusage's cost is tokens x API
    # list price, which for a subscription hugely overstates actual spend
    # (the logs record no real cost). ccusage keys the month as "period"
    # (older versions used "month").
    for entry in data.get("monthly", []):
        if (entry.get("period") or entry.get("month")) == month:
            return Status(True, f"{_humanize_tokens(int(entry['totalTokens']))} tok")
    return Status(False, "?")


def parse_icalbuddy(out: str) -> list[str]:
    return [
        line.removeprefix("• ").strip()
        for line in out.splitlines()
        if line.strip()
    ]


_DAY_MINUTES = 24 * 60
_HALF_DAY_MINUTES = _DAY_MINUTES // 2


def next_event_minutes(events: list[str], now: datetime) -> int | None:
    """Minutes until the first upcoming HH:MM-prefixed event, else None.

    An HH:MM with no date is ambiguous, so it resolves to whichever day puts it
    nearest to `now` — at 23:58 a 00:01 standup is three minutes away, not 1437
    minutes into the past. Pinning it to today made the pane go quiet for the
    last quarter-hour of every day.
    """
    best: int | None = None
    for e in events:
        m = re.match(r"(\d{2}):(\d{2})", e)
        if not m:
            continue
        start = now.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                            second=0, microsecond=0)
        delta = int((start - now).total_seconds() // 60)
        if delta < -_HALF_DAY_MINUTES:
            delta += _DAY_MINUTES        # long past on the clock: it is tomorrow's
        elif delta > _HALF_DAY_MINUTES:
            delta -= _DAY_MINUTES        # far ahead: it was last night's, and is gone
        if delta >= 0 and (best is None or delta < best):
            best = delta
    return best


# --- effectful fetchers (never raise) ---

def battery() -> Status:
    try:
        return parse_pmset(run_cmd(["pmset", "-g", "batt"]))
    except Exception:
        return Status(False, "?")


def vpn() -> Status:
    try:
        return parse_scutil_nc(run_cmd(["scutil", "--nc", "list"]))
    except Exception:
        return Status(False, "?")


def wifi() -> Status:
    try:
        return parse_wifi(run_cmd(["ipconfig", "getsummary", "en0"]))
    except Exception:
        return Status(False, "?")


def redis_tunnel(port: int = 36379) -> Status:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2.0):
            return Status(True, "up")
    except Exception:
        return Status(False, "down")


def weather(lat: float, lon: float) -> Status:
    try:
        r = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,weather_code",
                "temperature_unit": "fahrenheit",
            },
            timeout=10.0,
        )
        return parse_open_meteo(r.json())
    except Exception:
        return Status(False, "?")


def calendar_events() -> list[str]:
    try:
        out = run_cmd([
            "icalBuddy",
            "-n", "-nc", "-npn",           # no calendar name / colors / property-name labels
            "-b", "• ",                     # bullet marker parse_icalbuddy strips
            "-li", "5",                     # cap at 5 upcoming items
            "-iep", "datetime,title",       # only these two properties - no extra detail lines
            "-po", "datetime,title",        # datetime BEFORE title merges both onto one line
            "-ps", " ",                     # single-space separator -> "HH:MM[ - HH:MM] Title"
            "-tf", "%H:%M",                 # 24h zero-padded, matches next_event_minutes regex
            "-df", "",                      # suppress date component before the time
            "eventsToday+1",
        ], timeout=15.0)
        return parse_icalbuddy(out)
    except Exception:
        return []


def claude_usage() -> Status:
    """Month-to-date Claude token volume (not dollars — see parse_ccusage_tokens)."""
    try:
        out = run_cmd(["npx", "-y", "ccusage@latest", "monthly", "--json"], timeout=120.0)
        return parse_ccusage_tokens(json.loads(out), date.today().strftime("%Y-%m"))
    except Exception:
        return Status(False, "?")


def claude_usage_breakdown() -> dict | None:
    """MTD token breakdown (total/in/out/cache) or None on failure."""
    try:
        out = run_cmd(["npx", "-y", "ccusage@latest", "monthly", "--json"], timeout=120.0)
        return parse_ccusage_breakdown(json.loads(out), date.today().strftime("%Y-%m"))
    except Exception:
        return None


# Common macOS daemons we push to the bottom of the port list (not dev-relevant).
_SYSTEM_PROCS = {
    "rapportd", "sharingd", "ControlCe", "launchd", "remoted", "identityservicesd",
    "sshd-keygen-wrapper", "netbiosd", "AirPlayXPCHelper",
}


def notify(title: str, message: str) -> None:
    """Fire a macOS notification via osascript; never raises."""
    try:
        run_cmd([
            "osascript", "-e",
            f"display notification {json.dumps(message)} with title {json.dumps(title)}",
        ], timeout=5.0)
    except Exception:
        pass


def battery_detail() -> dict:
    """pmset detail + drain/ETA estimates; never raises."""
    try:
        d = parse_pmset_detail(run_cmd(["pmset", "-g", "batt"]))
        d.update(battery_estimates(d["pct"], d["on_ac"], d["status"], d["remaining_min"]))
        d["ok"] = True
        return d
    except Exception:
        return {"ok": False}


def parse_inet_addr(ifconfig_out: str) -> str | None:
    m = re.search(r"^\s*inet (\d+\.\d+\.\d+\.\d+)", ifconfig_out, re.MULTILINE)
    return m.group(1) if m else None


def _primary_ip() -> str | None:
    # ifconfig (not `ipconfig getifaddr`) so VPN/utun default interfaces resolve.
    try:
        iface = parse_default_iface(run_cmd(["route", "-n", "get", "default"]))
        if not iface:
            return None
        return parse_inet_addr(run_cmd(["ifconfig", iface]))
    except Exception:
        return None


def network_detail(max_ports: int = 6) -> dict:
    """Assemble the Network section: ip, wifi, vpn, listening ports, ssh tunnels."""
    result = {"ok": False, "ip": None, "wifi": Status(False, "?"),
              "vpn": Status(False, "?"), "ports": [], "tunnels": []}
    try:
        result["ip"] = _primary_ip()
        result["wifi"] = parse_wifi(run_cmd(["ipconfig", "getsummary", "en0"]))
        result["vpn"] = parse_scutil_nc(run_cmd(["scutil", "--nc", "list"]))
        listeners = parse_lsof_listen(
            run_cmd(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], timeout=8.0)
        )
        result["tunnels"] = sorted(
            (r for r in listeners if r["proc"] == "ssh"), key=lambda r: r["port"]
        )
        # dev-relevant first (non-system procs), then by port; cap for display
        ranked = sorted(
            listeners,
            key=lambda r: (r["proc"] in _SYSTEM_PROCS, r["port"]),
        )
        result["ports"] = ranked[:max_ports]
        result["ok"] = True
    except Exception:
        pass
    return result
