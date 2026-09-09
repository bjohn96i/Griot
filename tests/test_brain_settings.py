"""[brain] config resolution — defaults, validation, and the hook's params file."""
import pytest

from griot.brain import settings


def test_defaults_are_opt_in():
    cfg = settings.resolve({})
    assert cfg["enabled"] is False
    assert cfg["fps_idle"] == 3
    assert cfg["fps_active"] == 15
    assert cfg["hops"] == 3
    assert cfg["size"] == (900, 560)
    assert cfg["socket"] == ""


def test_user_values_override_defaults():
    cfg = settings.resolve({"enabled": True, "fps_active": 10, "size": [640, 400]})
    assert cfg["enabled"] is True
    assert cfg["fps_active"] == 10
    assert cfg["size"] == (640, 400)


@pytest.mark.parametrize("bad, message", [
    ({"fps_idle": 0}, "fps_idle"),
    ({"fps_active": 0}, "fps_active"),
    ({"fps_idle": 20, "fps_active": 5}, "fps_idle"),
    ({"hops": 0}, "hops"),
    ({"active_window": -1}, "active_window"),
    ({"size": [900]}, "size"),
    ({"size": [0, 560]}, "size"),
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
