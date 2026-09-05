from griot.status.sources import (
    Status,
    parse_ccusage_tokens,
    parse_icalbuddy,
    parse_open_meteo,
    parse_pmset,
    parse_scutil_nc,
    parse_wifi,
    redis_tunnel,
)

PMSET = """Now drawing from 'Battery Power'
 -InternalBattery-0 (id=12345)\t84%; discharging; 4:11 remaining present: true
"""

PMSET_AC = """Now drawing from 'AC Power'
 -InternalBattery-0 (id=12345)\t100%; charged; 0:00 remaining present: true
"""

SCUTIL_CONNECTED = """Available network connection services in the current set (*=enabled):
* (Connected)      F742733E VPN (com.nordvpn.macos.teams) "Corp VPN" [VPN]
* (Disconnected)   05792884 VPN (com.nordvpn.macos.teams) "Home VPN" [VPN]
"""

SCUTIL_DOWN = SCUTIL_CONNECTED.replace("(Connected)", "(Disconnected)")

WIFI_SUMMARY = """<dictionary> {
  BSSID : redacted
  SSID : HomeNet-5G
  Security : WPA2 Personal
}
"""


def test_parse_pmset_battery():
    s = parse_pmset(PMSET)
    assert s == Status(True, "84% ↓")


def test_parse_pmset_ac():
    assert parse_pmset(PMSET_AC) == Status(True, "100% ⚡")


def test_parse_pmset_garbage():
    assert parse_pmset("nonsense").ok is False


def test_parse_scutil_connected():
    s = parse_scutil_nc(SCUTIL_CONNECTED)
    assert s.ok and "Corp VPN" in s.text


def test_parse_scutil_disconnected():
    s = parse_scutil_nc(SCUTIL_DOWN)
    assert not s.ok and s.text == "down"


def test_parse_wifi_ssid():
    assert parse_wifi(WIFI_SUMMARY) == Status(True, "HomeNet-5G")


def test_parse_wifi_no_ssid():
    assert parse_wifi("<dictionary> { }").ok is False


def test_parse_wifi_redacted_shows_connected():
    # macOS 14+/26 returns "SSID : <redacted>" without Location permission —
    # show connected rather than the literal redacted string.
    out = "<dictionary> {\n  SSID : <redacted>\n}\n"
    assert parse_wifi(out) == Status(True, "on")


def test_parse_open_meteo():
    data = {"current": {"temperature_2m": 72.3, "weather_code": 0}}
    s = parse_open_meteo(data)
    assert s.ok and s.text == "☀ 72°F Clear"


def test_parse_open_meteo_unknown_code():
    data = {"current": {"temperature_2m": 50.0, "weather_code": 999}}
    s = parse_open_meteo(data)
    assert s.ok and "50°F" in s.text


def test_parse_ccusage_tokens_current_month():
    # ccusage keys the month as "period"; we report token volume, not $
    data = {"monthly": [
        {"period": "2026-08", "totalTokens": 5_000_000},
        {"period": "2026-09", "totalTokens": 890_115_931},
    ]}
    assert parse_ccusage_tokens(data, "2026-09") == Status(True, "890.1M tok")


def test_parse_ccusage_tokens_legacy_month_key():
    data = {"monthly": [{"month": "2026-09", "totalTokens": 1_500_000}]}
    assert parse_ccusage_tokens(data, "2026-09") == Status(True, "1.5M tok")


def test_parse_ccusage_tokens_thousands_and_billions():
    assert parse_ccusage_tokens(
        {"monthly": [{"period": "2026-09", "totalTokens": 47_200}]}, "2026-09"
    ) == Status(True, "47.2K tok")
    assert parse_ccusage_tokens(
        {"monthly": [{"period": "2026-09", "totalTokens": 2_300_000_000}]}, "2026-09"
    ) == Status(True, "2.3B tok")


def test_parse_ccusage_tokens_month_missing():
    assert parse_ccusage_tokens({"monthly": []}, "2026-09").ok is False


def test_parse_icalbuddy_single_line_per_event():
    # Realistic output for the -po "datetime,title" / -ps " " / -npn flag
    # set: each event is ONE bullet line, "HH:MM[ - HH:MM] Title". This is
    # the shape both next_event_minutes and the panel's events[0] dedup
    # key rely on operating over the same strings.
    out = (
        "• 15:00 - 15:30 API cache sync\n"
        "• 16:00 QA guild standup\n"
    )
    assert parse_icalbuddy(out) == [
        "15:00 - 15:30 API cache sync",
        "16:00 QA guild standup",
    ]


def test_parse_icalbuddy_all_day_event_title_only():
    # An all-day event has no datetime value to merge onto the bullet
    # line, so icalBuddy emits the title alone. It must pass through
    # intact, and next_event_minutes simply ignores it (no HH:MM prefix).
    out = "• 15:00 API cache sync\n• Company holiday\n"
    assert parse_icalbuddy(out) == ["15:00 API cache sync", "Company holiday"]


def test_parse_icalbuddy_regression_double_bullet():
    # Regression: lstrip("• ") strips character SET, not prefix
    # removeprefix("• ") must be used to preserve real leading bullets
    out = "• • starts with bullet\n"
    assert parse_icalbuddy(out) == ["• starts with bullet"]


def test_parse_icalbuddy_legacy_two_line_per_event_handled_sanely():
    # Older/alternate icalBuddy invocations emit the title on its own
    # bullet line and the datetime indented on the following line. Even
    # in that legacy shape, parse_icalbuddy must not crash: title-only
    # lines pass through untouched, and time lines still lead with HH:MM
    # so next_event_minutes can match them against the same strings the
    # panel dedups on.
    out = (
        "• API cache sync\n"
        "    15:00 - 15:30\n"
        "• QA guild\n"
        "    16:00 - 17:00\n"
    )
    assert parse_icalbuddy(out) == [
        "API cache sync",
        "15:00 - 15:30",
        "QA guild",
        "16:00 - 17:00",
    ]


def test_next_event_minutes():
    from datetime import datetime

    from griot.status.sources import next_event_minutes

    now = datetime(2026, 9, 5, 14, 50)
    events = ["15:00 - 15:30 API cache sync", "16:00 - 17:00 QA guild"]
    assert next_event_minutes(events, now) == 10
    assert next_event_minutes(["09:00 - 09:30 past"], now) is None
    assert next_event_minutes(["tomorrow at 09:00 offsite"], now) is None
    assert next_event_minutes([], now) is None


def test_redis_tunnel_down_returns_status():
    # port 1 is never listening; must not raise
    s = redis_tunnel(port=1)
    assert s == Status(False, "down")


# --- battery detail ---
from griot.status.sources import (  # noqa: E402
    battery_estimates,
    parse_default_iface,
    parse_lsof_listen,
    parse_pmset_detail,
    parse_ccusage_breakdown,
)

PMSET_DISCHARGING = """Now drawing from 'Battery Power'
 -InternalBattery-0 (id=12345)\t84%; discharging; 4:00 remaining present: true
"""
PMSET_CHARGING = """Now drawing from 'AC Power'
 -InternalBattery-0 (id=12345)\t60%; charging; 1:30 remaining present: true
"""
PMSET_NO_EST = """Now drawing from 'Battery Power'
 -InternalBattery-0 (id=12345)\t77%; discharging; (no estimate) present: true
"""


def test_parse_pmset_detail_discharging():
    d = parse_pmset_detail(PMSET_DISCHARGING)
    assert d == {"pct": 84, "on_ac": False, "status": "discharging", "remaining_min": 240}


def test_parse_pmset_detail_charging():
    d = parse_pmset_detail(PMSET_CHARGING)
    assert d["on_ac"] is True and d["status"] == "charging" and d["remaining_min"] == 90


def test_parse_pmset_detail_no_estimate():
    d = parse_pmset_detail(PMSET_NO_EST)
    assert d["pct"] == 77 and d["remaining_min"] is None


def test_battery_estimates_discharging():
    # 84% draining to empty in 240 min -> rate 21%/hr; to 10% = 240*(74/84)=211 min
    e = battery_estimates(pct=84, on_ac=False, status="discharging", remaining_min=240)
    assert round(e["drain_pct_per_hr"]) == 21
    assert e["eta_10_min"] == round(240 * (84 - 10) / 84)


def test_battery_estimates_charging_has_no_drain():
    e = battery_estimates(pct=60, on_ac=True, status="charging", remaining_min=90)
    assert e["drain_pct_per_hr"] is None and e["eta_10_min"] is None


def test_battery_estimates_below_10_is_zero():
    e = battery_estimates(pct=8, on_ac=False, status="discharging", remaining_min=20)
    assert e["eta_10_min"] == 0


# --- network: default iface, listeners, tunnels ---
ROUTE_OUT = """   route to: default
destination: default
       mask: default
    gateway: 192.168.1.1
  interface: en0
      flags: <UP,GATEWAY,DONE,STATIC,PRCLONING>
"""

LSOF_OUT = """COMMAND     PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
node      12345 john   23u  IPv4  0x1      0t0  TCP *:3000 (LISTEN)
com.docke  3456 john   17u  IPv4  0x2      0t0  TCP *:8080 (LISTEN)
ssh       23456 john    5u  IPv4  0x3      0t0  TCP 127.0.0.1:36379 (LISTEN)
ssh       23457 john    6u  IPv4  0x4      0t0  TCP 127.0.0.1:36380 (LISTEN)
rapportd    987 john    8u  IPv4  0x5      0t0  TCP *:52111 (LISTEN)
node      12345 john   24u  IPv6  0x6      0t0  TCP *:3000 (LISTEN)
"""


def test_parse_default_iface():
    assert parse_default_iface(ROUTE_OUT) == "en0"
    assert parse_default_iface("no interface here") is None


def test_parse_lsof_listen_dedup_and_ports():
    rows = parse_lsof_listen(LSOF_OUT)
    pairs = {(r["proc"], r["port"]) for r in rows}
    # node:3000 deduped across IPv4/IPv6
    assert ("node", 3000) in pairs
    assert ("com.docke", 8080) in pairs
    assert ("ssh", 36379) in pairs and ("ssh", 36380) in pairs
    assert sum(1 for r in rows if r["proc"] == "node" and r["port"] == 3000) == 1


def test_parse_lsof_listen_tunnels_are_ssh():
    rows = parse_lsof_listen(LSOF_OUT)
    tunnels = sorted(r["port"] for r in rows if r["proc"] == "ssh")
    assert tunnels == [36379, 36380]


# --- claude usage breakdown ---
def test_parse_ccusage_breakdown():
    data = {"monthly": [{
        "period": "2026-09", "totalTokens": 898_582_515,
        "inputTokens": 10_229, "outputTokens": 3_334_364,
        "cacheReadTokens": 820_448_560, "cacheCreationTokens": 74_789_362,
    }]}
    b = parse_ccusage_breakdown(data, "2026-09")
    assert b["total"] == 898_582_515 and b["cache_read"] == 820_448_560
    assert b["output"] == 3_334_364 and b["input"] == 10_229


def test_parse_ccusage_breakdown_missing():
    assert parse_ccusage_breakdown({"monthly": []}, "2026-09") is None


def test_parse_inet_addr():
    from griot.status.sources import parse_inet_addr
    out = "utun8: flags=8051\n\tinet 10.6.12.2 --> 10.6.12.2 netmask 0xffffffff\n"
    assert parse_inet_addr(out) == "10.6.12.2"
    assert parse_inet_addr("no inet here") is None


def test_parse_lsof_unescapes_spaces():
    out = ('COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n'
           'Code\\x20H 1 john 1u IPv4 0x1 0t0 TCP *:43045 (LISTEN)\n')
    rows = parse_lsof_listen(out)
    assert rows[0]["proc"] == "Code H"
