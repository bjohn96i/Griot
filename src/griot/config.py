"""Load ~/.config/griot/config.toml with spec defaults."""
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "griot" / "config.toml"

DEFAULTS = {
    "vault_path": "~/Documents/ObsidianVault",
    "tasks_dir": "Notes/Tasks",
    "claude_default_dir": "~/code",
    "repos_dir": "~/code",
    "startup_prompt": "/griot:brief",
    "jira_base_url": "https://your-org.atlassian.net/browse",
    "redis_tunnel_port": 36379,
    "latitude": 0.0,
    "longitude": 0.0,
    "left_percent": 20,
    "right_percent": 16,
    "theme_name": "vibranium-night",
}


@dataclass(frozen=True)
class Config:
    vault_path: Path
    tasks_dir: str
    claude_default_dir: Path
    repos_dir: Path
    startup_prompt: str
    commands: dict[str, str]
    jira_base_url: str
    redis_tunnel_port: int
    latitude: float
    longitude: float
    left_percent: int
    right_percent: int
    theme_name: str = "vibranium-night"
    theme_colors: dict[str, str] = field(default_factory=dict)
    animation: dict[str, object] = field(default_factory=dict)
    sound: dict[str, object] = field(default_factory=dict)

    @property
    def tasks_path(self) -> Path:
        return self.vault_path / self.tasks_dir


def load_config(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG_PATH
    raw: dict = {}
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        pass
    weather = raw.get("weather", {})
    layout = raw.get("layout", {})
    commands = {str(k): str(v) for k, v in raw.get("commands", {}).items()}
    theme_raw = raw.get("theme", {})
    theme_colors = {str(k): str(v) for k, v in theme_raw.get("colors", {}).items()}
    animation = dict(raw.get("animation", {}))
    sound = dict(raw.get("sound", {}))
    merged = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    return Config(
        vault_path=Path(str(merged["vault_path"])).expanduser(),
        tasks_dir=str(merged["tasks_dir"]),
        claude_default_dir=Path(str(merged["claude_default_dir"])).expanduser(),
        repos_dir=Path(str(merged["repos_dir"])).expanduser(),
        startup_prompt=str(merged["startup_prompt"]),
        commands=commands,
        jira_base_url=str(merged["jira_base_url"]),
        redis_tunnel_port=int(merged["redis_tunnel_port"]),
        latitude=float(weather.get("latitude", DEFAULTS["latitude"])),
        longitude=float(weather.get("longitude", DEFAULTS["longitude"])),
        left_percent=int(layout.get("left_percent", DEFAULTS["left_percent"])),
        right_percent=int(layout.get("right_percent", DEFAULTS["right_percent"])),
        theme_name=str(theme_raw.get("name", DEFAULTS["theme_name"])),
        theme_colors=theme_colors,
        animation=animation,
        sound=sound,
    )
