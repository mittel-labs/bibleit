from __future__ import annotations

import os
from pathlib import Path
import tomllib

CONFIG_NAMES = ("LIVE_TOKEN", "LIVE_URL", "DEFAULT_TRANSLATION", "THEME", "LISTENING_MODEL")
CONFIG_DIR = Path.home() / ".bibleit"
CONFIG_FILE = "config"
THEMES = ("light", "dark")


def config_path() -> Path:
    override = os.getenv("BIBLEIT_CONFIG_FILE")
    if override:
        return Path(override).expanduser()

    return CONFIG_DIR / CONFIG_FILE


def load_config() -> dict[str, str]:
    path = config_path()
    if not path.exists():
        return {}

    with path.open("rb") as file:
        data = tomllib.load(file)

    return {name: str(data.get(name, "")) for name in CONFIG_NAMES if name in data}


def save_config(values: dict[str, str]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    config = load_config()
    for name in CONFIG_NAMES:
        if name in values:
            value = values[name]
            if value == "":
                config.pop(name, None)
            else:
                config[name] = value

    lines = [f'{name} = "{_toml_escape(config.get(name, ""))}"' for name in CONFIG_NAMES if name in config]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def config_value(name: str, default: str = "") -> str:
    env_name = f"BIBLEIT_{name}"
    value = os.getenv(env_name)
    if value is not None:
        return value

    return load_config().get(name, default)


def theme_value() -> str:
    value = config_value("THEME", "light").strip().lower()
    if value not in THEMES:
        return "light"

    return value


def theme_is_dark() -> bool:
    return theme_value() == "dark"


def env_overrides() -> dict[str, str]:
    return {name: os.environ[f"BIBLEIT_{name}"] for name in CONFIG_NAMES if f"BIBLEIT_{name}" in os.environ}


def _toml_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\b", "\\b")
        .replace("\f", "\\f")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
