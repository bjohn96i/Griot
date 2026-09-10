"""[brain] config resolution — defaults, validation, and the hook's params file."""
import pytest

from griot.brain import settings


def test_defaults_are_opt_in():
    cfg = settings.resolve({})
    assert cfg["enabled"] is False
    assert cfg["fps"] == 12
    assert cfg["hops"] == 5
    assert cfg["speed"] == 1.0
    assert cfg["spread"] == 1.0


def test_user_values_override_defaults():
    cfg = settings.resolve({"enabled": True, "fps": 24, "hops": 8,
                            "speed": 0.6, "spread": 0.5})
    assert cfg["enabled"] is True
    assert cfg["fps"] == 24
    assert cfg["hops"] == 8
    assert cfg["speed"] == pytest.approx(0.6)
    assert cfg["spread"] == pytest.approx(0.5)


def test_the_dials_are_floats_not_truncated_to_int():
    """The whole point of speed/spread is fractional tuning — an int cast
    would silently turn every value under 1.0 into 0."""
    cfg = settings.resolve({"speed": 0.6, "spread": 0.75})
    assert isinstance(cfg["speed"], float)
    assert cfg["speed"] > 0.0 and cfg["spread"] > 0.0


def test_the_kitty_era_keys_are_gone():
    cfg = settings.resolve({})
    assert set(cfg) == {"enabled", "fps", "hops", "speed", "spread"}


@pytest.mark.parametrize("bad, message", [
    ({"fps": 0}, "fps"),
    ({"fps": -1}, "fps"),
    ({"hops": 0}, "hops"),
    ({"hops": -1}, "hops"),
    ({"speed": 0}, "speed"),
    ({"speed": -0.5}, "speed"),
    ({"speed": "fast"}, "speed"),
    ({"spread": 0}, "spread"),
    ({"spread": -1}, "spread"),
    ({"spread": "wide"}, "spread"),
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
