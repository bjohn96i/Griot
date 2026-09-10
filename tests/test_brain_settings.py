"""[brain] config resolution — defaults, validation, and the hook's params file."""
import pytest

from griot.brain import settings


def test_defaults_are_opt_in():
    cfg = settings.resolve({})
    assert cfg["enabled"] is False
    assert cfg["fps"] == 12
    assert cfg["hops"] == 5


def test_user_values_override_defaults():
    cfg = settings.resolve({"enabled": True, "fps": 24, "hops": 8})
    assert cfg["enabled"] is True
    assert cfg["fps"] == 24
    assert cfg["hops"] == 8


def test_the_kitty_era_keys_are_gone():
    cfg = settings.resolve({})
    assert set(cfg) == {"enabled", "fps", "hops"}


@pytest.mark.parametrize("bad, message", [
    ({"fps": 0}, "fps"),
    ({"fps": -1}, "fps"),
    ({"hops": 0}, "hops"),
    ({"hops": -1}, "hops"),
])
def test_invalid_values_are_rejected_by_name(bad, message):
    with pytest.raises(ValueError) as e:
        settings.resolve(bad)
    assert message in str(e.value)


def test_write_params_renders_shell_assignments(tmp_path):
    target = settings.write_params(settings.resolve({"enabled": True}),
                                   tmp_path / "params")
    body = dict(line.split("=", 1) for line in target.read_text().splitlines())
    assert body["brain_enabled"] == "1"
    assert body["spool"].endswith("/brain/events'")


def test_write_params_marks_disabled(tmp_path):
    target = settings.write_params(settings.resolve({}), tmp_path / "params")
    assert "brain_enabled=0" in target.read_text()
