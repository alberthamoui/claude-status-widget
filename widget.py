"""
Widget que mostra o estado do Claude Code em tempo real.

Lê os arquivos gravados pelo hook.py em ~/.claude/claude-status-widget/sessions/
e exibe a sessão mais urgente (waiting > thinking > idle).

Dois modos:
    flutuante         janela solta, sempre no topo, em qualquer lugar da tela
    barra de tarefas  encaixado no espaço livre da barra (ao lado do clima)

Uso:
    pythonw widget.py              (sem janela de console, usa o último modo)
    python  widget.py --taskbar    (muda para o modo barra de tarefas e salva)
    python  widget.py --floating   (muda para o modo flutuante e salva)
    python  widget.py --demo       (alterna os estados sozinho, para testar o visual)

Controles:
    arrastar com o botão esquerdo  -> mover (na barra, só na horizontal)
    duplo clique                   -> modo compacto (só a bolinha)
    botão direito                  -> menu (sessões, modo, som, sair)
"""
import json
import math
import os
import socket
import sys
import time
import tkinter as tk
import tkinter.font as tkfont

BASE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "claude-status-widget")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
CONFIG_PATH = os.path.join(BASE_DIR, "widget_config.json")

POLL_MS = 400              # leitura dos arquivos de sessão
FRAME_MS = 33              # animação (~30 fps)
TASKBAR_MS = 250           # reposiciona e reafirma o "por cima" da barra
STALE_SECONDS = 8 * 3600   # sessões sem eventos há mais que isso são ignoradas
SINGLE_INSTANCE_PORT = 47653

TRANSPARENT = "#ff00fe"    # cor-chave que o Windows torna transparente (cantos arredondados)

THEMES = {
    "floating":      {"bg": "#1e1e22", "border": "#34343c", "text": "#f2f2f2", "sub": "#9a9aa5"},
    "taskbar_dark":  {"bg": "#2c2c2c", "border": "#2c2c2c", "text": "#ffffff", "sub": "#ababab"},
    "taskbar_light": {"bg": "#e4e4e4", "border": "#e4e4e4", "text": "#1b1b1b", "sub": "#5f5f5f"},
}

STATES = {
    "thinking": {"label": "Pensando", "color": "#d97757", "priority": 2},
    "waiting":  {"label": "Aguardando você", "color": "#f5b942", "priority": 3},
    "idle":     {"label": "Pronto", "color": "#4ade80", "priority": 1},
    "offline":  {"label": "Nenhuma sessão", "color": "#6b6b75", "priority": 0},
}

INTERRUPT_MARKER = "[Request interrupted by user"


# --------------------------------------------------------------------------- Windows

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND] + [ctypes.c_int] * 4 + [wintypes.UINT]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

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


def taskbar_window():
    return user32.FindWindowW("Shell_TrayWnd", None) if user32 else None


def fullscreen_over(taskbar):
    """True se a janela em primeiro plano ocupa o monitor inteiro da barra (vídeo, jogo...)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    cls = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, cls, 64)
    if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
        return False
    monitor = user32.MonitorFromWindow(hwnd, 2)
    if monitor != user32.MonitorFromWindow(taskbar, 2):
        return False
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(monitor, ctypes.byref(info))
    m = info.rcMonitor
    left, top, right, bottom = window_rect(hwnd)
    return left <= m.left and top <= m.top and right >= m.right and bottom >= m.bottom


def light_taskbar():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "SystemUsesLightTheme")[0] == 1
    except OSError:
        return False


# --------------------------------------------------------------------------- dados

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def was_interrupted(session, cache):
    """Esc no Claude Code não dispara o hook Stop; detectamos pelo fim do transcript."""
    path = session.get("transcript_path")
    if not path:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if mtime <= session.get("updated", 0):
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
        s = load_json(os.path.join(SESSIONS_DIR, name), None)
        if not isinstance(s, dict) or s.get("state") not in STATES:
            continue
        if now - s.get("updated", 0) > STALE_SECONDS:
            continue
        if s["state"] != "idle":
            interrupted_at = was_interrupted(s, interrupt_cache)
            if interrupted_at:
                s.update(state="idle", detail="interrompido", since=interrupted_at)
        sessions.append(s)
    sessions.sort(key=lambda s: (-STATES[s["state"]]["priority"], -s.get("updated", 0)))
    return sessions


def project_name(session):
    cwd = session.get("cwd") or ""
    return os.path.basename(cwd.rstrip("\\/")) or cwd or "sessão"


def fmt_elapsed(seconds):
    seconds = int(max(0, seconds))
    if seconds < 3600:
        return f"{seconds // 60}:{seconds % 60:02d}"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}"


def blend(c1, c2, t):
    """Mistura duas cores hex; t=0 -> c1, t=1 -> c2."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


# --------------------------------------------------------------------------- widget

class StatusWidget:
    def __init__(self, demo=False, mode=None):
        self.demo = demo
        self.config = load_json(CONFIG_PATH, {})
        if mode:
            self.config["mode"] = mode
        self.sessions = []
        self.current = {"state": "offline"}
        self.last_state = "offline"
        self.interrupt_cache = {}
        self.t0 = time.time()
        self.hidden = False
        self.menu_open = False
        self.last_geometry = None

        self.root = tk.Tk()
        self.root.title("Claude Status")
        self.root.overrideredirect(True)  # sem borda e fora da barra de tarefas
        self.root.configure(bg=TRANSPARENT)
        try:
            self.root.wm_attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass  # fora do Windows: cantos ficam quadrados

        # Escala para monitores com DPI alto (Tk escala fontes, mas não pixels do canvas).
        self.s = max(1.0, float(self.root.tk.call("tk", "scaling")) / (96 / 72))
        self.taskbar_height = int(48 * self.s)

        self.on_taskbar = tk.BooleanVar(value=self.config.get("mode") == "taskbar" and user32 is not None)
        self.topmost = tk.BooleanVar(value=self.config.get("topmost", True))
        self.beep = tk.BooleanVar(value=self.config.get("beep", False))
        self.compact = self.config.get("compact", False)
        self.update_theme()

        self.canvas = tk.Canvas(self.root, bg=TRANSPARENT, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.title_font = tkfont.Font(family="Segoe UI Semibold", size=10)
        self.sub_font = tkfont.Font(family="Segoe UI", size=8)

        self.canvas.bind("<ButtonPress-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda e: self.save_config())
        self.canvas.bind("<Double-Button-1>", lambda e: self.toggle_compact())
        self.canvas.bind("<Button-3>", self.show_menu)

        self.apply_geometry()
        if mode:
            self.save_config()
        self.poll()
        self.animate()
        self.taskbar_tick()

    # ---- geometria e configuração

    def update_theme(self):
        if self.on_taskbar.get():
            self.theme = THEMES["taskbar_light" if light_taskbar() else "taskbar_dark"]
            self.root.wm_attributes("-topmost", True)
        else:
            self.theme = THEMES["floating"]
            self.root.wm_attributes("-topmost", self.topmost.get())

    def size(self):
        if self.on_taskbar.get():
            h = max(int(24 * self.s), self.taskbar_height - int(10 * self.s))
            return (h, h) if self.compact else (int(230 * self.s), h)
        return (int(36 * self.s), int(36 * self.s)) if self.compact else (int(250 * self.s), int(52 * self.s))

    def apply_geometry(self):
        if self.on_taskbar.get():
            self.last_geometry = None
            self.place_on_taskbar()
            return
        if self.hidden:
            self.root.deiconify()
            self.hidden = False
        w, h = self.size()
        sw = self.root.winfo_screenwidth()
        x = self.config.get("x", sw - w - int(24 * self.s))
        y = self.config.get("y", int(24 * self.s))
        x = min(max(0, x), sw - w)
        y = min(max(0, y), self.root.winfo_screenheight() - h)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.canvas.config(width=w, height=h)

    def place_on_taskbar(self):
        """Encaixa o widget sobre a barra, à esquerda, e o mantém por cima dela."""
        taskbar = taskbar_window()
        visible = False
        if taskbar and user32.IsWindowVisible(taskbar):
            left, top, right, bottom = window_rect(taskbar)
            bottom = min(bottom, self.root.winfo_screenheight())
            # barra com ocultação automática fica quase toda fora da tela
            visible = bottom - top > 20 and not fullscreen_over(taskbar)

        if not visible:
            if not self.hidden:
                self.root.withdraw()
                self.hidden = True
            return
        if self.hidden:
            self.root.deiconify()
            self.hidden = False
            self.last_geometry = None

        self.taskbar_height = bottom - top
        w, h = self.size()
        offset = self.config.get("taskbar_offset", int(64 * self.s))
        x = min(max(left, left + offset), right - w)
        y = top + (self.taskbar_height - h) // 2
        geometry = (w, h, x, y)
        if geometry != self.last_geometry:
            self.root.geometry(f"{w}x{h}+{x}+{y}")
            self.canvas.config(width=w, height=h)
            self.last_geometry = geometry

        # Clicar na barra a traz para frente; reafirmamos o "sempre no topo".
        # Com o menu aberto não: o widget passaria por cima dele e esconderia opções.
        if self.menu_open:
            return
        HWND_TOPMOST, SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = -1, 0x1, 0x2, 0x10
        hwnd = int(self.root.wm_frame(), 16)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)

    def taskbar_tick(self):
        if self.on_taskbar.get():
            self.place_on_taskbar()
        self.root.after(TASKBAR_MS, self.taskbar_tick)

    def save_config(self):
        self.config.update(
            mode="taskbar" if self.on_taskbar.get() else "floating",
            topmost=self.topmost.get(), beep=self.beep.get(), compact=self.compact,
        )
        if not self.on_taskbar.get() and self.root.winfo_ismapped():
            self.config.update(x=self.root.winfo_x(), y=self.root.winfo_y())
        try:
            os.makedirs(BASE_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f)
        except OSError:
            pass

    def toggle_compact(self):
        self.compact = not self.compact
        self.apply_geometry()
        self.save_config()

    def toggle_taskbar(self):
        self.update_theme()
        self.apply_geometry()
        self.save_config()

    def start_drag(self, event):
        self.drag_offset = (event.x, event.y)

    def on_drag(self, event):
        dx, dy = self.drag_offset
        if self.on_taskbar.get():
            taskbar = taskbar_window()
            if taskbar:
                self.config["taskbar_offset"] = event.x_root - dx - window_rect(taskbar)[0]
                self.place_on_taskbar()
        else:
            self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    # ---- menu de contexto

    def show_menu(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        if self.sessions:
            for s in self.sessions:
                label = f"{STATES[s['state']]['label']}  ·  {project_name(s)}"
                if s.get("detail"):
                    label += f"  ·  {s['detail']}"
                menu.add_command(label=label[:70], state="disabled")
        else:
            menu.add_command(label="Nenhuma sessão do Claude Code ativa", state="disabled")
        menu.add_separator()
        if user32:
            menu.add_checkbutton(label="Fixar na barra de tarefas", variable=self.on_taskbar,
                                 command=self.toggle_taskbar)
        if not self.on_taskbar.get():
            menu.add_checkbutton(label="Sempre no topo", variable=self.topmost, command=self.on_topmost)
        menu.add_checkbutton(label="Som ao aguardar você", variable=self.beep, command=self.save_config)
        menu.add_command(label="Modo compacto / normal", command=self.toggle_compact)
        menu.add_command(label="Limpar sessões antigas", command=self.clear_idle_sessions)
        menu.add_separator()
        menu.add_command(label="Sair", command=self.quit)
        # No Windows o tk_popup só retorna quando o menu fecha.
        self.menu_open = True
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
            self.menu_open = False

    def on_topmost(self):
        self.root.wm_attributes("-topmost", self.topmost.get())
        self.save_config()

    def clear_idle_sessions(self):
        for s in self.sessions:
            if s["state"] == "idle":
                try:
                    os.remove(os.path.join(SESSIONS_DIR, f"{s['session_id']}.json"))
                except (OSError, KeyError):
                    pass

    def quit(self):
        self.save_config()
        self.root.destroy()

    # ---- estado

    def poll(self):
        if self.demo:
            order = ["thinking", "waiting", "idle"]
            state = order[int((time.time() - self.t0) // 4) % 3]
            self.sessions = [{"state": state, "cwd": "demo", "detail": "modo demo", "since": self.t0}]
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

    # ---- desenho

    def rounded_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
               x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def animate(self):
        c = self.canvas
        c.delete("all")
        w, h = self.size()
        s = self.s
        bg = self.theme["bg"]
        state = self.current["state"]
        color = STATES[state]["color"]
        t = time.time()

        # No modo compacto só a bolinha aparece: o fundo fica todo transparente.
        if not self.compact:
            radius = 8 * s if self.on_taskbar.get() else h / 2 - 1
            self.rounded_rect(1, 1, w - 2, h - 2, radius, fill=bg, outline=self.theme["border"])

        cx, cy = (w / 2, h / 2) if self.compact else (h / 2 + 2 * s, h / 2)
        r = 7 * s

        if state == "thinking":
            # bolinha pulsando + arco girando em volta
            pulse = (math.sin(t * 4) + 1) / 2
            rr = r * (0.8 + 0.25 * pulse)
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=color, outline="")
            ring = r + 5 * s
            start = (t * 360) % 360
            c.create_arc(cx - ring, cy - ring, cx + ring, cy + ring, start=-start, extent=100,
                         style="arc", outline=color, width=max(2, int(2 * s)))
        elif state == "waiting":
            # piscando com halo, para chamar atenção
            blink = (math.sin(t * 6) + 1) / 2
            halo = r + (3 + 4 * blink) * s
            c.create_oval(cx - halo, cy - halo, cx + halo, cy + halo,
                          fill=blend(color, bg, 0.55 + 0.35 * (1 - blink)), outline="")
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=blend(bg, color, 0.45 + 0.55 * blink), outline="")
        else:
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="")

        if not self.compact:
            self.draw_text(w, h, state, color, t)
        self.root.after(FRAME_MS, self.animate)

    def fit(self, text, font, max_width):
        """Corta o texto com reticências até caber na largura em pixels."""
        if font.measure(text) <= max_width:
            return text
        while text and font.measure(text + "…") > max_width:
            text = text[:-1]
        return text + "…"

    def draw_text(self, w, h, state, color, t):
        c, s, cur = self.canvas, self.s, self.current
        x = h + 4 * s
        others = len(self.sessions) - 1
        max_width = w - x - (34 * s if others > 0 else 10 * s)

        label = STATES[state]["label"]
        if state == "thinking":
            label += "." * (int(t * 2) % 4)
        c.create_text(x, h / 2 - 8 * s, text=self.fit(label, self.title_font, max_width), anchor="w",
                      fill=self.theme["text"], font=self.title_font)

        if state == "offline":
            sub = "abra o Claude Code"
        else:
            elapsed = fmt_elapsed(time.time() - cur.get("since", time.time()))
            sub = f"{project_name(cur)}  ·  {elapsed}"
            if cur.get("detail") and state != "idle":
                with_detail = f"{project_name(cur)}  ·  {cur['detail']}  ·  {elapsed}"
                # sem espaço, o detalhe sai antes do cronômetro
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
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # texto nítido e pixels reais da tela
    except Exception:
        pass

    # Garante uma única instância do widget.
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
    except OSError:
        sys.exit(0)

    mode = "taskbar" if "--taskbar" in sys.argv else "floating" if "--floating" in sys.argv else None
    StatusWidget(demo="--demo" in sys.argv, mode=mode).run()


if __name__ == "__main__":
    main()
