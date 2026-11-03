"""
Installs (or removes) the Claude Status Widget.

    python install.py              copies the files, registers the hooks and opens the widget
    python install.py --startup    same + opens the widget when Windows starts
    python install.py --no-start   installs without opening the widget now
    python install.py --uninstall  removes the hooks, the startup entry and the files

What it changes (and nothing else):
  * ~/.claude/claude-status-widget/   copy of hook.py, widget.py, install.py and README.md
  * ~/.claude/settings.json           adds the widget's hooks (backed up first)
  * Windows Startup folder            ClaudeStatusWidget.vbs, only with --startup

Existing hooks are kept; only this widget's entries are replaced.
Running it again updates the installation without duplicating anything.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
SETTINGS = os.path.join(CLAUDE_DIR, "settings.json")
INSTALL_DIR = os.path.join(CLAUDE_DIR, "claude-status-widget")
QUIT_FLAG = os.path.join(INSTALL_DIR, "quit.flag")
MARKER = "claude-status-widget"
FILES = ("hook.py", "widget.py", "install.py", "README.md")
SINGLE_INSTANCE_PORT = 47653  # same as in widget.py
STARTUP_VBS = os.path.join(
    os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    "ClaudeStatusWidget.vbs",
)

# Events without a matcher | tool events (matcher "*")
PLAIN_EVENTS = ["SessionStart", "UserPromptSubmit", "Stop", "PreCompact", "SessionEnd"]
TOOL_EVENTS = ["PreToolUse", "PermissionRequest", "PostToolUse", "Notification"]


class InstallError(Exception):
    pass


# --------------------------------------------------------------------------- requirements

def check_requirements():
    if sys.platform != "win32":
        raise InstallError("This widget currently only works on Windows 10/11; macOS and Linux "
                           "are not supported yet. Nothing was changed.")
    if sys.version_info < (3, 8):
        raise InstallError(f"Python 3.8 or newer is required (this is {sys.version.split()[0]}).")
    try:
        import tkinter  # noqa: F401
    except ImportError:
        raise InstallError("This Python has no Tkinter. Install Python from python.org or the Microsoft Store.")


def python_paths():
    """Full paths of the python.exe and pythonw.exe the hooks and the widget will use."""
    exe = sys.executable
    if sys.prefix != sys.base_prefix:
        # Running inside a venv: use the base Python, which won't vanish if the venv is deleted.
        exe = getattr(sys, "_base_executable", "") or exe
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return exe, pythonw if os.path.exists(pythonw) else exe


def hook_command(python):
    # Full, quoted paths: works with spaces in the user name and
    # doesn't depend on a "python" being on the PATH.
    def norm(path):
        return path.replace("\\", "/")
    return f'"{norm(python)}" "{norm(os.path.join(INSTALL_DIR, "hook.py"))}"'


# --------------------------------------------------------------------------- settings.json

def load_settings():
    if not os.path.exists(SETTINGS):
        return {}
    try:
        # utf-8-sig: accepts a settings.json saved with a BOM (PowerShell, older Windows editors)
        with open(SETTINGS, encoding="utf-8-sig") as f:
            settings = json.load(f)
    except ValueError as e:
        raise InstallError(f"{SETTINGS} is not valid JSON ({e}). Fix the file; nothing was changed.")
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks", {}), dict):
        raise InstallError(f"{SETTINGS} has an unexpected format; nothing was changed.")
    return settings


def save_settings(settings):
    os.makedirs(CLAUDE_DIR, exist_ok=True)
    if os.path.exists(SETTINGS):
        backup = f"{SETTINGS}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(SETTINGS, backup)
        print(f"  settings.json backup: {backup}")
    # Write to a temporary file and swap it in at once: if anything fails midway,
    # the original settings.json stays intact.
    tmp = f"{SETTINGS}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, SETTINGS)


def strip_our_hooks(settings):
    """Removes only this widget's entries, keeping everything else."""
    hooks = settings.get("hooks", {})
    for event in list(hooks):
        groups = []
        for group in hooks[event] if isinstance(hooks[event], list) else []:
            if not isinstance(group, dict):
                groups.append(group)
                continue
            inner = [h for h in group.get("hooks", [])
                     if not (isinstance(h, dict) and MARKER in str(h.get("command", "")))]
            if inner:
                groups.append({**group, "hooks": inner})
        if groups:
            hooks[event] = groups
        elif isinstance(hooks[event], list):
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)


def add_our_hooks(settings, python):
    hooks = settings.setdefault("hooks", {})
    entry = {"type": "command", "command": hook_command(python), "timeout": 5}
    for event in PLAIN_EVENTS:
        hooks.setdefault(event, []).append({"hooks": [dict(entry)]})
    for event in TOOL_EVENTS:
        hooks.setdefault(event, []).append({"matcher": "*", "hooks": [dict(entry)]})


# --------------------------------------------------------------------------- running widget

def widget_running():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def stop_widget():
    """Asks the widget to close (via quit.flag) and waits up to 5 s."""
    if not widget_running():
        return
    os.makedirs(INSTALL_DIR, exist_ok=True)
    with open(QUIT_FLAG, "w", encoding="utf-8") as f:
        f.write("quit")
    for _ in range(50):
        if not widget_running():
            print("  old widget closed")
            return
        time.sleep(0.1)
    print("  warning: the old widget didn't close; quit it from the menu (right-click > Quit) and open it again")


def start_widget(pythonw):
    # cwd in the user folder: the process won't "hold on" to the folder the installer ran from.
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([pythonw, os.path.join(INSTALL_DIR, "widget.py")], cwd=os.path.expanduser("~"),
                     creationflags=flags, close_fds=True)
    print("  widget opened")


def source_version():
    try:
        out = subprocess.run(["git", "-C", HERE, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


# --------------------------------------------------------------------------- commands

def install(startup, start):
    check_requirements()
    python, pythonw = python_paths()
    settings = load_settings()  # validate before touching anything

    version = source_version()
    print(f"Installing the Claude Status Widget{f' (commit {version})' if version else ''}")
    print(f"  Python: {python}")

    stop_widget()
    os.makedirs(INSTALL_DIR, exist_ok=True)
    for name in FILES:
        src = os.path.join(HERE, name)
        dst = os.path.join(INSTALL_DIR, name)
        if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
    print(f"  files in {INSTALL_DIR}")

    strip_our_hooks(settings)
    add_our_hooks(settings, python)
    save_settings(settings)
    print(f"  hooks registered in {SETTINGS}")

    if startup:
        widget = os.path.join(INSTALL_DIR, "widget.py")
        with open(STARTUP_VBS, "w", encoding="utf-8") as f:
            f.write(f'CreateObject("WScript.Shell").Run """{pythonw}"" ""{widget}""", 0, False\n')
        print(f"  opens when Windows starts: {STARTUP_VBS}")

    if start:
        start_widget(pythonw)

    print("\nDone. Claude Code sessions that were already open may need a restart.")
    print(f'To uninstall: "{python}" "{os.path.join(INSTALL_DIR, "install.py")}" --uninstall')


def uninstall():
    stop_widget()
    if os.path.exists(SETTINGS):
        settings = load_settings()
        strip_our_hooks(settings)
        save_settings(settings)
        print("  hooks removed")
    if os.path.exists(STARTUP_VBS):
        os.remove(STARTUP_VBS)
        print("  startup entry removed")
    # Only ever deletes the widget's own folder inside ~/.claude, nothing else.
    target = os.path.realpath(INSTALL_DIR)
    if os.path.basename(target) == MARKER and os.path.dirname(target) == os.path.realpath(CLAUDE_DIR):
        shutil.rmtree(target, ignore_errors=True)
        print(f"  folder removed: {target}")
    print("\nUninstalled.")


def main():
    try:
        if "--uninstall" in sys.argv:
            uninstall()
        else:
            install(startup="--startup" in sys.argv, start="--no-start" not in sys.argv)
    except InstallError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
