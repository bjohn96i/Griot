"""griot-status: the right pane. Beads, clock, weather, calendar, statuses, spend."""
from datetime import datetime
from typing import Callable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static

from griot import theme
from griot.config import Config, load_config
from griot.status import sources
from griot.status.beads import Beads


class PolledStatus(Static):
    class Changed(Message):
        pass

    def __init__(self, label: str, fetch: Callable[[], sources.Status],
                 interval: float, id: str | None = None) -> None:
        super().__init__("…", id=id, classes="panel")
        self.label = label
        self.fetch = fetch
        self.interval = interval
        self.last_good: sources.Status | None = None
        self.last_ok: bool | None = None

    def on_mount(self) -> None:
        self.refresh_now()
        self.set_interval(self.interval, self.refresh_now)

    def refresh_now(self) -> None:
        self.run_worker(self._work, thread=True, exclusive=True, group=str(self.id))

    def _work(self) -> None:
        result = self.fetch()
        self.app.call_from_thread(self._apply, result)

    def _apply(self, result: sources.Status) -> None:
        if self.last_ok is not None and result.ok != self.last_ok:
            self.post_message(self.Changed())
        self.last_ok = result.ok
        if result.ok:
            self.last_good = result
            style = theme.OK
            body = result.text
        elif self.last_good:
            style = theme.MUTED
            body = f"{self.last_good.text} ◌"
        else:
            style = theme.ERR
            body = f"{result.text} ◌"
        self.update(Text.assemble((f"{self.label} ", theme.MUTED), (body, style)))


class ClockLine(Static):
    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)
        self._tick()

    def _tick(self) -> None:
        now = datetime.now()
        self.update(Text(now.strftime("%a %b %d  %H:%M:%S"),
                         style=theme.GOLD_BRIGHT, justify="center"))


class CalendarPanel(Static):
    def __init__(self, fetch: Callable[[], list[str]] = sources.calendar_events,
                 **kwargs) -> None:
        super().__init__("…", **kwargs)
        self.fetch = fetch
        self._alerted_event: str | None = None
        self._notified_event: str | None = None

    def on_mount(self) -> None:
        self.refresh_now()
        self.set_interval(60.0, self.refresh_now)

    def refresh_now(self) -> None:
        self.run_worker(self._work, thread=True, exclusive=True, group="cal")

    def _work(self) -> None:
        events = self.fetch()
        self.app.call_from_thread(self._apply, events)

    def _apply(self, events: list[str]) -> None:
        # Spec: beads accelerate when a meeting is < 15 minutes away (once per event).
        minutes = sources.next_event_minutes(events, datetime.now())
        if minutes is not None and minutes < 15:
            upcoming = events[0]
            if upcoming != self._alerted_event:
                self._alerted_event = upcoming
                self.post_message(PolledStatus.Changed())
        # A macOS notification (not just beads) when a meeting is < 5 min out.
        if minutes is not None and minutes < 5:
            upcoming = events[0]
            if upcoming != self._notified_event:
                self._notified_event = upcoming
                self.app.notifier("Griot · meeting soon", upcoming)
        if not events:
            self.update(Text("no events", style=theme.MUTED))
            return
        text = Text()
        for e in events[:5]:
            text.append("▸ ", style=theme.GOLD)
            text.append(e[:34] + "\n", style=theme.TEXT)
        self.update(text)


def _fmt_hm(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _htok(n: int) -> str:
    return sources._humanize_tokens(int(n))


def _row(t: Text, label: str, value: str, value_style: str = theme.TEXT,
         last: bool = False) -> None:
    """Append one stacked ' label   value' line (label padded for alignment)."""
    t.append(f" {label:<8}", style=theme.MUTED)
    t.append(value + ("" if last else "\n"), style=value_style)


class _PanelBase(Static):
    """Section widget: polls a dict-returning fetcher off-thread, keeps the
    last good result, and renders via _render(). Terse, multi-line."""
    interval = 30.0
    group = "panel"

    def __init__(self, fetch: Callable[[], object], **kwargs) -> None:
        super().__init__("…", classes="panel", **kwargs)
        self.fetch = fetch
        self.last = None

    def on_mount(self) -> None:
        self.refresh_now()
        self.set_interval(self.interval, self.refresh_now)

    def refresh_now(self) -> None:
        self.run_worker(self._work, thread=True, exclusive=True, group=self.group)

    def _work(self) -> None:
        data = self.fetch()
        self.app.call_from_thread(self._apply, data)

    def _apply(self, data) -> None:
        raise NotImplementedError


class BatteryPanel(_PanelBase):
    interval = 30.0
    group = "battery"

    def _apply(self, d: dict) -> None:
        if not d or not d.get("ok"):
            if self.last is None:
                self.update(Text.assemble(("⚡ BATTERY\n", f"bold {theme.GOLD}"),
                                          (" ?", theme.MUTED)))
            return
        self.last = d
        if d["status"] == "charging":
            source = "charging"
        elif d["on_ac"]:
            source = "AC"
        else:
            source = "battery"
        t = Text()
        t.append("⚡ BATTERY\n", style=f"bold {theme.GOLD}")
        _row(t, "charge", f"{d['pct']}%",
             value_style=theme.ERR if d["pct"] <= 10 else theme.TEXT)
        _row(t, "source", source)
        if d.get("drain_pct_per_hr") is not None:
            _row(t, "drain", f"{d['drain_pct_per_hr']:.0f}%/hr")
            _row(t, "→10%", _fmt_hm(d["eta_10_min"]), last=True)
        elif d["status"] == "charging" and d.get("remaining_min"):
            _row(t, "→full", _fmt_hm(d["remaining_min"]), last=True)
        else:
            _row(t, "drain", "estimating…", value_style=theme.MUTED, last=True)
        self.update(t)


class NetworkPanel(_PanelBase):
    interval = 15.0
    group = "network"

    def __init__(self, fetch: Callable[[], object], redis_port: int = 36379,
                 **kwargs) -> None:
        super().__init__(fetch, **kwargs)
        self.redis_port = redis_port
        self._prev: tuple | None = None

    def _apply(self, d: dict) -> None:
        if not d or not d.get("ok"):
            if self.last is None:
                self.update(Text.assemble(("⧉ NETWORK\n", f"bold {theme.GOLD}"),
                                          (" ?", theme.MUTED)))
            return
        self.last = d
        vpn: sources.Status = d["vpn"]
        wifi: sources.Status = d["wifi"]
        cur_ports = {t["port"] for t in d["tunnels"]}
        cur = (vpn.ok, frozenset(cur_ports))
        if self._prev is not None and cur != self._prev:
            self.post_message(PolledStatus.Changed())  # excite beads on any change
            prev_vpn, prev_ports = self._prev
            if prev_vpn and not vpn.ok:  # notify only on DOWN transitions
                self.app.notifier("Griot · VPN down", "VPN disconnected")
            if self.redis_port in prev_ports and self.redis_port not in cur_ports:
                self.app.notifier("Griot · tunnel down",
                                  f"Redis tunnel :{self.redis_port} closed")
        self._prev = cur

        t = Text()
        t.append("⧉ NETWORK\n", style=f"bold {theme.GOLD}")
        _row(t, "ip", d["ip"] or "—")
        _row(t, "wifi", wifi.text if wifi.ok else "off",
             value_style=theme.OK if wifi.ok else theme.MUTED)
        _row(t, "vpn", vpn.text if vpn.ok else "down",
             value_style=theme.OK if vpn.ok else theme.ERR)
        t.append(" ports\n", style=theme.MUTED)
        if d["ports"]:
            for p in d["ports"]:
                t.append(f"  :{p['port']:<6}", style=theme.GOLD)
                t.append(f"{p['proc'][:14]}\n", style=theme.TEXT)
        else:
            t.append("  none\n", style=theme.MUTED)
        t.append(" tunnels\n", style=theme.MUTED)
        if d["tunnels"]:
            for tn in d["tunnels"]:
                t.append(f"  :{tn['port']:<6}", style=theme.GOLD_BRIGHT)
                t.append("ssh", style=theme.MUTED)
                t.append("\n")
        else:
            t.append("  none", style=theme.MUTED)
        self.update(t)


class UsagePanel(_PanelBase):
    interval = 600.0
    group = "usage"

    def _apply(self, d: dict | None) -> None:
        if not d:
            if self.last is None:
                self.update(Text.assemble(("Σ CLAUDE (mo)\n", f"bold {theme.GOLD}"),
                                          (" ?", theme.MUTED)))
            return
        self.last = d
        t = Text()
        t.append("Σ CLAUDE (mo)\n", style=f"bold {theme.GOLD}")
        _row(t, "total", _htok(d["total"]))
        _row(t, "output", _htok(d["output"]), value_style=theme.MUTED)
        _row(t, "input", _htok(d["input"]), value_style=theme.MUTED)
        _row(t, "cache r", _htok(d["cache_read"]), value_style=theme.MUTED)
        _row(t, "cache w", _htok(d["cache_create"]), value_style=theme.MUTED, last=True)
        self.update(t)


class StatusApp(App):
    CSS_PATH = theme.TCSS_PATH

    def __init__(self, config: Config | None = None,
                 fetchers: dict[str, Callable] | None = None,
                 notifier: Callable[[str, str], None] | None = None) -> None:
        super().__init__()
        self.config = config or load_config()
        self.notifier = notifier or sources.notify
        f = fetchers or {}
        self.fetchers = {
            "weather": f.get("weather") or (
                lambda: sources.weather(self.config.latitude, self.config.longitude)),
            "battery": f.get("battery", sources.battery_detail),
            "network": f.get("network", sources.network_detail),
            "usage": f.get("usage", sources.claude_usage_breakdown),
            "calendar": f.get("calendar", sources.calendar_events),
        }

    def compose(self) -> ComposeResult:
        yield Static(" GRIOT", classes="panel-title")
        yield Beads(id="beads")
        yield ClockLine(id="clock")
        with VerticalScroll(id="status-scroll"):
            yield PolledStatus("☀", self.fetchers["weather"], 900.0, id="weather")
            yield CalendarPanel(self.fetchers["calendar"], id="calendar", classes="panel")
            yield BatteryPanel(self.fetchers["battery"], id="battery")
            yield NetworkPanel(self.fetchers["network"],
                               redis_port=self.config.redis_tunnel_port, id="network")
            yield UsagePanel(self.fetchers["usage"], id="usage")

    def on_polled_status_changed(self, message: PolledStatus.Changed) -> None:
        self.query_one("#beads", Beads).excite()


def main() -> None:
    StatusApp().run()


if __name__ == "__main__":
    main()
