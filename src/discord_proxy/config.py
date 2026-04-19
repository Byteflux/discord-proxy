import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_CONFIG_PATH = Path("discord-proxy.toml")
_DEFAULTS = {
    "nats_url": "nats://127.0.0.1:4222",
    "log_level": "INFO",
}


@dataclass
class Config:
    nats_url: str = field(default=_DEFAULTS["nats_url"])
    log_level: str = field(default=_DEFAULTS["log_level"])


def from_file_and_env() -> Config:
    """Load config from TOML file then apply environment variable overrides.

    File path is read from DISCORD_PROXY_CONFIG (default: ./discord-proxy.toml).
    Individual overrides: DISCORD_PROXY_NATS_URL, DISCORD_PROXY_LOG_LEVEL.
    """
    cfg: dict[str, str] = dict(_DEFAULTS)

    config_path = Path(os.environ.get("DISCORD_PROXY_CONFIG", _DEFAULT_CONFIG_PATH))
    if config_path.exists():
        with config_path.open("rb") as f:
            file_cfg = tomllib.load(f)
        cfg.update({k: v for k, v in file_cfg.items() if k in cfg})

    env_map = {
        "DISCORD_PROXY_NATS_URL": "nats_url",
        "DISCORD_PROXY_LOG_LEVEL": "log_level",
    }
    for env_key, cfg_key in env_map.items():
        if val := os.environ.get(env_key):
            cfg[cfg_key] = val

    return Config(**cfg)
