from datetime import date
from pathlib import Path

import pytest

from griot.config import Config
from griot.tasks.app import TasksApp
from griot.status.app import StatusApp
from griot.status.sources import Status


def _cfg(tmp_path) -> Config:
    return Config(
        vault_path=tmp_path,
        tasks_dir="Tasks",
        claude_default_dir=tmp_path,
        redis_tunnel_port=36379,
        latitude=0.0,
        longitude=0.0,
        left_percent=20,
        right_percent=16,
        repos_dir=tmp_path / "repos",
        startup_prompt="/griot:brief",
        commands={},
        jira_base_url="https://your-org.atlassian.net/browse",
    )


def _task(dirp, name, priority=3, progress=None, status="To Do"):
    dirp.mkdir(exist_ok=True)
    fm = [f"Status: {status}", f"Priority: {priority}"]
    if progress:
        fm.append(f"Last Progress: {progress}")
    (dirp / name).write_text("---\n" + "\n".join(fm) + "\n---\nbody\n")


def _option_prompts(app) -> list[str]:
    lst = app.query_one("#task-list")
    return [str(lst.get_option_at_index(i).prompt) for i in range(lst.option_count)]


async def test_mounts_and_lists_tasks(tmp_path):
    _task(tmp_path / "Tasks", "Alpha.md", priority=1)
    _task(tmp_path / "Tasks", "Beta.md", priority=5)
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda cmd: None)
    async with app.run_test() as pilot:
        assert len(app.notes) == 2
        assert app.query_one("#task-list").option_count >= 2


async def test_grouped_two_line_cards(tmp_path):
    _task(tmp_path / "Tasks", "Doing.md", priority=1, status="In Progress",
          progress="2026-09-01")
    _task(tmp_path / "Tasks", "Todo.md", priority=2, status="To Do")
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda cmd: None)
    async with app.run_test() as pilot:
        prompts = _option_prompts(app)
        # group headers present (Active view spans two statuses)
        assert any("In Progress" in p and "──" in p for p in prompts)
        assert any("To Do" in p and "──" in p for p in prompts)
        # each task card is two lines: full title + a metadata line (P · heat · age)
        card = next(p for p in prompts if "Doing" in p)
        assert "\n" in card
        meta = card.splitlines()[1]
        assert "Doing" in card and "P1" in meta and "d" in meta


async def test_enter_opens_detail_overlay(tmp_path):
    from griot.tasks.detail import TaskDetailScreen

    _task(tmp_path / "Tasks", "Alpha.md")
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda cmd: None)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, TaskDetailScreen)
        assert app.screen.note.title == "Alpha"


async def test_o_opens_note_in_center_tab(tmp_path):
    _task(tmp_path / "Tasks", "Alpha.md")
    calls: list[list[str]] = []
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=calls.append)
    async with app.run_test() as pilot:
        await pilot.press("o")
    assert calls, "o should invoke tmux"
    cmd = calls[0]
    assert cmd[:6] == ["tmux", "-L", "griot", "new-window", "-t", "griot-center"]
    assert "griot-view" in cmd[-1]
    assert "Alpha.md" in cmd[-1]


async def test_touch_updates_last_progress(tmp_path):
    _task(tmp_path / "Tasks", "Alpha.md")
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda cmd: None)
    async with app.run_test() as pilot:
        await pilot.press("t")
    text = (tmp_path / "Tasks" / "Alpha.md").read_text()
    assert f"Last Progress: {date.today().isoformat()}" in text


async def test_priority_cycle_writes_frontmatter(tmp_path):
    _task(tmp_path / "Tasks", "Alpha.md", priority=1)
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda cmd: None)
    async with app.run_test() as pilot:
        await pilot.press("p")
    assert "Priority: 2" in (tmp_path / "Tasks" / "Alpha.md").read_text()


async def test_priority_cycle_tracks_note_across_rescan_reorder(tmp_path):
    # Alpha starts at priority 1 (row 0, cursor default). Beta starts at
    # priority 2 with full heat (Last Progress = today), so on the priority
    # tie created by Alpha's first cycle (1 -> 2), Beta's higher heat sorts
    # it ahead of Alpha, swapping their row order. If the cursor row isn't
    # re-anchored to the selected note's identity after _rescan(), the
    # second "p" press will hit whatever now sits at the stale row index
    # (Beta) instead of continuing to act on Alpha.
    _task(tmp_path / "Tasks", "Alpha.md", priority=1)
    _task(
        tmp_path / "Tasks",
        "Beta.md",
        priority=2,
        progress=date.today().isoformat(),
    )
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda cmd: None)
    async with app.run_test() as pilot:
        await pilot.press("p")
        await pilot.press("p")
    alpha_text = (tmp_path / "Tasks" / "Alpha.md").read_text()
    beta_text = (tmp_path / "Tasks" / "Beta.md").read_text()
    assert "Priority: 3" in alpha_text
    assert "Priority: 2" in beta_text


async def test_filter_cycles(tmp_path):
    _task(tmp_path / "Tasks", "Doing.md", status="In Progress")
    _task(tmp_path / "Tasks", "Todo.md", status="To Do")
    _task(tmp_path / "Tasks", "Finished.md", status="Done")
    _task(tmp_path / "Tasks", "Killed.md", status="Cancelled")
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda cmd: None)
    async with app.run_test() as pilot:
        # default = Active: hides Done and Cancelled
        assert len(app.notes) == 2
        await pilot.press("f")  # -> In Progress
        assert len(app.notes) == 1
        await pilot.press("f")  # -> To Do
        assert len(app.notes) == 1
        await pilot.press("f")  # -> Done (now visible)
        assert len(app.notes) == 1
        await pilot.press("f")  # -> All (everything)
        assert len(app.notes) == 4
        await pilot.press("f")  # -> back to Active
        assert len(app.notes) == 2


def _batt(**over):
    d = {"ok": True, "pct": 84, "on_ac": False, "status": "discharging",
         "remaining_min": 240, "drain_pct_per_hr": 21.0, "eta_10_min": 211}
    d.update(over)
    return d


def _net(**over):
    d = {"ok": True, "ip": "192.168.1.42", "wifi": Status(True, "on"),
         "vpn": Status(True, "Corp VPN"),
         "ports": [{"proc": "docker", "pid": 1, "port": 8080, "addr": "*"},
                   {"proc": "node", "pid": 2, "port": 3000, "addr": "*"}],
         "tunnels": [{"proc": "ssh", "pid": 3, "port": 36379, "addr": "127.0.0.1"}]}
    d.update(over)
    return d


def _usage(**over):
    d = {"total": 898_582_515, "input": 10_229, "output": 3_334_364,
         "cache_read": 820_448_560, "cache_create": 74_789_362}
    d.update(over)
    return d


def _status_fetchers(**overrides):
    fetchers = {
        "weather": lambda: Status(True, "☀ 72°F Clear"),
        "battery": _batt,
        "network": _net,
        "usage": _usage,
        "calendar": lambda: ["15:00 API cache sync"],
    }
    fetchers.update(overrides)
    return fetchers


async def test_status_app_mounts_all_widgets(tmp_path):
    app = StatusApp(config=_cfg(tmp_path), fetchers=_status_fetchers())
    async with app.run_test() as pilot:
        await pilot.pause()
        for wid in ["#battery", "#network", "#usage", "#weather",
                    "#clock", "#beads", "#calendar"]:
            assert app.query_one(wid)


async def test_battery_panel_shows_drain_and_eta(tmp_path):
    app = StatusApp(config=_cfg(tmp_path), fetchers=_status_fetchers())
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        content = str(app.query_one("#battery").content)
        assert "84%" in content and "battery" in content
        assert "%/hr" in content and "10%" in content


async def test_network_panel_shows_ip_ports_tunnels(tmp_path):
    app = StatusApp(config=_cfg(tmp_path), fetchers=_status_fetchers())
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        content = str(app.query_one("#network").content)
        assert "192.168.1.42" in content
        assert "8080" in content and "docker" in content
        assert "36379" in content  # redis tunnel


async def test_usage_panel_breaks_out_tokens(tmp_path):
    app = StatusApp(config=_cfg(tmp_path), fetchers=_status_fetchers())
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        content = str(app.query_one("#usage").content)
        assert "898" in content   # total (898.6M)
        assert "820" in content   # cache read broken out (820.4M)


async def test_network_vpn_flip_excites_beads(tmp_path):
    state = {"up": True}
    fetchers = _status_fetchers(
        network=lambda: _net(vpn=Status(state["up"], "Corp VPN" if state["up"] else "down"))
    )
    app = StatusApp(config=_cfg(tmp_path), fetchers=fetchers)
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        beads = app.query_one("#beads")
        state["up"] = False
        app.query_one("#network").refresh_now()
        await pilot.pause(0.2)
        assert beads.excited > 0


async def test_stale_indicator_on_failure(tmp_path):
    state = {"ok": True}
    fetchers = _status_fetchers(weather=lambda: (
        Status(True, "☀ 72°F Clear") if state["ok"] else Status(False, "?")
    ))
    app = StatusApp(config=_cfg(tmp_path), fetchers=fetchers)
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one("#weather")
        widget.refresh_now()
        await pilot.pause(0.2)
        state["ok"] = False
        widget.refresh_now()
        await pilot.pause(0.2)
        assert "◌" in str(widget.content)
        assert "72°F" in str(widget.content)  # last good value kept


async def test_calendar_panel_uses_injected_fetcher_not_real_icalbuddy(tmp_path):
    # Finding 1: calendar_events() must never be called directly by
    # CalendarPanel/StatusApp in tests - it must go through the injected
    # "calendar" fetcher, same as every other PolledStatus source.
    calls = {"n": 0}

    def fake_calendar():
        calls["n"] += 1
        return ["15:00 API cache sync", "16:00 QA guild"]

    fetchers = _status_fetchers(calendar=fake_calendar)
    app = StatusApp(config=_cfg(tmp_path), fetchers=fetchers)
    async with app.run_test() as pilot:
        await pilot.pause()
        calendar = app.query_one("#calendar")
        calendar.refresh_now()
        await pilot.pause(0.2)
        assert calls["n"] > 0
        assert "API cache sync" in str(calendar.content)


async def test_click_opens_detail_overlay(tmp_path):
    from griot.tasks.detail import TaskDetailScreen

    _task(tmp_path / "Tasks", "Alpha.md")  # single task -> no group header, card at y=0
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda cmd: None)
    async with app.run_test() as pilot:
        lst = app.query_one("#task-list")
        await pilot.hover(lst, offset=(2, 1))  # hover registers the option under pointer
        await pilot.click(lst, offset=(2, 1))
        await pilot.pause()
        assert isinstance(app.screen, TaskDetailScreen)
        assert app.screen.note.title == "Alpha"
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, TaskDetailScreen)


async def test_detail_o_opens_center_tab(tmp_path):
    from griot.tasks.detail import TaskDetailScreen

    _task(tmp_path / "Tasks", "Alpha.md")
    calls: list[list[str]] = []
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=calls.append)
    async with app.run_test() as pilot:
        await pilot.press("enter")  # open detail overlay
        await pilot.pause()
        assert isinstance(app.screen, TaskDetailScreen)
        await pilot.press("o")
        await pilot.pause()
    assert calls and "Alpha.md" in calls[0][-1]


async def test_detail_touch_updates_note_and_survives_rescan(tmp_path):
    from datetime import date as _date

    from griot.tasks.detail import TaskDetailScreen

    _task(tmp_path / "Tasks", "Alpha.md")
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda cmd: None)
    async with app.run_test() as pilot:
        await pilot.press("enter")  # open detail overlay
        await pilot.pause()
        assert isinstance(app.screen, TaskDetailScreen)
        await pilot.press("t")  # touch from inside the overlay; triggers _rescan too
        await pilot.pause()
        assert isinstance(app.screen, TaskDetailScreen)  # still open, no crash
    text = (tmp_path / "Tasks" / "Alpha.md").read_text()
    assert f"Last Progress: {_date.today().isoformat()}" in text


async def test_c_loads_task_into_claude(tmp_path):
    _task(tmp_path / "Tasks", "Alpha.md")
    calls: list[list[str]] = []
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=calls.append)
    async with app.run_test() as pilot:
        await pilot.press("c")
    assert calls, "c should invoke tmux new-window"
    cmd = calls[0]
    assert cmd[:6] == ["tmux", "-L", "griot", "new-window", "-t", "griot-center"]
    assert cmd[-1].startswith("claude ")
    assert "Alpha.md" in cmd[-1]
    # vault context AND repo write access are both granted
    assert "--add-dir" in cmd[-1]
    assert str(tmp_path) in cmd[-1]   # vault
    assert "repos" in cmd[-1]         # repos_dir


async def test_detail_c_loads_task_into_claude(tmp_path):
    from griot.tasks.detail import TaskDetailScreen

    _task(tmp_path / "Tasks", "Alpha.md")
    calls: list[list[str]] = []
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=calls.append)
    async with app.run_test() as pilot:
        await pilot.press("enter")  # open detail overlay
        await pilot.pause()
        assert isinstance(app.screen, TaskDetailScreen)
        await pilot.press("c")
        await pilot.pause()
    assert calls and calls[0][-1].startswith("claude ")
    assert "Alpha.md" in calls[0][-1]


def _lines(content: str) -> list[str]:
    return content.splitlines()


async def test_panels_stack_one_stat_per_line(tmp_path):
    app = StatusApp(config=_cfg(tmp_path), fetchers=_status_fetchers())
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        batt = _lines(str(app.query_one("#battery").content))
        # charge% and source are on SEPARATE lines now
        assert any("84%" in ln and "battery" not in ln for ln in batt)
        assert any("battery" in ln and "84%" not in ln for ln in batt)
        # drain and ETA on separate lines
        assert any("%/hr" in ln and "10%" not in ln for ln in batt)
        assert any("10%" in ln and "%/hr" not in ln for ln in batt)

        net = _lines(str(app.query_one("#network").content))
        assert any("wifi" in ln and "vpn" not in ln for ln in net)
        assert any("vpn" in ln and "wifi" not in ln for ln in net)
        # each port on its own line
        assert any("8080" in ln and "3000" not in ln for ln in net)
        assert any("3000" in ln and "8080" not in ln for ln in net)

        usage = _lines(str(app.query_one("#usage").content))
        assert any("output" in ln and "input" not in ln for ln in usage)
        assert any("input" in ln and "output" not in ln for ln in usage)
        assert any("cache r" in ln for ln in usage)
        assert any("cache w" in ln for ln in usage)


async def test_default_filter_labeled_open(tmp_path):
    _task(tmp_path / "Tasks", "Alpha.md", status="In Progress")
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda cmd: None)
    async with app.run_test() as pilot:
        header = str(app.query_one("#tasks-header").content)
        assert "Open" in header and "Active" not in header


def _task_jira(dirp, name, jira, status="In Progress"):
    dirp.mkdir(exist_ok=True)
    fm = [f"Status: {status}", "Priority: 1", f"Jira: {jira}"]
    (dirp / name).write_text("---\n" + "\n".join(fm) + "\n---\nbody\n")


async def test_J_opens_jira_url(tmp_path):
    url = "https://your-org.atlassian.net/browse/PROJ-4914"
    _task_jira(tmp_path / "Tasks", "Alpha.md", url)
    opened: list[str] = []
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda c: None,
                   opener=opened.append)
    async with app.run_test() as pilot:
        await pilot.press("J")
    assert opened == [url]


async def test_J_no_jira_does_nothing(tmp_path):
    _task(tmp_path / "Tasks", "Alpha.md")  # no Jira field
    opened: list[str] = []
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda c: None,
                   opener=opened.append)
    async with app.run_test() as pilot:
        await pilot.press("J")
    assert opened == []


async def test_do_or_die_badge_and_header_count(tmp_path):
    _task(tmp_path / "Tasks", "Stale.md", status="In Progress", progress="2026-06-01")
    _task(tmp_path / "Tasks", "Fresh.md", status="In Progress",
          progress=date.today().isoformat())
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda cmd: None)
    async with app.run_test() as pilot:
        header = str(app.query_one("#tasks-header").content)
        assert "DoD 1" in header  # one do-or-die task
        stale_card = next(p for p in _option_prompts(app) if "Stale" in p)
        fresh_card = next(p for p in _option_prompts(app) if "Fresh" in p)
        assert "☠" in stale_card
        assert "☠" not in fresh_card


async def test_notify_on_vpn_down(tmp_path):
    state = {"up": True}
    notes: list[tuple[str, str]] = []
    fetchers = _status_fetchers(
        network=lambda: _net(vpn=Status(state["up"], "Corp VPN" if state["up"] else "down")))
    app = StatusApp(config=_cfg(tmp_path), fetchers=fetchers, notifier=lambda t, m: notes.append((t, m)))
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        state["up"] = False
        app.query_one("#network").refresh_now()
        await pilot.pause(0.2)
    assert any("VPN" in t for t, _ in notes)


async def test_notify_on_redis_tunnel_down(tmp_path):
    state = {"tun": True}
    notes: list[tuple[str, str]] = []

    def net():
        tunnels = ([{"proc": "ssh", "pid": 3, "port": 36379, "addr": "127.0.0.1"}]
                   if state["tun"] else [])
        return _net(tunnels=tunnels)

    app = StatusApp(config=_cfg(tmp_path), fetchers=_status_fetchers(network=net),
                    notifier=lambda t, m: notes.append((t, m)))
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        state["tun"] = False
        app.query_one("#network").refresh_now()
        await pilot.pause(0.2)
    assert any("tunnel" in t.lower() or "36379" in m for t, m in notes)


async def test_notify_on_meeting_soon(tmp_path):
    from datetime import datetime, timedelta
    soon = (datetime.now() + timedelta(minutes=3)).strftime("%H:%M")
    notes: list[tuple[str, str]] = []
    app = StatusApp(config=_cfg(tmp_path),
                    fetchers=_status_fetchers(calendar=lambda: [f"{soon} standup"]),
                    notifier=lambda t, m: notes.append((t, m)))
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        app.query_one("#calendar").refresh_now()
        await pilot.pause(0.2)
    assert any("meeting" in t.lower() for t, _ in notes)


async def test_no_notify_when_stable(tmp_path):
    notes: list[tuple[str, str]] = []
    app = StatusApp(config=_cfg(tmp_path), fetchers=_status_fetchers(),
                    notifier=lambda t, m: notes.append((t, m)))
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        app.query_one("#network").refresh_now()
        await pilot.pause(0.2)
    assert notes == []  # vpn up, tunnel up, no meeting <5min -> silence


async def test_J_builds_url_from_bare_ticket_ids(tmp_path):
    _task_jira(tmp_path / "Tasks", "Multi.md", "PROJ-4927, PROJ-4937")
    opened: list[str] = []
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda c: None, opener=opened.append)
    async with app.run_test() as pilot:
        await pilot.press("J")
    assert opened == [
        "https://your-org.atlassian.net/browse/PROJ-4927",
        "https://your-org.atlassian.net/browse/PROJ-4937",
    ]


async def test_J_na_opens_nothing(tmp_path):
    _task_jira(tmp_path / "Tasks", "Na.md", "n/a")
    opened: list[str] = []
    app = TasksApp(config=_cfg(tmp_path), tmux_runner=lambda c: None, opener=opened.append)
    async with app.run_test() as pilot:
        await pilot.press("J")
    assert opened == []


# --- themes and animations ---

def _themed_cfg(tmp_path, name, animation=None, colors=None) -> Config:
    base = _cfg(tmp_path)
    return Config(**{**base.__dict__, "theme_name": name,
                     "theme_colors": colors or {}, "animation": animation or {}})


def _plain(widget) -> str:
    """Rendered text of a Static (Textual 8 exposes it as .content)."""
    c = widget.content
    return getattr(c, "plain", str(c))


async def test_status_app_activates_theme_and_css_variables(tmp_path):
    from griot import theme
    app = StatusApp(config=_themed_cfg(tmp_path, "dataterm"), fetchers=_status_fetchers())
    try:
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            assert theme.ACTIVE == "dataterm"
            assert app.get_css_variables()["accent"] == "#FFD07A"
            # stylesheet variables resolved: the screen background is the theme bg.
            # Dataterm is the one theme that is not on black — this is the lit
            # amber screen, and the khaki #877254 stays in the chrome.
            assert app.screen.styles.background.hex.upper() == "#140F08"
            v = app.get_css_variables()
            assert v["panel"] == "#1E1710"     # card fill, carries body text
            assert v["chrome"] == "#877254"    # khaki bars
            assert v["outline"] == "#877254"   # khaki card frames
            assert v["border"] == "#000000"    # black seams between panes
            assert v["select"] == "#877254"
            heart = app.query_one("#beads")
            assert heart.style_name == "glyphs"           # dataterm default
            assert heart.cfg["glyph_set"] == "hex"
            assert "NETWORK" in _plain(app.query_one("#network"))  # upper-cased title
    finally:
        theme.activate("vibranium-night")


async def test_user_animation_overrides_theme_default(tmp_path):
    from griot import theme
    cfg = _themed_cfg(tmp_path, "vaporwave-mono",
                      animation={"style": "bars", "height": 3, "speed": 0.05})
    app = StatusApp(config=cfg, fetchers=_status_fetchers())
    try:
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            heart = app.query_one("#beads")
            assert heart.style_name == "bars" and heart.cfg["height"] == 3
            plain = _plain(heart)
            assert plain.count("\n") == 2                      # three rows
            assert any(ch in "▁▂▃▄▅▆▇█" for ch in plain)
    finally:
        theme.activate("vibranium-night")


async def test_every_animation_style_renders_without_error(tmp_path):
    from griot import theme
    for style in ("beads", "scope", "bars", "glyphs"):
        app = StatusApp(config=_themed_cfg(tmp_path, "vibranium-night",
                                           animation={"style": style, "speed": 0.02}),
                        fetchers=_status_fetchers())
        try:
            async with app.run_test() as pilot:
                await pilot.pause(0.15)
                heart = app.query_one("#beads")
                assert heart.tick > 1, style
                assert _plain(heart).strip(), style
                heart.excite()
                assert heart.excited > 0
        finally:
            theme.activate("vibranium-night")


def test_tasks_app_exposes_css_variables(tmp_path):
    from griot import theme
    cfg = _themed_cfg(tmp_path, "vaporwave-mono", colors={"accent": "#123456"})
    app = TasksApp(config=cfg, tmux_runner=lambda cmd: None)
    try:
        assert app.get_css_variables()["accent"] == "#123456"
        assert theme.ACCENT == "#123456"
    finally:
        theme.activate("vibranium-night")


async def test_mounting_the_status_pane_never_starts_audio_by_itself(tmp_path):
    """Sound is opt-in. Dataterm asks for it; `[sound] enabled` still gates it."""
    from griot import sound, theme
    app = StatusApp(config=_themed_cfg(tmp_path, "dataterm"), fetchers=_status_fetchers())
    try:
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            assert app.sound_cfg["whir"] is True      # the theme wants the drive
            assert app.sound_cfg["enabled"] is False  # but nobody turned it on
            eng = sound.engine()
            assert eng is not None and eng.running is False
            app.query_one("#beads").excite()          # the seek hook, unarmed
            await pilot.press("m")                    # mute key must not explode
    finally:
        app.exit()
        sound.shutdown()
        theme.activate("vibranium-night")   # module-level palette is global
    assert sound.engine() is None


@pytest.mark.parametrize("app_factory", ["status", "tasks"])
async def test_css_driven_surfaces_follow_the_configured_theme(tmp_path, app_factory):
    """Regression: Textual freezes $bg/$panel/$border during App.__init__.

    Both apps used to call super().__init__() before theme.activate_from_config(),
    so every stylesheet colour rendered in whatever theme happened to be active —
    always the default. Imperative theme.ACCENT styling hid it.
    """
    from griot import theme
    cfg = _themed_cfg(tmp_path, "dataterm")
    app = StatusApp(config=cfg, fetchers=_status_fetchers()) if app_factory == "status" \
        else TasksApp(config=cfg, tmux_runner=lambda a: None, opener=lambda u: None)
    try:
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            assert app.screen.styles.background.hex.upper() == "#140F08", \
                "screen must be the amber phosphor, not the default theme's black"
            panels = app.query(".panel")
            if panels:
                first = panels.first()
                assert first.styles.background.hex.upper() == "#1E1710", \
                    "card fill must be the lifted brown, not vibranium navy"
                assert first.styles.border_top[1].hex.upper() == "#877254", \
                    "card frame must be the khaki case, not the black seam colour"
    finally:
        app.exit()
        theme.activate("vibranium-night")


async def test_vault_writes_click_the_drive(tmp_path, monkeypatch):
    """`t` and `p` both write to disk, so both should be audible.

    The tasks pane is its own process in the real layout, so it installs its
    own engine in on_mount — this drives that path rather than pre-installing.
    """
    from griot import sound

    class Recorder:
        supports_loop = True

        def __init__(self):
            self.played = []

        def available(self):
            return True

        def play(self, path, volume, loop=False):
            self.played.append(path.name)
            return type("H", (), {"poll": lambda s: 0, "stop": lambda s: None})()

        def kill(self, handle):
            pass

    rec = Recorder()
    monkeypatch.setattr(sound, "best_player", lambda: rec)
    monkeypatch.setattr(sound, "MUTE_FLAG", tmp_path / "muted")
    monkeypatch.setattr(sound, "ensure_assets", lambda *a, **k: {
        "whir": tmp_path / "w.wav", "seek": tmp_path / "s.wav",
        "clicks": [tmp_path / "c1.wav"]})

    cfg = _cfg(tmp_path)
    cfg = Config(**{**cfg.__dict__, "sound": {"enabled": True, "clicks": True}})
    _task(tmp_path / "Tasks", "Alpha.md")
    app = TasksApp(config=cfg, tmux_runner=lambda cmd: None)
    try:
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            eng = sound.engine()
            assert eng is not None, "the tasks pane must install its own engine"
            assert eng.cfg["whir"] is False and eng.cfg["seek"] is False, \
                "ambient sound belongs to the status pane only"
            assert eng._ticks is False, "only one pane owns the idle ticker"
            await pilot.press("t")
            assert rec.played == ["c1.wav"], rec.played
            eng._last_click = 0.0          # step past the debounce deliberately
            await pilot.press("p")
            assert rec.played == ["c1.wav", "c1.wav"], rec.played
    finally:
        app.exit()
        sound.shutdown()
    assert (tmp_path / "Tasks" / "Alpha.md").read_text().count("Last Progress") == 1


# ------------------------------------------------------------- drive footer ----

def test_hint_line_pads_the_state_to_the_right_edge():
    from griot.status.app import hint_line
    line = hint_line(28, enabled=True, muted=False)
    assert len(line) == 28
    assert line.startswith("m mute")
    assert line.endswith("DRIVE ON")
    assert "  " in line, "the gap between key and state is padding, not a tab"


def test_hint_line_names_all_three_states():
    from griot.status.app import hint_line
    assert hint_line(28, enabled=True, muted=False).endswith("DRIVE ON")
    assert hint_line(28, enabled=True, muted=True).endswith("DRIVE MUTED")
    off = hint_line(28, enabled=False, muted=False)
    assert off.endswith("SOUND OFF")
    assert "m mute" not in off, "no key hint for something that cannot be muted"


def test_hint_line_drops_the_key_before_it_truncates_the_state():
    from griot.status.app import hint_line
    wide = hint_line(20, enabled=True, muted=True)
    assert len(wide) == 20 and wide.endswith("DRIVE MUTED")
    tight = hint_line(14, enabled=True, muted=True)
    assert "m mute" not in tight, "state survives, key goes first"
    assert tight.endswith("DRIVE MUTED")
    assert hint_line(6, enabled=True, muted=True) == "DRIVE "   # hard truncation
    assert hint_line(0, enabled=True, muted=False) == ""


async def test_footer_is_docked_at_the_bottom_and_reports_sound_off(tmp_path):
    """Default config has no [sound], so the pane says so rather than lying."""
    from griot import theme
    from griot.status.app import DriveFooter
    app = StatusApp(config=_themed_cfg(tmp_path, "dataterm"), fetchers=_status_fetchers())
    try:
        async with app.run_test(size=(34, 40)) as pilot:
            await pilot.pause(0.1)
            footer = app.query_one("#drive-footer", DriveFooter)
            assert "SOUND OFF" in _plain(footer)
            assert footer.styles.dock == "bottom"
            assert footer.region.y == app.screen.size.height - 1, "not at the bottom"
            # chrome bar with chrome's own foreground, not the amber body text
            assert footer.styles.background.hex.upper() == "#877254"
            assert footer.styles.color.hex.upper() == "#000000"
            await pilot.press("m")
            assert "SOUND OFF" in _plain(footer), "m must be inert when sound is off"
    finally:
        app.exit()
        theme.activate("vibranium-night")


async def test_footer_flips_between_on_and_muted(tmp_path, monkeypatch):
    from griot import sound, theme
    from griot.status.app import DriveFooter
    monkeypatch.setattr(sound, "MUTE_FLAG", tmp_path / "muted")
    monkeypatch.setattr(sound, "best_player", lambda: _SilentPlayer())
    monkeypatch.setattr(sound, "ensure_assets", lambda *a, **k: {
        "whir": tmp_path / "w.wav", "seek": tmp_path / "s.wav",
        "clicks": [tmp_path / "c1.wav"]})
    cfg = _themed_cfg(tmp_path, "dataterm")
    cfg = Config(**{**cfg.__dict__, "sound": {"enabled": True, "clicks": False}})
    app = StatusApp(config=cfg, fetchers=_status_fetchers())
    try:
        async with app.run_test(size=(34, 40)) as pilot:
            await pilot.pause(0.1)
            footer = app.query_one("#drive-footer", DriveFooter)
            assert "DRIVE ON" in _plain(footer)
            await pilot.press("m")
            assert "DRIVE MUTED" in _plain(footer)
            assert (tmp_path / "muted").exists(), "mute must be on disk for both panes"
            await pilot.press("m")
            assert "DRIVE ON" in _plain(footer)
            assert not (tmp_path / "muted").exists()
    finally:
        app.exit()
        sound.shutdown()
        theme.activate("vibranium-night")


class _SilentPlayer:
    supports_loop = True

    def available(self):
        return True

    def play(self, path, volume, loop=False):
        return type("H", (), {"poll": lambda s: None, "stop": lambda s: None})()

    def kill(self, handle):
        pass
