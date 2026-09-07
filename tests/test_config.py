from pathlib import Path

from griot.config import Config, load_config


def test_defaults_when_file_missing(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.tasks_dir == "Notes/Tasks"
    assert cfg.redis_tunnel_port == 36379
    assert "ObsidianVault" in str(cfg.vault_path)
    assert cfg.vault_path.is_absolute()


def test_loads_and_overrides(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        'vault_path = "~/vault"\n'
        'redis_tunnel_port = 12345\n'
        "[weather]\n"
        "latitude = 40.7\n"
        "longitude = -74.0\n"
    )
    cfg = load_config(p)
    assert cfg.vault_path == Path.home() / "vault"
    assert cfg.redis_tunnel_port == 12345
    assert cfg.latitude == 40.7
    assert cfg.tasks_dir == "Notes/Tasks"  # untouched default


def test_tasks_path_join(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.tasks_path == cfg.vault_path / cfg.tasks_dir


def test_layout_defaults(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.left_percent == 20
    assert cfg.right_percent == 16


def test_layout_overrides(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[layout]\nleft_percent = 25\nright_percent = 12\n")
    cfg = load_config(p)
    assert cfg.left_percent == 25
    assert cfg.right_percent == 12


def test_startup_prompt_default(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.startup_prompt == "/griot:brief"


def test_startup_prompt_override(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('startup_prompt = "/griot:review"\n')
    assert load_config(p).startup_prompt == "/griot:review"


def test_commands_default_empty(tmp_path):
    assert load_config(tmp_path / "nope.toml").commands == {}


def test_commands_parsed(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[commands]\n"restore tunnel" = "your-tunnel-cmd --up"\n'
                 '"tunnel status" = "your-tunnel-cmd --status"\n')
    cmds = load_config(p).commands
    assert cmds["restore tunnel"] == "your-tunnel-cmd --up"
    assert cmds["tunnel status"] == "your-tunnel-cmd --status"


def test_jira_base_url_default(tmp_path):
    assert load_config(tmp_path / "nope.toml").jira_base_url == \
        "https://your-org.atlassian.net/browse"


def test_theme_defaults(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.theme_name == "vibranium-night"
    assert cfg.theme_colors == {}
    assert cfg.animation == {}


def test_theme_and_animation_sections(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        "[theme]\n"
        'name = "dataterm"\n'
        "[theme.colors]\n"
        'accent = "#ABCDEF"\n'
        "[animation]\n"
        'style = "scope"\n'
        "speed = 0.08\n"
        "height = 2\n"
        "wavelength = 12\n"
    )
    cfg = load_config(p)
    assert cfg.theme_name == "dataterm"
    assert cfg.theme_colors == {"accent": "#ABCDEF"}
    assert cfg.animation == {"style": "scope", "speed": 0.08, "height": 2, "wavelength": 12}
