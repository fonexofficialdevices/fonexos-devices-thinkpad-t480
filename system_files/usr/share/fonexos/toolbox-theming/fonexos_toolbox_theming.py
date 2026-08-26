#!/usr/bin/env python3
"""
Fonex Toolbox — Theming screen. Plain, borderless terminal menu.

    Fonex Toolbox
    ----------------------------------------

    Theming

     [1] Dark
     [2] Light
     [A] Auto                              *

     [R] Restore GNOME
     [F] Free Will Mode: OFF
     [Esc] Back

    Select:

Backed by fonexos_theme_engine.py — keep both files in the same folder.
Uses single-keypress hotkeys on a real terminal (no Enter needed); falls
back to line-based input automatically when stdin isn't a TTY (e.g. when
piping input for testing).

Usage:
    python3 fonexos_toolbox_theming.py
"""

import os
import sys

try:
    import fonexos_theme_engine as engine
except ImportError:
    print(
        "Error: fonexos_theme_engine.py must be in the same folder as this script.",
        file=sys.stderr,
    )
    sys.exit(1)

LINE_WIDTH = 42


class Ansi:
    ENABLED = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    RESET = "\033[0m" if ENABLED else ""
    BOLD = "\033[1m" if ENABLED else ""
    DIM = "\033[2m" if ENABLED else ""
    GREEN = "\033[32m" if ENABLED else ""
    YELLOW = "\033[33m" if ENABLED else ""
    RED = "\033[31m" if ENABLED else ""


def clear_screen():
    # ANSI clear + cursor-home, no dependency on an external clear/cls binary
    # (which may be missing from minimal shells, e.g. Git Bash on Windows).
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def read_key(prompt=""):
    """
    Return a single logical keypress as lowercase text: '1', '2', 'a', 'r',
    'f', 'esc', or 'q'. Uses raw single-keypress input on a real TTY;
    falls back to line-based input() (reading a whole line) otherwise,
    so the script also works when input is piped in (e.g. for testing).
    """
    if prompt:
        print(prompt, end="", flush=True)

    if not sys.stdin.isatty():
        line = sys.stdin.readline()
        if not line:
            return "q"
        text = line.strip().lower()
        return text if text else "\n"

    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getch()
        try:
            ch = ch.decode(errors="ignore")
        except AttributeError:
            pass
        if ch in ("\x1b",):
            return "esc"
        if ch in ("\x03",):
            return "q"
        return ch.lower()
    else:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        if ch == "\x1b":
            return "esc"
        if ch == "\x03":
            return "q"
        return ch.lower()


def draw_theming_screen(current_mode, custom_themes, free_will, gnome_restored):
    c = Ansi
    clear_screen()

    print(c.BOLD + "Fonex Toolbox" + c.RESET)
    print(c.DIM + "-" * LINE_WIDTH + c.RESET)
    print()
    print(c.BOLD + "Theming" + c.RESET)
    print()

    def mode_line(key, label, mode_key):
        marker = " *" if current_mode == mode_key else ""
        color = c.GREEN if current_mode == mode_key else ""
        print(f" [{key}] {color}{label}{c.RESET}{marker}")

    mode_line("1", "Dark", "dark")
    mode_line("2", "Light", "light")
    mode_line("A", "Auto", "auto")

    # Custom (community) themes discovered by the engine, if any.
    slot = 3
    theme_keys = {}
    if custom_themes:
        print()
        print(c.DIM + "Installed Themes" + c.RESET)
        for t in custom_themes:
            marker = " *" if current_mode == t["id"] else ""
            flag = "" if t["compliant"] else " (non-compliant)"
            print(f" [{slot}] {t['name']}{flag}{marker}")
            theme_keys[str(slot)] = t
            slot += 1

    print()
    if gnome_restored:
        print(" [R] Re-enable Fonex Look" + c.DIM + "  (stock GNOME active)" + c.RESET)
    else:
        print(" [R] Restore GNOME")
    fw_label = "ON" if free_will else "OFF"
    print(f" [F] Free Will Mode: {fw_label}")
    print(" [Esc] Back")
    print()

    return theme_keys


def confirm(message):
    print(Ansi.YELLOW + message + Ansi.RESET)
    answer = read_key("Type YES to confirm, anything else to cancel: ")
    return answer.strip().lower() in ("yes", "y")


def pause():
    print(Ansi.DIM + "\nPress any key to continue..." + Ansi.RESET)
    read_key()


def main():
    while True:
        state = engine.load_engine_config()
        current_mode = state.get("CURRENT_MODE", "auto")
        free_will = state.get("FREE_WILL") == "on"
        gnome_restored = state.get("GNOME_RESTORED") == "on"
        custom_themes = engine.discover_themes()

        theme_keys = draw_theming_screen(current_mode, custom_themes, free_will, gnome_restored)
        key = read_key("Select: ")

        if key in ("esc", "q", "b", ""):
            print(Ansi.DIM + "\nBack." + Ansi.RESET)
            return

        if key in ("1", "2") or key == "a":
            mode = {"1": "dark", "2": "light", "a": "auto"}[key]
            results = engine.apply_builtin_mode(mode)
            print(Ansi.GREEN + f"\n✅ Theme set to {mode.title()}." + Ansi.RESET)
            if not results["color_scheme"]:
                print(Ansi.DIM + "(color scheme not applied — gsettings unavailable)" + Ansi.RESET)
            if mode in ("dark", "light") and not results["icon_theme"]:
                print(Ansi.DIM + "(icon theme not applied — gsettings unavailable)" + Ansi.RESET)
            if not results["wallpaper"]:
                print(Ansi.DIM + f"(wallpaper not applied — check {engine.WALLPAPER_DIR})" + Ansi.RESET)
            pause()
            continue

        if key == "r" and not gnome_restored:
            print()
            if confirm("⚠️  This disables ALL enabled extensions and installs stock Fedora wallpapers."):
                results, disabled, installed_bg, bg_applied = engine.restore_gnome()
                print(Ansi.GREEN + "\n✅ Restored stock GNOME look." + Ansi.RESET)
                if disabled:
                    print(Ansi.DIM + f"Disabled {len(disabled)} extension(s): " + ", ".join(disabled) + Ansi.RESET)
                else:
                    print(Ansi.DIM + "No extensions were enabled." + Ansi.RESET)
                if installed_bg:
                    print(Ansi.DIM + f"Installed stock wallpaper(s): {', '.join(installed_bg)}" + Ansi.RESET)
                else:
                    print(Ansi.YELLOW + f"⚠️  No stock wallpapers found at {engine.STOCK_BACKGROUNDS_SOURCE}." + Ansi.RESET)
            else:
                print(Ansi.YELLOW + "Cancelled." + Ansi.RESET)
            pause()
            continue

        if key == "r" and gnome_restored:
            print()
            if confirm("Re-enable the Fonex look? This re-enables the extensions and removes the stock wallpapers we added."):
                results, re_enabled, removed_bg = engine.enable_fonex_look()
                print(Ansi.GREEN + "\n✅ Fonex look re-enabled." + Ansi.RESET)
                if re_enabled:
                    print(Ansi.DIM + f"Re-enabled {len(re_enabled)} extension(s): " + ", ".join(re_enabled) + Ansi.RESET)
                if removed_bg:
                    print(Ansi.DIM + f"Removed stock wallpaper(s): {', '.join(removed_bg)}" + Ansi.RESET)
                if not results.get("wallpaper"):
                    print(Ansi.DIM + f"(FonexOS wallpaper not applied — check {engine.WALLPAPER_DIR})" + Ansi.RESET)
            else:
                print(Ansi.YELLOW + "Cancelled." + Ansi.RESET)
            pause()
            continue

        if key == "f":
            enabled = engine.toggle_free_will()
            state_label = "ON" if enabled else "OFF"
            print(Ansi.GREEN + f"\n✅ Free Will Mode: {state_label}" + Ansi.RESET)
            pause()
            continue

        if key in theme_keys:
            theme = theme_keys[key]
            ok, message = engine.apply_custom_theme(theme, free_will=free_will)
            print(("\n✅ " if ok else "\n❌ ") + message)
            pause()
            continue

        print(Ansi.RED + f"\n❌ '{key}' isn't a valid option." + Ansi.RESET)
        pause()


if __name__ == "__main__":
    main()
