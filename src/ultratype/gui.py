"""GTK4/Libadwaita settings GUI for UltraType."""

from __future__ import annotations

import asyncio
import os
from dataclasses import asdict

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ultratype.config import (
    Config,
    GeneralConfig,
    InjectionConfig,
    KeybindsConfig,
    LLMConfig,
    ProfileConfig,
    RecordingConfig,
    TranslationConfig,
    WhisperConfig,
    load_config,
    save_config,
)


class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="UltraType Settings")
        self.set_default_size(500, 700)
        self._config = load_config()
        self._entries: dict[str, Gtk.Widget] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        page = Adw.PreferencesPage()

        # -- General --
        grp = Adw.PreferencesGroup(title="General")
        self._add_switch(grp, "general.notification", "Notifications",
                         "Show desktop notifications", self._config.general.notification)
        page.add(grp)

        # -- Recording --
        grp = Adw.PreferencesGroup(title="Recording")
        self._add_entry(grp, "recording.sample_rate", "Sample Rate",
                        str(self._config.recording.sample_rate))
        self._add_entry(grp, "recording.channels", "Channels",
                        str(self._config.recording.channels))
        self._add_entry(grp, "recording.format", "Format",
                        self._config.recording.format)
        self._add_entry(grp, "recording.device", "Device",
                        self._config.recording.device)
        page.add(grp)

        # -- Whisper --
        grp = Adw.PreferencesGroup(title="Whisper")
        self._add_entry(grp, "whisper.model_path", "Model Path",
                        self._config.whisper.model_path)
        self._add_entry(grp, "whisper.model_name", "Model Name",
                        self._config.whisper.model_name)
        self._add_entry(grp, "whisper.extra_args", "Extra Args",
                        self._config.whisper.extra_args)
        page.add(grp)

        # -- LLM --
        grp = Adw.PreferencesGroup(title="LLM Post-Processing")
        self._add_entry(grp, "llm.provider", "Provider",
                        self._config.llm.provider)
        self._add_entry(grp, "llm.api_key", "API Key",
                        self._config.llm.api_key, password=True)
        self._add_entry(grp, "llm.model", "Model",
                        self._config.llm.model)
        self._add_entry(grp, "llm.endpoint", "Endpoint",
                        self._config.llm.endpoint)
        self._add_entry(grp, "llm.timeout", "Timeout (s)",
                        str(self._config.llm.timeout))
        page.add(grp)

        # -- Translation --
        grp = Adw.PreferencesGroup(title="Translation")
        self._add_entry(grp, "translation.source_language", "Source Language",
                        self._config.translation.source_language)
        self._add_entry(grp, "translation.target_language", "Target Language",
                        self._config.translation.target_language)
        page.add(grp)

        # -- Keybinds --
        grp = Adw.PreferencesGroup(title="Keybinds")
        self._add_entry(grp, "keybinds.dictate", "Dictate",
                        self._config.keybinds.dictate)
        self._add_entry(grp, "keybinds.stop", "Stop",
                        self._config.keybinds.stop)
        self._add_entry(grp, "keybinds.translate", "Translate",
                        self._config.keybinds.translate)
        self._add_entry(grp, "keybinds.backend", "Backend",
                        self._config.keybinds.backend)
        page.add(grp)

        # -- Profile --
        grp = Adw.PreferencesGroup(
            title="Profile",
            description="Help the LLM understand your speech context for better corrections",
        )
        self._add_entry(grp, "profile.description", "Description",
                        self._config.profile.description)
        self._add_entry(grp, "profile.vocabulary", "Vocabulary",
                        self._config.profile.vocabulary)
        self._add_entry(grp, "profile.language_style", "Language Style",
                        self._config.profile.language_style)
        page.add(grp)

        # -- Save button --
        btn_grp = Adw.PreferencesGroup()
        save_btn = Gtk.Button(label="Save", css_classes=["suggested-action"])
        save_btn.connect("clicked", self._on_save)
        btn_grp.add(save_btn)
        page.add(btn_grp)

        # Toolbar view with header bar
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(page)
        self.set_content(toolbar)

    def _add_entry(
        self, group: Adw.PreferencesGroup, key: str, title: str,
        value: str, password: bool = False,
    ) -> None:
        row = Adw.EntryRow(title=title, text=value)
        if password:
            row.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self._entries[key] = row
        group.add(row)

    def _add_switch(
        self, group: Adw.PreferencesGroup, key: str, title: str,
        subtitle: str, active: bool,
    ) -> None:
        row = Adw.SwitchRow(title=title, subtitle=subtitle, active=active)
        self._entries[key] = row
        group.add(row)

    def _on_save(self, _button: Gtk.Button) -> None:
        """Read widget values and save config."""
        data = asdict(self._config)

        for key, widget in self._entries.items():
            section, field = key.split(".", 1)
            if isinstance(widget, Adw.SwitchRow):
                data[section][field] = widget.get_active()
            elif isinstance(widget, Adw.EntryRow):
                text = widget.get_text()
                old_val = data[section][field]
                if isinstance(old_val, int):
                    try:
                        data[section][field] = int(text)
                    except ValueError:
                        pass
                else:
                    data[section][field] = text

        config = Config(
            general=GeneralConfig(**data["general"]),
            recording=RecordingConfig(**data["recording"]),
            whisper=WhisperConfig(**data["whisper"]),
            llm=LLMConfig(**data["llm"]),
            translation=TranslationConfig(**data["translation"]),
            keybinds=KeybindsConfig(**data["keybinds"]),
            injection=InjectionConfig(**data["injection"]),
            profile=ProfileConfig(**data["profile"]),
        )
        save_config(config)

        # Try to reload daemon config
        try:
            from ultratype.daemon import send_command
            asyncio.run(send_command("reload"))
        except Exception:
            pass

        # Show toast
        toast = Adw.Toast(title="Settings saved")
        # Find toast overlay or just close
        self.close()


class SettingsApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.ultratype.settings")

    def do_activate(self) -> None:
        win = SettingsWindow(self)
        win.present()


def run_gui() -> None:
    """Launch the settings GUI."""
    app = SettingsApp()
    app.run()
