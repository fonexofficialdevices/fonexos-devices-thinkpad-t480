#!/usr/bin/env python3
"""
FonexOS Theme Engine — the backend behind Fonex Toolbox's Theming menu and
the future community Themes app.

A "theme" is a folder with this structure (per FonexOS Documentation, 13/08/26):

    my-theme/
        info.xml          (required) name, author, version, compliant, description
        icons/
            scalable/...  (recommended) can include Light/Dark icon variants
        wallpapers/
            *.png|*.jpg   each image needs a matching *.xml descriptor
            *.xml
        sounds/           (optional)
        extensions/       (optional; extension configs)
        apply.sh          (required) script that actually applies the theme

Themes are discovered from:
    /usr/share/fonexos/themes/            (system-installed)
    ~/.local/share/fonexos/themes/        (user-installed / community uploads)

Themes must be marked <compliant>true</compliant> in info.xml to comply with
FonexOS' components. Users can flip "Free Will Mode" on to bypass this check
and apply any theme anyway (see toggle_free_will()).

Restore GNOME / Re-enable Fonex Look is a toggle, not a one-way reset:
  - Restoring GNOME disables every currently-enabled shell extension and
    installs the stock Fedora wallpapers (which FonexOS does NOT ship by
    default), remembering exactly what it changed.
  - Re-enabling the Fonex look reverses precisely that: re-enables only the
    extensions it disabled, and removes only the stock wallpapers it
    installed — it doesn't touch anything the user changed in between.

CLI usage:
    python3 fonexos_theme_engine.py list
    python3 fonexos_theme_engine.py validate <theme-name>
    python3 fonexos_theme_engine.py apply <theme-name>
    python3 fonexos_theme_engine.py scaffold <theme-name>
    python3 fonexos_theme_engine.py restore-gnome
    python3 fonexos_theme_engine.py enable-fonex-look
    python3 fonexos_theme_engine.py toggle-free-will
"""

import argparse
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SYSTEM_THEMES_DIR = Path("/usr/share/fonexos/themes")
USER_THEMES_DIR = Path.home() / ".local" / "share" / "fonexos" / "themes"
THEME_DIRS = [SYSTEM_THEMES_DIR, USER_THEMES_DIR]

CONFIG_DIR = Path.home() / ".config" / "fonexos"
ENGINE_CONFIG = CONFIG_DIR / "engine.conf"

BUILTIN_MODES = {"dark", "light", "auto"}

# --- FonexOS branding — adjust these to match your actual theme/icon names ---
FONEX_ICON_THEME = "Fonex-icons"
FONEX_CURSOR_THEME = "Fonex-icons"
FONEX_GTK_THEME = "FonexOS"

# Stock Fedora wallpapers are bundled in the image but NOT installed/active
# by default (FonexOS ships its own branded wallpapers instead). Restoring
# GNOME copies them from here into an active location; re-enabling the
# Fonex look removes exactly what was copied.
STOCK_BACKGROUNDS_SOURCE = Path("/usr/share/fonexos/stock-assets/backgrounds")
STOCK_BACKGROUNDS_TARGET = Path.home() / ".local" / "share" / "backgrounds" / "stock-fedora"


# --------------------------------------------------------------------------
# Engine config (current mode, free-will toggle)
# --------------------------------------------------------------------------

def load_engine_config():
    defaults = {
        "CURRENT_MODE": "auto",
        "FREE_WILL": "off",
        "GNOME_RESTORED": "off",
        "DISABLED_EXTENSIONS": "",
        "INSTALLED_STOCK_BG_FILES": "",
    }
    try:
        for line in ENGINE_CONFIG.read_text().splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                defaults[key.strip()] = value.strip()
    except OSError:
        pass
    return defaults


def save_engine_config(state):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in state.items()]
    ENGINE_CONFIG.write_text("\n".join(lines) + "\n")


def toggle_free_will():
    state = load_engine_config()
    state["FREE_WILL"] = "off" if state.get("FREE_WILL") == "on" else "on"
    save_engine_config(state)
    return state["FREE_WILL"] == "on"


# --------------------------------------------------------------------------
# Theme discovery + validation
# --------------------------------------------------------------------------

def _parse_bool(value, default=False):
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def parse_info_xml(path):
    """Parse a theme's info.xml into a metadata dict. Returns None on failure."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None

    def field(tag, default=""):
        el = root.find(tag)
        return el.text.strip() if el is not None and el.text else default

    return {
        "name": field("name", "Untitled Theme"),
        "author": field("author", "Unknown"),
        "version": field("version", "0.0"),
        "description": field("description", ""),
        "compliant": _parse_bool(field("compliant", "false")),
    }


def validate_theme(theme_dir):
    """Check a theme folder against the required structure. Returns (errors, warnings)."""
    errors = []
    warnings = []

    info_xml = theme_dir / "info.xml"
    if not info_xml.exists():
        errors.append("Missing info.xml")

    apply_sh = theme_dir / "apply.sh"
    if not apply_sh.exists():
        errors.append("Missing apply.sh")

    icons_dir = theme_dir / "icons" / "scalable"
    if not icons_dir.is_dir():
        warnings.append("No icons/scalable/ directory found")

    wallpapers_dir = theme_dir / "wallpapers"
    if wallpapers_dir.is_dir():
        images = [p for p in wallpapers_dir.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
        for img in images:
            if not img.with_suffix(".xml").exists():
                warnings.append(f"wallpapers/{img.name} has no matching .xml descriptor")
    else:
        warnings.append("No wallpapers/ directory found")

    return errors, warnings


def discover_themes():
    """Scan THEME_DIRS for valid theme folders. Returns a list of metadata dicts."""
    themes = []
    for base in THEME_DIRS:
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            info_xml = entry / "info.xml"
            meta = parse_info_xml(info_xml) if info_xml.exists() else None
            errors, warnings = validate_theme(entry)
            themes.append({
                "path": entry,
                "id": entry.name,
                "name": (meta or {}).get("name", entry.name),
                "author": (meta or {}).get("author", "Unknown"),
                "version": (meta or {}).get("version", "0.0"),
                "description": (meta or {}).get("description", ""),
                "compliant": (meta or {}).get("compliant", False),
                "errors": errors,
                "warnings": warnings,
            })
    return themes


# --------------------------------------------------------------------------
# Applying themes / modes
# --------------------------------------------------------------------------

def _gsettings(*args):
    if not shutil.which("gsettings"):
        return False
    try:
        subprocess.run(["gsettings", *args], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, OSError):
        return False


def apply_builtin_mode(mode):
    """Apply Dark / Light / Auto via gsettings color-scheme. Returns (ok, applied_live)."""
    if mode not in BUILTIN_MODES:
        raise ValueError(f"Unknown mode: {mode}")
    scheme_map = {"dark": "prefer-dark", "light": "prefer-light", "auto": "default"}
    applied_live = _gsettings("set", "org.gnome.desktop.interface", "color-scheme", scheme_map[mode])

    state = load_engine_config()
    state["CURRENT_MODE"] = mode
    save_engine_config(state)
    return True, applied_live


def apply_custom_theme(theme, free_will=False):
    """
    Run a theme's apply.sh. Refuses non-compliant themes unless free_will=True.
    Returns (ok: bool, message: str).
    """
    if theme["errors"]:
        return False, "Cannot apply — " + "; ".join(theme["errors"])

    if not theme["compliant"] and not free_will:
        return False, (
            f"'{theme['name']}' is not marked compliant with FonexOS' components. "
            "Enable Free Will Mode to apply it anyway."
        )

    apply_sh = theme["path"] / "apply.sh"
    try:
        os.chmod(apply_sh, 0o755)
        result = subprocess.run(["bash", str(apply_sh)], cwd=str(theme["path"]))
        if result.returncode != 0:
            return False, f"apply.sh exited with code {result.returncode}"
    except OSError as e:
        return False, f"Failed to run apply.sh: {e}"

    state = load_engine_config()
    state["CURRENT_MODE"] = theme["id"]
    save_engine_config(state)
    return True, f"'{theme['name']}' applied."


def restore_gnome():
    """
    Reset to stock GNOME: disables EVERY currently-enabled shell extension
    and installs the stock Fedora wallpapers (bundled but inactive by
    default on FonexOS). Remembers exactly what changed so
    enable_fonex_look() can reverse it precisely later.

    Returns (results: dict, disabled_extensions: list, installed_bg_files: list, bg_applied: bool)
    """
    # 1. Disable every currently-enabled extension (not just FonexOS ones —
    #    stock Fedora GNOME ships with none active).
    disabled_extensions = []
    if shutil.which("gnome-extensions"):
        try:
            enabled = subprocess.run(
                ["gnome-extensions", "list", "--enabled"], capture_output=True, text=True, check=True
            ).stdout.splitlines()
            for uuid in enabled:
                uuid = uuid.strip()
                if not uuid:
                    continue
                subprocess.run(["gnome-extensions", "disable", uuid], capture_output=True)
                disabled_extensions.append(uuid)
        except (subprocess.CalledProcessError, OSError):
            pass

    # 2. Install the stock Fedora wallpapers — FonexOS doesn't ship them
    #    active by default, so copy them from the bundled source into an
    #    active location and point picture-uri at one of them.
    installed_bg_files = []
    bg_applied = False
    if STOCK_BACKGROUNDS_SOURCE.is_dir():
        STOCK_BACKGROUNDS_TARGET.mkdir(parents=True, exist_ok=True)
        for f in sorted(STOCK_BACKGROUNDS_SOURCE.iterdir()):
            if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".xml"):
                shutil.copy2(f, STOCK_BACKGROUNDS_TARGET / f.name)
                installed_bg_files.append(f.name)

        first_image = next(
            (STOCK_BACKGROUNDS_TARGET / n for n in installed_bg_files
             if Path(n).suffix.lower() in (".png", ".jpg", ".jpeg")),
            None,
        )
        if first_image:
            uri = f"file://{first_image}"
            applied1 = _gsettings("set", "org.gnome.desktop.background", "picture-uri", uri)
            applied2 = _gsettings("set", "org.gnome.desktop.background", "picture-uri-dark", uri)
            bg_applied = applied1 or applied2

    # 3. Reset icon/cursor/gtk theme + color scheme to stock Adwaita.
    results = {}
    results["icon-theme"] = _gsettings("set", "org.gnome.desktop.interface", "icon-theme", "Adwaita")
    results["cursor-theme"] = _gsettings("set", "org.gnome.desktop.interface", "cursor-theme", "Adwaita")
    results["gtk-theme"] = _gsettings("set", "org.gnome.desktop.interface", "gtk-theme", "Adwaita")
    results["color-scheme"] = _gsettings("set", "org.gnome.desktop.interface", "color-scheme", "default")

    # 4. Remember exactly what we changed, so re-enabling the Fonex look
    #    can reverse precisely this — nothing more, nothing less.
    state = load_engine_config()
    state["CURRENT_MODE"] = "auto"
    state["GNOME_RESTORED"] = "on"
    state["DISABLED_EXTENSIONS"] = ",".join(disabled_extensions)
    state["INSTALLED_STOCK_BG_FILES"] = ",".join(installed_bg_files)
    save_engine_config(state)

    return results, disabled_extensions, installed_bg_files, bg_applied


def enable_fonex_look():
    """
    Reverse restore_gnome() precisely: re-enable only the extensions it
    disabled, remove only the stock wallpapers it installed, and reapply
    the FonexOS icon/cursor/gtk theme.

    Returns (results: dict, re_enabled_extensions: list, removed_bg_files: list)
    """
    state = load_engine_config()

    # 1. Remove exactly the stock wallpaper files we installed earlier.
    removed_bg_files = []
    installed = [name for name in state.get("INSTALLED_STOCK_BG_FILES", "").split(",") if name]
    for name in installed:
        target = STOCK_BACKGROUNDS_TARGET / name
        try:
            target.unlink()
            removed_bg_files.append(name)
        except OSError:
            pass

    # 2. Re-enable exactly the extensions we disabled earlier.
    re_enabled_extensions = []
    disabled = [uuid for uuid in state.get("DISABLED_EXTENSIONS", "").split(",") if uuid]
    if disabled and shutil.which("gnome-extensions"):
        for uuid in disabled:
            result = subprocess.run(["gnome-extensions", "enable", uuid], capture_output=True)
            if result.returncode == 0:
                re_enabled_extensions.append(uuid)

    # 3. Reapply the FonexOS icon/cursor/gtk theme (color-scheme is left
    #    alone — that's owned by the Dark/Light/Auto Theming menu).
    results = {}
    results["icon-theme"] = _gsettings("set", "org.gnome.desktop.interface", "icon-theme", FONEX_ICON_THEME)
    results["cursor-theme"] = _gsettings("set", "org.gnome.desktop.interface", "cursor-theme", FONEX_CURSOR_THEME)
    results["gtk-theme"] = _gsettings("set", "org.gnome.desktop.interface", "gtk-theme", FONEX_GTK_THEME)

    state["GNOME_RESTORED"] = "off"
    state["DISABLED_EXTENSIONS"] = ""
    state["INSTALLED_STOCK_BG_FILES"] = ""
    save_engine_config(state)

    return results, re_enabled_extensions, removed_bg_files


# --------------------------------------------------------------------------
# Scaffolding new theme packages (for creators / the future Themes app)
# --------------------------------------------------------------------------

INFO_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<theme>
    <name>{name}</name>
    <author>Your Name</author>
    <version>1.0</version>
    <compliant>false</compliant>
    <description>A short description of your theme.</description>
</theme>
"""

APPLY_SH_TEMPLATE = """#!/bin/sh
# Applies this theme's assets. Edit as needed.
set -e
THEME_DIR="$(cd "$(dirname "$0")" && pwd)"

# Example: set an icon theme (replace with your icon theme's actual name)
# gsettings set org.gnome.desktop.interface icon-theme "MyThemeIcons"

# Example: install wallpapers
if [ -d "$THEME_DIR/wallpapers" ]; then
    mkdir -p "$HOME/.local/share/backgrounds"
    cp -f "$THEME_DIR"/wallpapers/*.png "$HOME/.local/share/backgrounds/" 2>/dev/null || true
    cp -f "$THEME_DIR"/wallpapers/*.jpg "$HOME/.local/share/backgrounds/" 2>/dev/null || true
fi

echo "Theme applied."
"""


def scaffold_theme(name, target_dir=None):
    """Create a new theme skeleton under USER_THEMES_DIR (or target_dir). Returns the path."""
    base = Path(target_dir) if target_dir else USER_THEMES_DIR
    theme_dir = base / name
    if theme_dir.exists():
        raise FileExistsError(f"{theme_dir} already exists")

    (theme_dir / "icons" / "scalable").mkdir(parents=True)
    (theme_dir / "wallpapers").mkdir(parents=True)
    (theme_dir / "sounds").mkdir(parents=True)
    (theme_dir / "extensions").mkdir(parents=True)

    (theme_dir / "info.xml").write_text(INFO_XML_TEMPLATE.format(name=name))
    apply_sh = theme_dir / "apply.sh"
    apply_sh.write_text(APPLY_SH_TEMPLATE)
    os.chmod(apply_sh, 0o755)

    return theme_dir


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="FonexOS Theme Engine")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List discovered themes and their compliance status.")

    p_validate = sub.add_parser("validate", help="Validate a theme's file structure.")
    p_validate.add_argument("theme_id")

    p_apply = sub.add_parser("apply", help="Apply a theme (dark/light/auto or a theme id).")
    p_apply.add_argument("theme_id")

    sub.add_parser("restore-gnome", help="Reset to the stock GNOME look (disables all extensions, installs stock wallpapers).")
    sub.add_parser("enable-fonex-look", help="Reverse restore-gnome: re-enable disabled extensions, remove stock wallpapers, reapply FonexOS theme.")
    sub.add_parser("toggle-free-will", help="Toggle bypassing FonexOS compliance checks.")

    p_scaffold = sub.add_parser("scaffold", help="Generate a new theme skeleton.")
    p_scaffold.add_argument("name")

    args = parser.parse_args()

    if args.command == "list":
        themes = discover_themes()
        if not themes:
            print("No themes installed.")
            return
        for t in themes:
            flag = "✅ compliant" if t["compliant"] else "⚠️  non-compliant"
            problems = ""
            if t["errors"]:
                problems = " — ❌ " + "; ".join(t["errors"])
            print(f"{t['id']:<24} {t['name']:<24} {flag}{problems}")

    elif args.command == "validate":
        matches = [t for t in discover_themes() if t["id"] == args.theme_id]
        if not matches:
            print(f"Theme '{args.theme_id}' not found.")
            sys.exit(1)
        t = matches[0]
        errors, warnings = validate_theme(t["path"])
        print(f"{t['name']} ({t['id']})")
        for e in errors:
            print(f"  ❌ {e}")
        for w in warnings:
            print(f"  ⚠️  {w}")
        if not errors and not warnings:
            print("  ✅ No issues found.")

    elif args.command == "apply":
        if args.theme_id in BUILTIN_MODES:
            ok, live = apply_builtin_mode(args.theme_id)
            print(f"✅ Mode set to {args.theme_id}." + (" Applied live." if live else " (saved; gsettings unavailable)"))
        else:
            themes = {t["id"]: t for t in discover_themes()}
            if args.theme_id not in themes:
                print(f"'{args.theme_id}' is not a known mode or installed theme.")
                sys.exit(1)
            free_will = load_engine_config().get("FREE_WILL") == "on"
            ok, message = apply_custom_theme(themes[args.theme_id], free_will=free_will)
            print(("✅ " if ok else "❌ ") + message)
            if not ok:
                sys.exit(1)

    elif args.command == "restore-gnome":
        results, disabled, installed_bg, bg_applied = restore_gnome()
        print("Restoring stock GNOME look...")
        for key, ok in results.items():
            print(f"  {'✅' if ok else '⚠️ '} {key}")
        if disabled:
            print(f"Disabled {len(disabled)} extension(s): " + ", ".join(disabled))
        else:
            print("No extensions were enabled.")
        if installed_bg:
            print(f"Installed stock Fedora wallpaper(s): {', '.join(installed_bg)}"
                  + ("" if bg_applied else " (couldn't set live via gsettings)"))
        else:
            print(f"⚠️  No stock wallpapers found at {STOCK_BACKGROUNDS_SOURCE} — nothing to install.")

    elif args.command == "enable-fonex-look":
        results, re_enabled, removed_bg = enable_fonex_look()
        print("Re-enabling the Fonex look...")
        for key, ok in results.items():
            print(f"  {'✅' if ok else '⚠️ '} {key}")
        if re_enabled:
            print(f"Re-enabled {len(re_enabled)} extension(s): " + ", ".join(re_enabled))
        if removed_bg:
            print(f"Removed stock wallpaper(s): {', '.join(removed_bg)}")

    elif args.command == "toggle-free-will":
        enabled = toggle_free_will()
        state = "ON — themes no longer need to comply with FonexOS' components" if enabled else "OFF — themes must comply with FonexOS' components"
        print(f"Free Will Mode: {state}")

    elif args.command == "scaffold":
        try:
            path = scaffold_theme(args.name)
        except FileExistsError as e:
            print(f"❌ {e}")
            sys.exit(1)
        print(f"✅ Created theme skeleton at {path}")
        print("Fill in info.xml, add icons/wallpapers/sounds, and edit apply.sh.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
