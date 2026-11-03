"""
Instala (ou remove) o Claude Status Widget.

    python install.py              copia os arquivos, registra os hooks e abre o widget
    python install.py --startup    idem + abre o widget junto com o Windows
    python install.py --no-start   instala sem abrir o widget agora
    python install.py --uninstall  remove hooks, inicialização automática e arquivos

O que ele altera (e nada além disso):
  * ~/.claude/claude-status-widget/   cópia de hook.py, widget.py, install.py e README.md
  * ~/.claude/settings.json           acrescenta os hooks do widget (com backup antes)
  * pasta Inicializar do Windows      ClaudeStatusWidget.vbs, só com --startup

Hooks que já existem são preservados; só entradas deste widget são trocadas.
Rodar de novo atualiza a instalação sem duplicar nada.
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
SINGLE_INSTANCE_PORT = 47653  # o mesmo do widget.py
STARTUP_VBS = os.path.join(
    os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    "ClaudeStatusWidget.vbs",
)

# Eventos que não usam matcher | eventos de ferramenta (matcher "*")
PLAIN_EVENTS = ["SessionStart", "UserPromptSubmit", "Stop", "SubagentStop", "PreCompact", "SessionEnd"]
TOOL_EVENTS = ["PreToolUse", "PermissionRequest", "PostToolUse", "Notification"]


class InstallError(Exception):
    pass


# --------------------------------------------------------------------------- pré-requisitos

def check_requirements():
    if sys.platform != "win32":
        raise InstallError("Este widget por enquanto só funciona no Windows 10/11.")
    if sys.version_info < (3, 8):
        raise InstallError(f"Precisa de Python 3.8 ou mais novo (este é {sys.version.split()[0]}).")
    try:
        import tkinter  # noqa: F401
    except ImportError:
        raise InstallError("Este Python não tem Tkinter. Instale o Python de python.org ou da Microsoft Store.")


def python_paths():
    """Caminhos completos do python.exe e do pythonw.exe que os hooks e o widget vão usar."""
    exe = sys.executable
    if sys.prefix != sys.base_prefix:
        # Rodando dentro de um venv: usa o Python base, que não some se o venv for apagado.
        exe = getattr(sys, "_base_executable", "") or exe
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return exe, pythonw if os.path.exists(pythonw) else exe


def hook_command(python):
    # Caminhos completos e entre aspas: funciona com espaço no nome do usuário e
    # não depende de existir um "python" no PATH.
    def norm(path):
        return path.replace("\\", "/")
    return f'"{norm(python)}" "{norm(os.path.join(INSTALL_DIR, "hook.py"))}"'


# --------------------------------------------------------------------------- settings.json

def load_settings():
    if not os.path.exists(SETTINGS):
        return {}
    try:
        # utf-8-sig: aceita settings.json salvo com BOM (PowerShell, editores antigos do Windows)
        with open(SETTINGS, encoding="utf-8-sig") as f:
            settings = json.load(f)
    except ValueError as e:
        raise InstallError(f"{SETTINGS} não é um JSON válido ({e}). Corrija o arquivo; nada foi alterado.")
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks", {}), dict):
        raise InstallError(f"{SETTINGS} tem um formato inesperado; nada foi alterado.")
    return settings


def save_settings(settings):
    os.makedirs(CLAUDE_DIR, exist_ok=True)
    if os.path.exists(SETTINGS):
        backup = f"{SETTINGS}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(SETTINGS, backup)
        print(f"  backup do settings.json: {backup}")
    # Grava num temporário e troca de uma vez: se algo falhar no meio,
    # o settings.json original continua intacto.
    tmp = f"{SETTINGS}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, SETTINGS)


def strip_our_hooks(settings):
    """Remove apenas as entradas deste widget, mantendo as demais."""
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


# --------------------------------------------------------------------------- widget em execução

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
    """Pede para o widget fechar (via quit.flag) e espera até 5 s."""
    if not widget_running():
        return
    os.makedirs(INSTALL_DIR, exist_ok=True)
    with open(QUIT_FLAG, "w", encoding="utf-8") as f:
        f.write("quit")
    for _ in range(50):
        if not widget_running():
            print("  widget antigo fechado")
            return
        time.sleep(0.1)
    print("  aviso: o widget antigo não fechou; feche pelo menu (botão direito > Sair) e abra de novo")


def start_widget(pythonw):
    # cwd na pasta do usuário: o processo não "segura" a pasta de onde o instalador rodou.
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([pythonw, os.path.join(INSTALL_DIR, "widget.py")], cwd=os.path.expanduser("~"),
                     creationflags=flags, close_fds=True)
    print("  widget aberto")


def source_version():
    try:
        out = subprocess.run(["git", "-C", HERE, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


# --------------------------------------------------------------------------- comandos

def install(startup, start):
    check_requirements()
    python, pythonw = python_paths()
    settings = load_settings()  # valida antes de mexer em qualquer coisa

    version = source_version()
    print(f"Instalando o Claude Status Widget{f' (commit {version})' if version else ''}")
    print(f"  Python: {python}")

    stop_widget()
    os.makedirs(INSTALL_DIR, exist_ok=True)
    for name in FILES:
        src = os.path.join(HERE, name)
        dst = os.path.join(INSTALL_DIR, name)
        if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
    print(f"  arquivos em {INSTALL_DIR}")

    strip_our_hooks(settings)
    add_our_hooks(settings, python)
    save_settings(settings)
    print(f"  hooks registrados em {SETTINGS}")

    if startup:
        widget = os.path.join(INSTALL_DIR, "widget.py")
        with open(STARTUP_VBS, "w", encoding="utf-8") as f:
            f.write(f'CreateObject("WScript.Shell").Run """{pythonw}"" ""{widget}""", 0, False\n')
        print(f"  abre junto com o Windows: {STARTUP_VBS}")

    if start:
        start_widget(pythonw)

    print("\nPronto. Sessões do Claude Code que já estavam abertas podem precisar ser reiniciadas.")
    print(f'Para desinstalar: "{python}" "{os.path.join(INSTALL_DIR, "install.py")}" --uninstall')


def uninstall():
    stop_widget()
    if os.path.exists(SETTINGS):
        settings = load_settings()
        strip_our_hooks(settings)
        save_settings(settings)
        print("  hooks removidos")
    if os.path.exists(STARTUP_VBS):
        os.remove(STARTUP_VBS)
        print("  inicialização automática removida")
    # Só apaga a pasta do próprio widget dentro de ~/.claude, nunca outra coisa.
    target = os.path.realpath(INSTALL_DIR)
    if os.path.basename(target) == MARKER and os.path.dirname(target) == os.path.realpath(CLAUDE_DIR):
        shutil.rmtree(target, ignore_errors=True)
        print(f"  pasta removida: {target}")
    print("\nDesinstalado.")


def main():
    try:
        if "--uninstall" in sys.argv:
            uninstall()
        else:
            install(startup="--startup" in sys.argv, start="--no-start" not in sys.argv)
    except InstallError as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
