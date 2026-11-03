"""
Widget that shows the state of Claude Code in real time.

Reads the files written by hook.py in ~/.claude/claude-status-widget/sessions/
and shows the most urgent session (waiting > thinking > idle).

Two modes:
    floating   free window, always on top, anywhere on the screen
    taskbar    one dot on every taskbar (every monitor), just left of the Start button

Usage:
    pythonw widget.py              (no console window, uses the last mode)
    python  widget.py --taskbar    (switches to taskbar mode and saves it)
    python  widget.py --floating   (switches to floating mode and saves it)
    python  widget.py --demo       (cycles through the states, to test the look)

Controls:
    drag with the left button  -> move (on the taskbar, horizontally only)
    double-click               -> compact mode (just the dot)
    right-click                -> menu (sessions, mode, sound, quit)
"""
import json
import math
import os
import socket
import sys
import time
import tkinter as tk
import tkinter.font as tkfont

CLAUDE_DIR = os.path.realpath(os.path.join(os.path.expanduser("~"), ".claude"))
BASE_DIR = os.path.join(CLAUDE_DIR, "claude-status-widget")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
CONFIG_PATH = os.path.join(BASE_DIR, "widget_config.json")
QUIT_FLAG = os.path.join(BASE_DIR, "quit.flag")  # created by the installer to close the widget on update

POLL_MS = 400              # reading the session files
FRAME_MS = 33              # animation (~30 fps)
TASKBAR_MS = 250           # finds the taskbars, repositions and re-asserts "on top of the taskbar"
STALE_SECONDS = 8 * 3600   # sessions with no events for longer than this are ignored
INACTIVE_SECONDS = 30 * 60  # "thinking" with no hook event or transcript write for this long counts as ready
SINGLE_INSTANCE_PORT = 47653

TRANSPARENT = "#ff00fe"    # key color that Windows makes transparent (rounded corners)

THEMES = {
    "floating":      {"bg": "#1e1e22", "border": "#34343c", "text": "#f2f2f2", "sub": "#9a9aa5"},
    "taskbar_dark":  {"bg": "#2c2c2c", "border": "#2c2c2c", "text": "#ffffff", "sub": "#ababab"},
    "taskbar_light": {"bg": "#e4e4e4", "border": "#e4e4e4", "text": "#1b1b1b", "sub": "#5f5f5f"},
}

STATES = {
    "thinking": {"label": "Thinking", "color": "#d97757", "priority": 2},
    "waiting":  {"label": "Waiting for you", "color": "#f5b942", "priority": 3},
    "idle":     {"label": "Ready", "color": "#4ade80", "priority": 1},
    "offline":  {"label": "No session", "color": "#6b6b75", "priority": 0},
}

INTERRUPT_MARKER = "[Request interrupted by user"

# Taskbar window class -> its child holding the app icons, which starts at the Start button.
TASKBARS = {"Shell_TrayWnd": "ReBarWindow32", "Shell_SecondaryTrayWnd": "WorkerW"}


# --------------------------------------------------------------------------- Windows

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.FindWindowExW.restype = wintypes.HWND
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND] + [ctypes.c_int] * 4 + [wintypes.UINT]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    try:
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    except AttributeError:  # Windows older than 10 1607
        pass
    try:
        dwmapi = ctypes.windll.dwmapi
        dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    except OSError:
        dwmapi = None

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
else:
    user32 = None


def window_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def class_name(hwnd):
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, 64)
    return buf.value


def monitor_rect(hwnd):
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info))
    m = info.rcMonitor
    return m.left, m.top, m.right, m.bottom


def taskbar_windows():
    """Every visible taskbar (one per monitor) as {hwnd: window class}."""
    found = {}

    def collect(hwnd, _):
        cls = class_name(hwnd)
        if cls in TASKBARS and user32.IsWindowVisible(hwnd):
            found[hwnd] = cls
        return True

    if user32:
        user32.EnumWindows(EnumWindowsProc(collect), 0)
    return found


def apps_area(taskbar, cls):
    """Rect of the taskbar's app icons, which starts at the Start button; None if not found."""
    hwnd = user32.FindWindowExW(taskbar, None, TASKBARS[cls], None)
    if not hwnd or not user32.IsWindowVisible(hwnd):
        return None
    rect = window_rect(hwnd)
    return rect if rect[2] > rect[0] else None


# Shell windows that can cover a whole monitor without hiding the taskbar.
SHELL_OVERLAYS = {"Progman", "WorkerW", "XamlExplorerHostIslandWindow", "MultitaskingViewFrame",
                  "ForegroundStaging", "Windows.UI.Core.CoreWindow", *TASKBARS}


class physical_pixels:
    """Measures in real pixels while active, so monitors with different scaling compare exactly."""

    def __enter__(self):
        try:
            self.old = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2
        except AttributeError:  # Windows older than 10 1607
            self.old = None
        return self

    def __exit__(self, *exc):
        if self.old:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(self.old))


def can_cover_taskbar(hwnd):
    """A real, visible app window: not ours, not minimized, cloaked, click-through or a shell overlay."""
    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return False
    ex_style = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
    if ex_style & 0x20 or ex_style & 0x80:  # WS_EX_TRANSPARENT (overlays), WS_EX_TOOLWINDOW
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():
        return False
    if dwmapi:
        cloaked = ctypes.c_int(0)
        dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))  # DWMWA_CLOAKED
        if cloaked.value:
            return False
    return class_name(hwnd) not in SHELL_OVERLAYS


def fullscreen_taskbars(taskbars):
    """Taskbars that a fullscreen window (video, game...) is hiding, the way Windows hides them.

    Walks the windows from the top of the z-order down to each taskbar: a window above
    the taskbar that covers its whole monitor means the taskbar is out of sight.
    """
    pending = set(taskbars)
    covered = set()
    if not pending:
        return covered
    tolerance = 2  # pixels; borderless fullscreen windows are sometimes off by one

    with physical_pixels():
        monitors = {tb: monitor_rect(tb) for tb in pending}

        def visit(hwnd, _):
            if hwnd in pending:  # reached this taskbar: windows below it can't hide it
                pending.discard(hwnd)
                return bool(pending)
            if not can_cover_taskbar(hwnd):
                return True
            left, top, right, bottom = window_rect(hwnd)
            for tb in list(pending):
                m = monitors[tb]
                if (left <= m[0] + tolerance and top <= m[1] + tolerance
                        and right >= m[2] - tolerance and bottom >= m[3] - tolerance):
                    covered.add(tb)
                    pending.discard(tb)
            return bool(pending)

        user32.EnumWindows(EnumWindowsProc(visit), 0)
    return covered


def light_taskbar():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "SystemUsesLightTheme")[0] == 1
    except OSError:
        return False


# --------------------------------------------------------------------------- data

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def inside_claude_dir(path):
    """Only Claude Code's own transcripts are read, never an arbitrary path taken from the JSON."""
    try:
        real = os.path.realpath(path)
        return real.endswith(".jsonl") and os.path.commonpath([real, CLAUDE_DIR]) == CLAUDE_DIR
    except ValueError:  # different drives, invalid path
        return False


def transcript_mtime(session):
    path = session["transcript_path"]
    if not path or not inside_claude_dir(path):
        return 0.0
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def was_interrupted(session, cache):
    """Esc in Claude Code doesn't fire the Stop hook; we detect it from the end of the transcript."""
    path = session["transcript_path"]
    if not path or not inside_claude_dir(path):
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if mtime <= session["updated"]:
        return None
    cached = cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    result = None
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - 6000))
            tail = f.read().decode("utf-8", "ignore")
        last_lines = [line for line in tail.splitlines() if line.strip()][-3:]
        if any(INTERRUPT_MARKER in line for line in last_lines):
            result = mtime
    except OSError:
        pass
    cache[path] = (mtime, result)
    return result


def clean_session(raw, filename):
    """Accepts only the expected fields and types; an odd JSON is ignored instead of crashing the widget."""
    if not isinstance(raw, dict) or raw.get("state") not in STATES or raw["state"] == "offline":
        return None

    def number(value):
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        return float(value) if ok else None

    def text(value):
        return value if isinstance(value, str) else ""

    updated = number(raw.get("updated"))
    if updated is None:
        return None
    since = number(raw.get("since"))
    return {
        "file": filename,
        "state": raw["state"],
        "detail": text(raw.get("detail"))[:120],
        "cwd": text(raw.get("cwd")),
        "transcript_path": text(raw.get("transcript_path")),
        "updated": updated,
        "since": since if since is not None else updated,
    }


def read_sessions(interrupt_cache):
    sessions = []
    now = time.time()
    try:
        names = os.listdir(SESSIONS_DIR)
    except OSError:
        return sessions
    for name in names:
        if not name.endswith(".json"):
            continue
        s = clean_session(load_json(os.path.join(SESSIONS_DIR, name), None), name)
        if s is None or now - s["updated"] > STALE_SECONDS:
            continue
        if s["state"] != "idle":
            interrupted_at = was_interrupted(s, interrupt_cache)
            if interrupted_at:
                s.update(state="idle", detail="interrupted", since=interrupted_at)
        if s["state"] == "thinking":
            # A missed Stop (Claude Code closed abruptly, an event lost) would leave the dot
            # orange forever; real work keeps firing hooks or writing the transcript.
            last_activity = max(s["updated"], transcript_mtime(s))
            if now - last_activity > INACTIVE_SECONDS:
                s.update(state="idle", detail="inactive", since=last_activity)
        sessions.append(s)
    sessions.sort(key=lambda s: (-STATES[s["state"]]["priority"], -s["updated"]))
    return sessions


def project_name(session):
    cwd = session.get("cwd") or ""
    return os.path.basename(cwd.rstrip("\\/")) or cwd or "session"


def fmt_elapsed(seconds):
    seconds = int(max(0, seconds))
    if seconds < 3600:
        return f"{seconds // 60}:{seconds % 60:02d}"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}"


def blend(c1, c2, t):
    """Blends two hex colors; t=0 -> c1, t=1 -> c2."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


# --------------------------------------------------------------------------- widget

class View:
    """One visible window of the widget: the floating one, or the dot on one taskbar."""

    def __init__(self, app, taskbar=None, cls=None):
        self.app = app
        self.taskbar = taskbar
        self.cls = cls
        self.height = int(48 * app.s)  # height of its taskbar
        self.hidden = False
        self.last_geometry = None

        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)  # borderless and not shown in the taskbar
        self.win.configure(bg=TRANSPARENT)
        try:
            self.win.wm_attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass  # outside Windows: corners stay square
        self.win.wm_attributes("-topmost", True if taskbar else app.topmost.get())

        self.canvas = tk.Canvas(self.win, bg=TRANSPARENT, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", lambda e: app.start_drag(e, self))
        self.canvas.bind("<B1-Motion>", lambda e: app.on_drag(e, self))
        self.canvas.bind("<ButtonRelease-1>", lambda e: app.save_config())
        self.canvas.bind("<Double-Button-1>", lambda e: app.toggle_compact())
        self.canvas.bind("<Button-3>", app.show_menu)

    def show(self, visible):
        if visible and self.hidden:
            self.win.deiconify()
            self.hidden = False
            self.last_geometry = None
        elif not visible and not self.hidden:
            self.win.withdraw()
            self.hidden = True

    def move(self, w, h, x, y):
        if (w, h, x, y) != self.last_geometry:
            self.win.geometry(f"{w}x{h}+{x}+{y}")
            self.canvas.config(width=w, height=h)
            self.last_geometry = (w, h, x, y)
            return
        # Windows moves windows by itself when monitors are rearranged or (dis)connected.
        # Tk ignores a geometry it already set, so put the window back directly.
        actual = (self.win.winfo_width(), self.win.winfo_height(), self.win.winfo_x(), self.win.winfo_y())
        if actual != (w, h, x, y) and user32 and self.win.winfo_ismapped():
            SWP_NOZORDER, SWP_NOACTIVATE = 0x4, 0x10
            user32.SetWindowPos(int(self.win.wm_frame(), 16), None, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE)

    def destroy(self):
        self.win.destroy()


class StatusWidget:
    def __init__(self, demo=False, mode=None):
        self.demo = demo
        self.config = load_json(CONFIG_PATH, {})
        if not isinstance(self.config, dict):
            self.config = {}
        if mode:
            self.config["mode"] = mode
        self.sessions = []
        self.current = {"state": "offline"}
        self.last_state = "offline"
        self.interrupt_cache = {}
        self.t0 = time.time()
        self.menu_open = False
        self.views = {}  # taskbar hwnd (or "floating") -> View
        self.covered = set()  # taskbars a fullscreen window is hiding

        # The root window stays hidden; each visible window is a View.
        self.root = tk.Tk()
        self.root.title("Claude Status")
        self.root.withdraw()

        # Scale for high-DPI monitors (Tk scales fonts, but not canvas pixels).
        self.s = max(1.0, float(self.root.tk.call("tk", "scaling")) / (96 / 72))

        # Default for a fresh install: just the dot, on the taskbar.
        self.on_taskbar = tk.BooleanVar(value=self.config.get("mode", "taskbar") == "taskbar" and user32 is not None)
        self.topmost = tk.BooleanVar(value=self.config.get("topmost", True))
        self.beep = tk.BooleanVar(value=self.config.get("beep", False))
        self.compact = self.config.get("compact", True)
        self.update_theme()

        self.title_font = tkfont.Font(family="Segoe UI Semibold", size=10)
        self.sub_font = tkfont.Font(family="Segoe UI", size=8)

        self.layout()
        if mode:
            self.save_config()
        self.poll()
        self.animate()
        self.taskbar_tick()

    # ---- geometry and settings

    def update_theme(self):
        if self.on_taskbar.get():
            self.theme = THEMES["taskbar_light" if light_taskbar() else "taskbar_dark"]
        else:
            self.theme = THEMES["floating"]

    def size(self, view):
        s = self.s
        if view.taskbar:
            h = max(int(24 * s), view.height - int(10 * s))
            return (h, h) if self.compact else (int(230 * s), h)
        return (int(36 * s), int(36 * s)) if self.compact else (int(250 * s), int(52 * s))

    def layout(self):
        """Creates or removes views so there is one per taskbar (or a single floating one)."""
        wanted = taskbar_windows() if self.on_taskbar.get() else {"floating": None}
        for key in list(self.views):
            if key not in wanted:
                self.views.pop(key).destroy()
        for key, cls in wanted.items():
            if key not in self.views:
                taskbar = None if key == "floating" else key
                self.views[key] = View(self, taskbar, cls)
                if not taskbar:
                    self.place_floating(self.views[key])

    def place_floating(self, view):
        w, h = self.size(view)
        sw = self.root.winfo_screenwidth()
        x = self.config_int("x", sw - w - int(24 * self.s))
        y = self.config_int("y", int(24 * self.s))
        x = min(max(0, x), sw - w)
        y = min(max(0, y), self.root.winfo_screenheight() - h)
        view.last_geometry = None
        view.move(w, h, x, y)

    def place_on_taskbar(self, view):
        """Docks the view over its taskbar, just left of the Start button, and keeps it on top."""
        left, top, right, bottom = window_rect(view.taskbar)
        bottom = min(bottom, monitor_rect(view.taskbar)[3])
        # an auto-hidden taskbar sits almost entirely off screen
        visible = bottom - top > 20 and view.taskbar not in self.covered
        view.show(visible)
        if not visible:
            return

        view.height = bottom - top
        w, h = self.size(view)
        view.move(w, h, self.taskbar_x(view, left, w), top + (view.height - h) // 2)

        # Clicking the taskbar brings it to the front; we re-assert "always on top".
        # Not while the menu is open: the widget would cover it and hide options.
        if self.menu_open:
            return
        HWND_TOPMOST, SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = -1, 0x1, 0x2, 0x10
        hwnd = int(view.win.wm_frame(), 16)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)

    def taskbar_x(self, view, left, w):
        """Just left of the Start button, between it and the weather widget, on any monitor."""
        nearest = left
        apps = apps_area(view.taskbar, view.cls)
        if apps:
            nearest = apps[0] - int(8 * self.s) - w
        if nearest <= left:
            # Start button at the very left (left-aligned taskbar): fall back to a fixed spot.
            return left + max(0, self.config_int("taskbar_offset", 0))
        return max(left, nearest - max(0, self.config_int("start_offset", 0)))

    def taskbar_tick(self):
        if self.on_taskbar.get() and not self.menu_open:
            self.layout()
            self.covered = fullscreen_taskbars([v.taskbar for v in self.views.values() if v.taskbar])
            for view in self.views.values():
                self.place_on_taskbar(view)
        self.root.after(TASKBAR_MS, self.taskbar_tick)

    def config_int(self, key, default):
        value = self.config.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else default

    def save_config(self):
        self.config.update(
            mode="taskbar" if self.on_taskbar.get() else "floating",
            topmost=self.topmost.get(), beep=self.beep.get(), compact=self.compact,
        )
        floating = self.views.get("floating")
        if floating and floating.win.winfo_ismapped():
            self.config.update(x=floating.win.winfo_x(), y=floating.win.winfo_y())
        try:
            os.makedirs(BASE_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f)
        except OSError:
            pass

    def refresh(self):
        for view in self.views.values():
            if view.taskbar:
                self.place_on_taskbar(view)
            else:
                self.place_floating(view)

    def toggle_compact(self):
        self.compact = not self.compact
        self.refresh()
        self.save_config()

    def toggle_taskbar(self):
        self.update_theme()
        self.layout()
        self.refresh()
        self.save_config()

    def start_drag(self, event, view):
        self.drag_offset = (event.x, event.y)

    def on_drag(self, event, view):
        dx, dy = self.drag_offset
        x = event.x_root - dx
        if view.taskbar:
            # The distance from the Start button is shared by the dots on every taskbar.
            apps = apps_area(view.taskbar, view.cls)
            left = window_rect(view.taskbar)[0]
            nearest = apps[0] - int(8 * self.s) - self.size(view)[0] if apps else left
            if nearest > left:
                self.config["start_offset"] = nearest - x
            else:
                self.config["taskbar_offset"] = x - left
            self.place_on_taskbar(view)
        else:
            view.win.geometry(f"+{x}+{event.y_root - dy}")

    # ---- context menu

    def show_menu(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        if self.sessions:
            for s in self.sessions:
                label = f"{STATES[s['state']]['label']}  ·  {project_name(s)}"
                if s.get("detail"):
                    label += f"  ·  {s['detail']}"
                menu.add_command(label=label[:70], state="disabled")
        else:
            menu.add_command(label="No active Claude Code session", state="disabled")
        menu.add_separator()
        if user32:
            menu.add_checkbutton(label="Pin to taskbar", variable=self.on_taskbar,
                                 command=self.toggle_taskbar)
        if not self.on_taskbar.get():
            menu.add_checkbutton(label="Always on top", variable=self.topmost, command=self.on_topmost)
        menu.add_checkbutton(label="Sound when waiting for you", variable=self.beep, command=self.save_config)
        menu.add_command(label="Compact / normal mode", command=self.toggle_compact)
        menu.add_command(label="Clear old sessions", command=self.clear_idle_sessions)
        menu.add_separator()
        menu.add_command(label="Quit", command=self.quit)
        # On Windows, tk_popup only returns once the menu closes.
        self.menu_open = True
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
            self.menu_open = False

    def on_topmost(self):
        floating = self.views.get("floating")
        if floating:
            floating.win.wm_attributes("-topmost", self.topmost.get())
        self.save_config()

    def clear_idle_sessions(self):
        # Deletes by the name os.listdir returned, never by an id read from inside the JSON.
        for s in self.sessions:
            if s["state"] == "idle" and s.get("file"):
                try:
                    os.remove(os.path.join(SESSIONS_DIR, s["file"]))
                except OSError:
                    pass

    def quit(self):
        self.save_config()
        self.root.destroy()

    def quit_requested(self):
        """The installer asks the widget to close (on update or uninstall) by creating quit.flag."""
        try:
            requested = os.path.getmtime(QUIT_FLAG) >= self.t0 - 1
            os.remove(QUIT_FLAG)
        except OSError:
            return False
        if requested:
            self.quit()
        return requested

    # ---- state

    def poll(self):
        if self.quit_requested():
            return
        if self.demo:
            order = ["thinking", "waiting", "idle"]
            state = order[int((time.time() - self.t0) // 4) % 3]
            self.sessions = [{"state": state, "cwd": "demo", "detail": "demo mode", "since": self.t0}]
        else:
            self.sessions = read_sessions(self.interrupt_cache)

        self.current = self.sessions[0] if self.sessions else {"state": "offline"}
        state = self.current["state"]
        if state == "waiting" and self.last_state != "waiting" and self.beep.get():
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        self.last_state = state
        self.root.after(POLL_MS, self.poll)

    # ---- drawing

    def animate(self):
        t = time.time()
        for view in self.views.values():
            if not view.hidden:
                self.draw(view, t)
        self.root.after(FRAME_MS, self.animate)

    def draw(self, view, t):
        c = view.canvas
        c.delete("all")
        w, h = self.size(view)
        s = self.s
        bg = self.theme["bg"]
        state = self.current["state"]
        color = STATES[state]["color"]

        # In compact mode only the dot shows: the background is fully transparent.
        if not self.compact:
            r = 8 * s if view.taskbar else h / 2 - 1
            x1, y1, x2, y2 = 1, 1, w - 2, h - 2
            pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
                   x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
            c.create_polygon(pts, smooth=True, fill=bg, outline=self.theme["border"])

        cx, cy = (w / 2, h / 2) if self.compact else (h / 2 + 2 * s, h / 2)
        r = 7 * s

        if state == "thinking":
            # pulsing dot + arc spinning around it
            pulse = (math.sin(t * 4) + 1) / 2
            rr = r * (0.8 + 0.25 * pulse)
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=color, outline="")
            ring = r + 5 * s
            start = (t * 360) % 360
            c.create_arc(cx - ring, cy - ring, cx + ring, cy + ring, start=-start, extent=100,
                         style="arc", outline=color, width=max(2, int(2 * s)))
        elif state == "waiting":
            # blinking with a halo, to get attention
            blink = (math.sin(t * 6) + 1) / 2
            halo = r + (3 + 4 * blink) * s
            c.create_oval(cx - halo, cy - halo, cx + halo, cy + halo,
                          fill=blend(color, bg, 0.55 + 0.35 * (1 - blink)), outline="")
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=blend(bg, color, 0.45 + 0.55 * blink), outline="")
        else:
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="")

        if not self.compact:
            self.draw_text(c, w, h, state, color, t)

    def fit(self, text, font, max_width):
        """Truncates the text with an ellipsis until it fits the width in pixels."""
        if font.measure(text) <= max_width:
            return text
        while text and font.measure(text + "…") > max_width:
            text = text[:-1]
        return text + "…"

    def draw_text(self, c, w, h, state, color, t):
        s, cur = self.s, self.current
        x = h + 4 * s
        others = len(self.sessions) - 1
        max_width = w - x - (34 * s if others > 0 else 10 * s)

        label = STATES[state]["label"]
        if state == "thinking":
            label += "." * (int(t * 2) % 4)
        c.create_text(x, h / 2 - 8 * s, text=self.fit(label, self.title_font, max_width), anchor="w",
                      fill=self.theme["text"], font=self.title_font)

        if state == "offline":
            sub = "open Claude Code"
        else:
            elapsed = fmt_elapsed(time.time() - cur.get("since", time.time()))
            sub = f"{project_name(cur)}  ·  {elapsed}"
            if cur.get("detail") and state != "idle":
                with_detail = f"{project_name(cur)}  ·  {cur['detail']}  ·  {elapsed}"
                # when space runs out, the detail goes before the timer
                if self.sub_font.measure(with_detail) <= max_width:
                    sub = with_detail
        c.create_text(x, h / 2 + 9 * s, text=self.fit(sub, self.sub_font, max_width), anchor="w",
                      fill=self.theme["sub"], font=self.sub_font)

        if others > 0:
            bx = w - 20 * s
            c.create_oval(bx - 10 * s, h / 2 - 10 * s, bx + 10 * s, h / 2 + 10 * s,
                          fill=blend(self.theme["bg"], color, 0.3), outline="")
            c.create_text(bx, h / 2, text=f"+{others}", fill=self.theme["text"], font=self.sub_font)

    def run(self):
        self.root.mainloop()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text and real screen pixels
    except Exception:
        pass

    # Ensures a single instance of the widget.
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
    except OSError:
        sys.exit(0)

    mode = "taskbar" if "--taskbar" in sys.argv else "floating" if "--floating" in sys.argv else None
    StatusWidget(demo="--demo" in sys.argv, mode=mode).run()


if __name__ == "__main__":
    main()
