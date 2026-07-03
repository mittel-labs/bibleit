from __future__ import annotations

from textual import events
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Select, Switch

from bibleit import translation
from bibleit.config import config_path, env_overrides, load_config, save_config, theme_is_dark
from bibleit.listening import available_model_paths


def _select_blank():
    return getattr(Select, "NULL", getattr(Select, "BLANK", None))


class ConfigScreen(Screen):
    TEXT_CONFIGS = ("LIVE_TOKEN", "LIVE_URL")

    BINDINGS = [
        ("escape", "close", "Close"),
        ("ctrl+s", "save", "Save"),
    ]

    def compose(self):
        values = load_config()
        overrides = env_overrides()

        with Container(id="config-panel"):
            yield Label("Config", id="config-title")
            yield Label(f"Stored in {config_path()}", id="config-path")

            yield Label("Theme", classes="config-label")
            with Horizontal(id="config-theme-row"):
                yield Label("Dark mode", id="config-theme-label")
                yield Switch(value=theme_is_dark(), id="config-theme-dark")

            if "THEME" in overrides:
                yield Label(
                    "BIBLEIT_THEME is set and will take precedence.",
                    classes="config-note",
                )

            for name in self.TEXT_CONFIGS:
                yield Label(name, classes="config-label")
                input_ = Input(
                    value=values.get(name, ""),
                    placeholder=f"BIBLEIT_{name}",
                    id=f"config-{name.lower().replace('_', '-')}",
                )
                if name == "LIVE_TOKEN":
                    input_.password = True
                yield input_

                if name in overrides:
                    yield Label(
                        f"BIBLEIT_{name} is set and will take precedence.",
                        classes="config-note",
                    )

            yield Label("DEFAULT_TRANSLATION", classes="config-label")
            default_translation = values.get("DEFAULT_TRANSLATION", "")
            yield Select(
                self._translation_options(default_translation),
                prompt="Auto",
                allow_blank=True,
                value=default_translation or _select_blank(),
                id="config-default-translation",
            )

            if "DEFAULT_TRANSLATION" in overrides:
                yield Label(
                    "BIBLEIT_DEFAULT_TRANSLATION is set and will take precedence.",
                    classes="config-note",
                )

            yield Label("LISTENING_MODEL", classes="config-label")
            listening_model = values.get("LISTENING_MODEL", "")
            yield Select(
                self._listening_model_options(listening_model),
                prompt="Select a Vosk model",
                allow_blank=True,
                value=listening_model or _select_blank(),
                id="config-listening-model",
            )

            if "LISTENING_MODEL" in overrides:
                yield Label(
                    "BIBLEIT_LISTENING_MODEL is set and will take precedence.",
                    classes="config-note",
                )

            with Horizontal(id="config-actions"):
                yield Button("Save", id="config-save")
                yield Button("Close", id="config-close")

    def _translation_options(self, selected_slug: str = "") -> list[tuple[str, str]]:
        installed = {slug: header for slug, header in translation.get_installed().items() if header is not None}

        options = [(self._translation_label(slug, header.name), slug) for slug, header in sorted(installed.items())]

        if selected_slug and selected_slug not in installed:
            options.insert(0, (selected_slug, selected_slug))

        return options

    def _translation_label(self, slug: str, name: str, limit: int = 56) -> str:
        label = f"{slug} - {name}"
        if len(label) <= limit:
            return label
        return f"{label[: limit - 1]}…"

    def _listening_model_options(self, selected_path: str = "") -> list[tuple[str, str]]:
        paths = {str(path): path for path in available_model_paths()}
        options = [(path.name, value) for value, path in sorted(paths.items(), key=lambda item: item[1].name.lower())]

        if selected_path and selected_path not in paths:
            options.insert(0, (selected_path, selected_path))

        return options

    def _values(self) -> dict[str, str]:
        values = {
            name: self.query_one(f"#config-{name.lower().replace('_', '-')}", Input).value for name in self.TEXT_CONFIGS
        }
        default_translation = self.query_one("#config-default-translation", Select).value
        values["DEFAULT_TRANSLATION"] = "" if default_translation == _select_blank() else str(default_translation)
        listening_model = self.query_one("#config-listening-model", Select).value
        values["LISTENING_MODEL"] = "" if listening_model == _select_blank() else str(listening_model)
        values["THEME"] = "dark" if self.query_one("#config-theme-dark", Switch).value else "light"
        return values

    def action_save(self) -> None:
        values = self._values()
        save_config(values)
        self.app.apply_theme(theme_is_dark())
        self.notify("Config saved", title=str(config_path()), timeout=3)
        self.app.pop_screen()

    def action_close(self) -> None:
        self.app.apply_theme(theme_is_dark())
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "config-save":
            event.stop()
            self.action_save()
        elif event.button.id == "config-close":
            event.stop()
            self.action_close()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_save()

    def on_key(self, event: events.Key) -> None:
        if event.key not in {"down", "up"}:
            return

        if self._select_is_expanded():
            return

        event.stop()
        if event.key == "down":
            self.focus_next()
        else:
            self.focus_previous()

    def _select_is_expanded(self) -> bool:
        focused = self.app.focused
        while focused is not None and focused is not self:
            if isinstance(focused, Select) and focused.has_class("-expanded"):
                return True
            focused = focused.parent
        return False
