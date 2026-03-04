"""UltraType CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ultratype",
        description="Push-to-talk dictation for Wayland/Hyprland",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )
    parser.add_argument(
        "--version", action="version", version="%(prog)s 0.1.0"
    )
    subparsers = parser.add_subparsers(dest="command")

    # daemon
    subparsers.add_parser("daemon", help="Start the background daemon")

    # dictate / stop / translate
    subparsers.add_parser("dictate", help="Start recording")
    subparsers.add_parser("stop", help="Stop recording, transcribe, and inject")
    subparsers.add_parser("translate", help="Stop recording, transcribe, translate, and inject")

    # status
    sub_status = subparsers.add_parser("status", help="Print current state")
    sub_status.add_argument("--waybar", action="store_true", help="Waybar JSON format")
    sub_status.add_argument("--watch", action="store_true", help="Continuous output")

    # config
    sub_config = subparsers.add_parser("config", help="Configuration management")
    config_sub = sub_config.add_subparsers(dest="config_action")
    config_sub.add_parser("show", help="Show current config")
    config_set = config_sub.add_parser("set", help="Set a config value")
    config_set.add_argument("key", help="Config key (e.g., llm.model)")
    config_set.add_argument("value", help="Config value")
    config_sub.add_parser("edit", help="Open config in $EDITOR")

    # model
    sub_model = subparsers.add_parser("model", help="Model management")
    model_sub = sub_model.add_subparsers(dest="model_action")
    model_sub.add_parser("list", help="List available models")
    model_dl = model_sub.add_parser("download", help="Download a model")
    model_dl.add_argument("model_name", help="Model name (e.g., base.en)")

    # settings (GUI)
    subparsers.add_parser("settings", help="Open settings GUI")

    args = parser.parse_args()

    # Logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    match args.command:
        case "daemon":
            from ultratype.daemon import run_daemon
            asyncio.run(run_daemon())

        case "dictate" | "stop" | "translate":
            from ultratype.daemon import send_command
            response = asyncio.run(send_command(args.command))
            if "error" in response:
                print(f"Error: {response['error']}", file=sys.stderr)
                sys.exit(1)
            else:
                print(json.dumps(response, indent=2))

        case "status":
            from ultratype.waybar import print_status
            asyncio.run(print_status(watch=args.watch, waybar=args.waybar))

        case "config":
            _handle_config(args)

        case "model":
            _handle_model(args)

        case "settings":
            from ultratype.gui import run_gui
            run_gui()


def _handle_config(args: argparse.Namespace) -> None:
    from ultratype.config import CONFIG_PATH, load_config, save_config

    match args.config_action:
        case "show" | None:
            load_config()  # ensure file exists
            print(CONFIG_PATH.read_text())

        case "set":
            from dataclasses import asdict
            config = load_config()
            data = asdict(config)
            # Navigate dotted key: e.g., "llm.model"
            keys = args.key.split(".")
            target = data
            for k in keys[:-1]:
                if k not in target:
                    print(f"Error: Unknown config section '{k}'", file=sys.stderr)
                    sys.exit(1)
                target = target[k]
            final_key = keys[-1]
            if final_key not in target:
                print(f"Error: Unknown config key '{args.key}'", file=sys.stderr)
                sys.exit(1)
            # Type coercion
            old_val = target[final_key]
            if isinstance(old_val, bool):
                target[final_key] = args.value.lower() in ("true", "1", "yes")
            elif isinstance(old_val, int):
                target[final_key] = int(args.value)
            else:
                target[final_key] = args.value
            # Reconstruct and save
            from ultratype.config import (
                GeneralConfig, RecordingConfig, WhisperConfig,
                LLMConfig, TranslationConfig, KeybindsConfig, InjectionConfig, Config,
            )
            new_config = Config(
                general=GeneralConfig(**data["general"]),
                recording=RecordingConfig(**data["recording"]),
                whisper=WhisperConfig(**data["whisper"]),
                llm=LLMConfig(**data["llm"]),
                translation=TranslationConfig(**data["translation"]),
                keybinds=KeybindsConfig(**data["keybinds"]),
                injection=InjectionConfig(**data["injection"]),
            )
            save_config(new_config)
            print(f"Set {args.key} = {args.value}")

        case "edit":
            load_config()  # ensure file exists
            editor = os.environ.get("EDITOR", "nano")
            subprocess.run([editor, str(CONFIG_PATH)])


def _handle_model(args: argparse.Namespace) -> None:
    from ultratype.models import download_model, list_models

    match args.model_action:
        case "list" | None:
            asyncio.run(list_models())
        case "download":
            asyncio.run(download_model(args.model_name))


if __name__ == "__main__":
    main()
