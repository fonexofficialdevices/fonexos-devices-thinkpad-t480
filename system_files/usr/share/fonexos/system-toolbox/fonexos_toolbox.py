#!/usr/bin/env python3
"""
FonexOS Toolbox: an interactive, Ghost-Toolbox-style CLI for managing a
FonexOS (Fedora Atomic/bootc, Universal Blue-based) system.

Unlike earlier versions of this tool, this one does NOT wrap `ujust`.
Every action is a plain shell command (rpm-ostree, systemctl, dnf5,
flatpak, etc.) defined directly in the COMMANDS registry below. Add,
remove, or edit entries there to customize what the toolbox can do.

Usage:
    python3 fonexos_toolbox.py                 # interactive menu
    python3 fonexos_toolbox.py --list           # print all known commands
    python3 fonexos_toolbox.py --search wifi     # filter commands
    python3 fonexos_toolbox.py --about           # show OS/system info and exit
    python3 fonexos_toolbox.py <command-id>       # run one command directly
    python3 fonexos_toolbox.py --dry-run <id>      # print the command, don't run it
"""

import argparse
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

APP_TITLE = "🧰 FONEXOS TOOLBOX"
APP_SUBTITLE = "Your friendly system command center"
BOX_WIDTH = 62


# ==========================================================================
# COMMAND REGISTRY — edit/extend this to change what the toolbox can do.
# ==========================================================================
#
# Each entry:
#   id            unique short identifier, used for `fonexos_toolbox.py <id>`
#   name          display name shown in menus
#   desc          one-line description shown next to the name
#   group         category key (drives the main-menu grouping + emoji/label)
#   cmd           list[str] (argv, safest) OR a single str run via shell=True
#                 (needed only when you use pipes/redirects, e.g. "a | b")
#   requires_root if True, the command is run with sudo when not already root
#   confirm       if True, asks "Are you sure?" before running (destructive ops)
#   needs_input   optional dict: {"prompt": str} — the user's answer replaces
#                 "{input}" anywhere it appears in cmd
#
COMMANDS = [
    # -- System Maintenance ------------------------------------------------
    {
        "id": "update-system",
        "name": "Update System",
        "desc": "Pull and stage the latest FonexOS image updates",
        "group": "system",
        "cmd": ["rpm-ostree", "upgrade"],
        "requires_root": True,
    },
    {
        "id": "check-updates",
        "name": "Check for Updates",
        "desc": "Check for available updates without applying them",
        "group": "system",
        "cmd": ["rpm-ostree", "upgrade", "--check"],
        "requires_root": True,
    },
    {
        "id": "system-status",
        "name": "System Status",
        "desc": "Show current deployment, pending updates, and layered packages",
        "group": "system",
        "cmd": ["rpm-ostree", "status"],
    },
    {
        "id": "rollback",
        "name": "Rollback to Previous Deployment",
        "desc": "Revert to the previous FonexOS image deployment",
        "group": "system",
        "cmd": ["rpm-ostree", "rollback"],
        "requires_root": True,
        "confirm": True,
    },
    {
        "id": "cleanup-deployments",
        "name": "Clean Up Old Deployments",
        "desc": "Remove the rollback deployment to free up space",
        "group": "system",
        "cmd": ["rpm-ostree", "cleanup", "-p"],
        "requires_root": True,
        "confirm": True,
    },
    {
        "id": "reboot",
        "name": "Reboot System",
        "desc": "Restart the machine now",
        "group": "system",
        "cmd": ["systemctl", "reboot"],
        "requires_root": True,
        "confirm": True,
    },

    # -- App & Package Manager ----------------------------------------------
    {
        "id": "install-flatpak",
        "name": "Install Flatpak App",
        "desc": "Install an app from Flathub by its application ID",
        "group": "apps",
        "cmd": ["flatpak", "install", "-y", "flathub", "{input}"],
        "needs_input": {"prompt": "Flatpak app ID (e.g. org.mozilla.firefox): "},
    },
    {
        "id": "remove-flatpak",
        "name": "Remove Flatpak App",
        "desc": "Uninstall a Flatpak app by its application ID",
        "group": "apps",
        "cmd": ["flatpak", "uninstall", "-y", "{input}"],
        "needs_input": {"prompt": "Flatpak app ID to remove: "},
        "confirm": True,
    },
    {
        "id": "list-flatpaks",
        "name": "List Installed Flatpaks",
        "desc": "Show every Flatpak app currently installed",
        "group": "apps",
        "cmd": ["flatpak", "list"],
    },
    {
        "id": "layer-package",
        "name": "Layer an RPM Package",
        "desc": "Permanently add a package to the base image (needs reboot)",
        "group": "apps",
        "cmd": ["rpm-ostree", "install", "{input}"],
        "needs_input": {"prompt": "Package name to layer: "},
        "requires_root": True,
        "confirm": True,
    },
    {
        "id": "unlayer-package",
        "name": "Remove a Layered Package",
        "desc": "Remove a previously layered package (needs reboot)",
        "group": "apps",
        "cmd": ["rpm-ostree", "uninstall", "{input}"],
        "needs_input": {"prompt": "Layered package name to remove: "},
        "requires_root": True,
        "confirm": True,
    },

    # -- Networking -----------------------------------------------------------
    {
        "id": "restart-networkmanager",
        "name": "Restart NetworkManager",
        "desc": "Restart the NetworkManager service",
        "group": "networking",
        "cmd": ["systemctl", "restart", "NetworkManager"],
        "requires_root": True,
    },
    {
        "id": "show-network-info",
        "name": "Show Network Info",
        "desc": "Show IP addresses and interfaces",
        "group": "networking",
        "cmd": ["ip", "addr", "show"],
    },
    {
        "id": "show-connections",
        "name": "Show Active Connections",
        "desc": "List active NetworkManager connections",
        "group": "networking",
        "cmd": ["nmcli", "connection", "show"],
    },

    # -- Hardware ---------------------------------------------------------------
    {
        "id": "gpu-info",
        "name": "Show GPU Info",
        "desc": "List graphics hardware and the driver in use",
        "group": "hardware",
        "cmd": "lspci -k | grep -EA3 'VGA|3D'",
        "shell": True,
    },
    {
        "id": "cpu-info",
        "name": "Show CPU Info",
        "desc": "Show CPU model, core, and thread details",
        "group": "hardware",
        "cmd": ["lscpu"],
    },
    {
        "id": "disk-usage",
        "name": "Show Disk Usage",
        "desc": "Show free/used space on mounted filesystems",
        "group": "hardware",
        "cmd": ["df", "-h"],
    },
    {
        "id": "sensors",
        "name": "Show Temperatures & Sensors",
        "desc": "Show CPU/GPU temps and fan speeds (needs lm_sensors)",
        "group": "hardware",
        "cmd": ["sensors"],
    },

    # -- Diagnostics ------------------------------------------------------------
    {
        "id": "recent-logs",
        "name": "View Recent System Logs",
        "desc": "Show the last 50 lines of the system journal",
        "group": "diagnostics",
        "cmd": ["journalctl", "-n", "50", "--no-pager"],
    },
    {
        "id": "boot-log",
        "name": "View Current Boot Log",
        "desc": "Show logs from the current boot",
        "group": "diagnostics",
        "cmd": "journalctl -b --no-pager | tail -100",
        "shell": True,
    },
]


# --------------------------------------------------------------------------
# Friendly category + command styling
# --------------------------------------------------------------------------

CATEGORY_STYLE = {
    "system": ("🖥️", "System Maintenance"),
    "apps": ("📦", "App & Package Manager"),
    "networking": ("🌐", "Networking"),
    "hardware": ("🎮", "Hardware"),
    "diagnostics": ("🩺", "Diagnostics"),
    "privacy": ("🔒", "Privacy & Security"),
    "general": ("🧰", "General Tools"),
}
FALLBACK_EMOJIS = ["🧩", "🛠️", "⚙️", "📂", "✨"]


def friendly_group_label(raw_name):
    key = raw_name.lower()
    for keyword, (emoji, label) in CATEGORY_STYLE.items():
        if keyword in key:
            return emoji, label
    idx = sum(ord(ch) for ch in key) % len(FALLBACK_EMOJIS)
    return FALLBACK_EMOJIS[idx], raw_name.replace("-", " ").replace("_", " ").title()


COMMAND_EMOJI_KEYWORDS = {
    "update": "⬆️", "upgrade": "⬆️",
    "install": "📥", "layer": "📥",
    "remove": "🗑️", "uninstall": "🗑️", "unlayer": "🗑️", "cleanup": "🗑️",
    "rollback": "⏪",
    "reboot": "🔁", "restart": "🔁",
    "status": "📋", "check": "🔍",
    "network": "🌐", "connection": "🌐", "ip": "🌐",
    "gpu": "🎮", "cpu": "🧮",
    "disk": "💽",
    "sensor": "🌡️", "temperature": "🌡️",
    "log": "🩺", "boot": "🥾",
    "flatpak": "📦",
}


def command_emoji(entry):
    text = f"{entry['name']} {entry['desc']}".lower()
    for keyword, emoji in COMMAND_EMOJI_KEYWORDS.items():
        if keyword in text:
            return emoji
    return "▶️"


def group_commands(commands):
    groups = {}
    for cmd in commands:
        groups.setdefault(cmd["group"], []).append(cmd)
    return list(groups.items())


def filter_commands(commands, term):
    term = term.lower()
    return [
        c for c in commands
        if term in c["name"].lower()
        or term in c["desc"].lower()
        or term in c["group"].lower()
        or term in c["id"].lower()
    ]


# --------------------------------------------------------------------------
# Toolbox-style terminal UI (banner, boxed menus, colors)
# --------------------------------------------------------------------------

class Ansi:
    ENABLED = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    RESET = "\033[0m" if ENABLED else ""
    BOLD = "\033[1m" if ENABLED else ""
    DIM = "\033[2m" if ENABLED else ""
    CYAN = "\033[36m" if ENABLED else ""
    GREEN = "\033[32m" if ENABLED else ""
    YELLOW = "\033[33m" if ENABLED else ""
    RED = "\033[31m" if ENABLED else ""
    MAGENTA = "\033[35m" if ENABLED else ""
    WHITE = "\033[97m" if ENABLED else ""


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def hr(char="=", width=BOX_WIDTH):
    return char * width


def print_banner():
    c = Ansi
    print(c.CYAN + hr("═") + c.RESET)
    print(c.CYAN + "║" + c.RESET + c.BOLD + c.WHITE + APP_TITLE.center(BOX_WIDTH - 2) + c.RESET + c.CYAN + "║" + c.RESET)
    print(c.CYAN + "║" + c.RESET + c.DIM + APP_SUBTITLE.center(BOX_WIDTH - 2) + c.RESET + c.CYAN + "║" + c.RESET)
    print(c.CYAN + hr("═") + c.RESET)


def print_section(title):
    c = Ansi
    print()
    print(c.YELLOW + f" {title} ".center(BOX_WIDTH, "-") + c.RESET)


def pause():
    input(Ansi.DIM + "\n⏎ Press Enter to continue..." + Ansi.RESET)


def render_menu(title, items, footer_options):
    c = Ansi
    clear_screen()
    print_banner()
    print_section(title)
    for i, (label, sublabel) in enumerate(items, start=1):
        num = c.GREEN + f"{i:>3}" + c.RESET
        desc = f"{c.DIM} — {sublabel}{c.RESET}" if sublabel else ""
        print(f" {num}. {c.WHITE}{label}{c.RESET}{desc}")
    print(c.CYAN + hr("-") + c.RESET)
    for key, desc in footer_options:
        print(f" {c.MAGENTA}[{key}]{c.RESET} {desc}   ", end="")
    print("\n")


# --------------------------------------------------------------------------
# Running commands
# --------------------------------------------------------------------------

def is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


def binary_name(entry):
    if entry.get("shell"):
        return entry["cmd"].split()[0]
    return entry["cmd"][0]


def build_command(entry, user_value=None):
    """Resolve an entry's cmd (substituting {input}, prepending sudo)."""
    if entry.get("shell"):
        cmd = entry["cmd"]
        if user_value is not None:
            cmd = cmd.replace("{input}", user_value)
        if entry.get("requires_root") and not is_root():
            cmd = "sudo " + cmd
        return cmd, True

    cmd = list(entry["cmd"])
    if user_value is not None:
        cmd = [part.replace("{input}", user_value) if "{input}" in part else part for part in cmd]
    if entry.get("requires_root") and not is_root():
        cmd = ["sudo"] + cmd
    return cmd, False


def run_shell(cmd, use_shell):
    c = Ansi
    printable = cmd if use_shell else " ".join(cmd)
    print(c.DIM + f"$ {printable}" + c.RESET + "\n")
    try:
        code = subprocess.run(cmd, shell=use_shell).returncode
        status = (c.GREEN + "✅ Done.") if code == 0 else (c.RED + f"❌ Exited with code {code}.")
        print("\n" + status + c.RESET)
        return code
    except FileNotFoundError:
        missing = cmd.split()[0] if use_shell else cmd[0]
        print(
            c.RED + f"❌ '{missing}' was not found on this system.\n"
            "This command is designed for FonexOS (Fedora Atomic/bootc). "
            "If you're testing elsewhere, that tool may not be installed here."
            + c.RESET,
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print(c.YELLOW + "\n⚠️ Interrupted." + c.RESET)
        return 130


def confirm_prompt(entry):
    c = Ansi
    print(c.YELLOW + f"⚠️  '{entry['name']}' can make significant changes to your system." + c.RESET)
    answer = input("Type YES to confirm, anything else to cancel: ").strip()
    return answer == "YES"


def run_entry(entry, dry_run=False):
    """Handle needs_input / confirm, then build and run (or print) the command."""
    user_value = None
    if entry.get("needs_input"):
        user_value = input(entry["needs_input"]["prompt"]).strip()
        if not user_value:
            print(Ansi.RED + "❌ Cancelled — no value entered." + Ansi.RESET)
            return 1

    if entry.get("confirm") and not dry_run:
        if not confirm_prompt(entry):
            print(Ansi.YELLOW + "Cancelled." + Ansi.RESET)
            return 1

    cmd, use_shell = build_command(entry, user_value)

    if dry_run:
        printable = cmd if use_shell else " ".join(cmd)
        print(Ansi.CYAN + f"[dry-run] {printable}" + Ansi.RESET)
        return 0

    return run_shell(cmd, use_shell)


# --------------------------------------------------------------------------
# Screens
# --------------------------------------------------------------------------

def run_screen(entry):
    c = Ansi
    clear_screen()
    print_banner()
    print_section(f"{command_emoji(entry)} {entry['name']}")
    if entry["desc"]:
        print(c.DIM + entry["desc"] + c.RESET + "\n")
    run_entry(entry)
    pause()


def category_screen(group_name, commands, all_commands):
    emoji, friendly_name = friendly_group_label(group_name)
    while True:
        items = [(f"{command_emoji(c)} {c['name']}", c["desc"]) for c in commands]
        render_menu(
            f"{emoji} {friendly_name}",
            items,
            footer_options=[
                ("0", "🔙 Back to Main Menu"),
                ("/term", "🔍 Search Here"),
                ("q", "🚪 Quit"),
            ],
        )
        choice = input("👉 Select an option: ").strip()

        if choice.lower() in ("q", "quit", "exit"):
            sys.exit(0)
        if choice in ("0", "b", "back"):
            return
        if choice.startswith("/"):
            search_screen(all_commands, preset_term=choice[1:])
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(commands):
            run_screen(commands[int(choice) - 1])
            continue

        print(Ansi.RED + f"❌ '{choice}' is not a valid option." + Ansi.RESET)
        pause()


def search_screen(all_commands, preset_term=None):
    term = preset_term if preset_term is not None else ""
    while True:
        if not preset_term:
            clear_screen()
            print_banner()
            print_section("🔎 Search Commands")
            term = input("🔎 Search term (blank to cancel): ").strip()
            if not term:
                return

        results = filter_commands(all_commands, term)
        items = []
        for c in results:
            group_emoji, group_label = friendly_group_label(c["group"])
            items.append((f"{command_emoji(c)} {c['name']}", f"[{group_emoji} {group_label}] {c['desc']}"))
        render_menu(
            f"🔎 Results for '{term}'",
            items,
            footer_options=[("0", "🔙 Back"), ("q", "🚪 Quit")],
        )
        choice = input("👉 Select an option: ").strip()

        if choice.lower() in ("q", "quit", "exit"):
            sys.exit(0)
        if choice in ("0", "b", "back"):
            return
        if choice.isdigit() and results and 1 <= int(choice) <= len(results):
            run_screen(results[int(choice) - 1])
            if preset_term:
                return
            continue

        print(Ansi.RED + f"❌ '{choice}' is not a valid option." + Ansi.RESET)
        pause()
        if preset_term:
            return


# --------------------------------------------------------------------------
# About System
# --------------------------------------------------------------------------

OS_RELEASE_PATH = Path("/etc/os-release")


def read_os_release(path=OS_RELEASE_PATH):
    data = {}
    try:
        text = path.read_text()
    except OSError:
        return data
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def _read_uptime_seconds():
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _format_uptime(seconds):
    if seconds is None:
        return "Unknown"
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _read_meminfo():
    try:
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    info[key] = int(rest.strip().split()[0])
        to_gb = lambda kb: round(kb / (1024 * 1024), 1) if kb is not None else None
        return to_gb(info.get("MemTotal")), to_gb(info.get("MemAvailable"))
    except (OSError, ValueError, KeyError):
        return None, None


def gather_system_info():
    os_release = read_os_release()
    total_mem, avail_mem = _read_meminfo()
    uptime = _format_uptime(_read_uptime_seconds())

    return {
        "os_name": os_release.get("PRETTY_NAME") or os_release.get("NAME") or platform.system(),
        "version": os_release.get("VERSION") or os_release.get("VERSION_ID") or "Unknown",
        "id": os_release.get("ID", "unknown"),
        "id_like": os_release.get("ID_LIKE", ""),
        "build_id": os_release.get("BUILD_ID", ""),
        "variant": os_release.get("VARIANT", ""),
        "home_url": os_release.get("HOME_URL", ""),
        "hostname": socket.gethostname(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "cpu_count": os.cpu_count() or "Unknown",
        "total_memory_gb": total_mem,
        "available_memory_gb": avail_mem,
        "uptime": uptime,
        "os_release_found": bool(os_release),
    }


def about_screen(interactive=True):
    c = Ansi
    info = gather_system_info()

    if interactive:
        clear_screen()
    print_banner()
    print_section("ℹ️  About This System")

    if not info["os_release_found"]:
        print(c.YELLOW + "⚠️  /etc/os-release not found — showing what's available." + c.RESET + "\n")

    rows = [
        ("🏷️  OS", info["os_name"]),
        ("🔢 Version", info["version"]),
        ("🆔 ID", info["id"] + (f" (like {info['id_like']})" if info["id_like"] else "")),
    ]
    if info["variant"]:
        rows.append(("🧩 Variant", info["variant"]))
    if info["build_id"]:
        rows.append(("🏗️  Build", info["build_id"]))
    rows += [
        ("💻 Hostname", info["hostname"]),
        ("🐧 Kernel", info["kernel"]),
        ("🏛️  Architecture", info["architecture"]),
        ("🧮 CPU Cores", str(info["cpu_count"])),
    ]
    if info["total_memory_gb"] is not None:
        rows.append(("🧠 Memory", f"{info['available_memory_gb']} GB free / {info['total_memory_gb']} GB total"))
    rows.append(("⏱️  Uptime", info["uptime"]))
    if info["home_url"]:
        rows.append(("🔗 Homepage", info["home_url"]))

    label_width = max(len(label) for label, _ in rows) + 1
    for label, value in rows:
        print(f" {c.WHITE}{label:<{label_width}}{c.RESET} {c.DIM}{value}{c.RESET}")

    print(c.CYAN + "\n" + hr("-") + c.RESET)
    if interactive:
        pause()


# --------------------------------------------------------------------------
# Main menu / entry point
# --------------------------------------------------------------------------

def main_menu(commands):
    groups = group_commands(commands)
    while True:
        items = []
        for name, cmds in groups:
            emoji, friendly_name = friendly_group_label(name)
            items.append((f"{emoji} {friendly_name}", f"{len(cmds)} command(s)"))
        render_menu(
            "🏠 Main Menu",
            items,
            footer_options=[("/term", "🔎 Search All"), ("i", "ℹ️  About System"), ("q", "🚪 Quit")],
        )
        choice = input("👉 Select a category: ").strip()

        if choice.lower() in ("q", "quit", "exit"):
            print(Ansi.CYAN + "\n👋 See ya!" + Ansi.RESET)
            return
        if choice.lower() in ("i", "info", "about"):
            about_screen()
            continue
        if choice.startswith("/"):
            search_screen(commands, preset_term=choice[1:] or None)
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(groups):
            name, cmds = groups[int(choice) - 1]
            category_screen(name, cmds, commands)
            continue

        print(Ansi.RED + f"❌ '{choice}' is not a valid option." + Ansi.RESET)
        pause()


def print_commands_plain(commands):
    if not commands:
        print("No commands found.")
        return
    groups = {}
    for cmd in commands:
        groups.setdefault(cmd["group"], []).append(cmd)
    for group, cmds in groups.items():
        _, label = friendly_group_label(group)
        print(f"\n[{label}]")
        for c in cmds:
            print(f"  {c['id']:<24} {c['name']} - {c['desc']}")


def main():
    parser = argparse.ArgumentParser(description="FonexOS Toolbox — a friendly CLI for managing your system.")
    parser.add_argument("command_id", nargs="?", help="Run this command directly by its id and exit.")
    parser.add_argument("--list", action="store_true", help="List all available commands and exit.")
    parser.add_argument("--search", metavar="TERM", help="Filter commands by name/description.")
    parser.add_argument("--about", action="store_true", help="Show system/OS info and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved command instead of running it.")
    args = parser.parse_args()

    if args.about:
        about_screen(interactive=False)
        return

    if args.list:
        print_commands_plain(COMMANDS)
        return

    if args.search:
        print_commands_plain(filter_commands(COMMANDS, args.search))
        return

    if args.command_id:
        matching = [c for c in COMMANDS if c["id"] == args.command_id]
        if not matching:
            print(f"'{args.command_id}' is not a recognized command id.\n")
            print_commands_plain(filter_commands(COMMANDS, args.command_id))
            sys.exit(1)
        sys.exit(run_entry(matching[0], dry_run=args.dry_run))

    main_menu(COMMANDS)


if __name__ == "__main__":
    main()
