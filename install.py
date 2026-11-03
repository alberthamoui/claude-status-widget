"""
Instala (ou remove) o Claude Status Widget.

    python install.py              copia os arquivos e registra os hooks
    python install.py --startup    idem + inicia o widget junto com o Windows
    python install.py --uninstall  remove hooks, atalho de inicialização e arquivos

Antes de alterar ~/.claude/settings.json, cria um backup ao lado dele.
Hooks que você já tem são preservados; só entradas deste widget são trocadas.
"""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
SETTINGS = os.path.join(CLAUDE_DIR, "settings.json")
INSTALL_DIR = os.path.join(CLAUDE_DIR, "claude-status-widget")
MARKER = "claude-status-widget"
STARTUP_VBS = os.path.join(
    os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    "ClaudeStatusWidget.vbs",
)

# Eventos que não usam matcher | eventos de ferramenta (matcher "*")
PLAIN_EVENTS = ["SessionStart", "UserPromptSubmit", "Stop", "SubagentStop", "PreCompact", "SessionEnd"]
TOOL_EVENTS = ["PreToolUse", "PermissionRequest", "PostToolUse", "Notification"]


def hook_command():
    path = os.path.join(INSTALL_DIR, "hook.py").replace("\\", "/")
    return f'python "{path}"'


def load_settings():
    if not os.path.exists(SETTINGS):
        return {}
    with open(SETTINGS, encoding="utf-8") as f:
        return json.load(f)


def save_settings(settings):
    if os.path.exists(SETTINGS):
        backup = f"{SETTINGS}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(SETTINGS, backup)
        print(f"Backup: {backup}")
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")


def strip_our_hooks(settings):
    """Remove apenas as entradas deste widget, mantendo as demais."""
    hooks = settings.get("hooks", {})
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            inner = [h for h in group.get("hooks", []) if MARKER not in h.get("command", "")]
            if inner:
                groups.append({**group, "hooks": inner})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)


def add_our_hooks(settings):
    hooks = settings.setdefault("hooks", {})
    entry = {"type": "command", "command": hook_command(), "timeout": 5}
    for event in PLAIN_EVENTS:
        hooks.setdefault(event, []).append({"hooks": [dict(entry)]})
    for event in TOOL_EVENTS:
        hooks.setdefault(event, []).append({"matcher": "*", "hooks": [dict(entry)]})


def install(startup):
    os.makedirs(INSTALL_DIR, exist_ok=True)
    for name in ("hook.py", "widget.py", "install.py", "README.md"):
        src = os.path.join(HERE, name)
        dst = os.path.join(INSTALL_DIR, name)
        if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
    print(f"Arquivos copiados para {INSTALL_DIR}")

    settings = load_settings()
    strip_our_hooks(settings)
    add_our_hooks(settings)
    save_settings(settings)
    print(f"Hooks registrados em {SETTINGS}")

    if startup:
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = "pythonw.exe"
        widget = os.path.join(INSTALL_DIR, "widget.py")
        with open(STARTUP_VBS, "w", encoding="utf-8") as f:
            f.write(f'CreateObject("WScript.Shell").Run """{pythonw}"" ""{widget}""", 0, False\n')
        print(f"Inicialização automática: {STARTUP_VBS}")

    print("\nPronto. Reinicie as sessões do Claude Code para os hooks valerem e rode:")
    print(f'  pythonw "{os.path.join(INSTALL_DIR, "widget.py")}"')


def uninstall():
    settings = load_settings()
    strip_our_hooks(settings)
    save_settings(settings)
    print("Hooks removidos.")
    if os.path.exists(STARTUP_VBS):
        os.remove(STARTUP_VBS)
        print("Inicialização automática removida.")
    shutil.rmtree(INSTALL_DIR, ignore_errors=True)
    print(f"Pasta removida: {INSTALL_DIR}")


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        install(startup="--startup" in sys.argv)
