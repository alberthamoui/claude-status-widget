"""
Hook do Claude Code que registra o estado de cada sessão em disco.

O Claude Code chama este script em cada evento de hook, passando um JSON
no stdin. O script traduz o evento num destes estados e grava um arquivo
por sessão em ~/.claude/claude-status-widget/sessions/<session_id>.json:

    thinking  -> processando / raciocinando / executando ferramentas
    waiting   -> aguardando permissão, resposta (AskUserQuestion) ou aprovação de plano
    idle      -> terminou e está pronto para um novo prompt

Regras importantes para um hook:
  * nunca imprimir nada no stdout (em alguns eventos isso vira contexto do modelo);
  * sempre sair com código 0 (código 2 bloquearia a ação do Claude);
  * ser rápido.

Teste manual sem o Claude:
    python hook.py --test thinking|waiting|idle|clear
"""
import json
import os
import sys
import time

BASE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "claude-status-widget")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")

# Ferramentas que, por natureza, param tudo esperando o usuário.
INTERACTIVE_TOOLS = {"AskUserQuestion", "ExitPlanMode"}

# Tipos de Notification que significam "preciso de você".
WAITING_NOTIFICATIONS = {"permission_prompt", "elicitation_dialog"}


def state_for(event):
    """Traduz o payload de um hook em (estado, detalhe). None = remover a sessão."""
    name = event.get("hook_event_name", "")
    tool = event.get("tool_name", "")

    if name == "SessionEnd":
        return None, ""
    if name in ("SessionStart", "Stop", "StopFailure"):
        return "idle", ""
    if name == "UserPromptSubmit":
        return "thinking", "processando o prompt"
    if name == "PreToolUse":
        if tool in INTERACTIVE_TOOLS:
            return "waiting", "pergunta interativa" if tool == "AskUserQuestion" else "aprovar o plano"
        return "thinking", tool
    if name == "PermissionRequest":
        return "waiting", f"permissão: {tool}" if tool else "permissão"
    if name in ("PostToolUse", "PostToolUseFailure", "SubagentStart", "SubagentStop", "PreCompact"):
        return "thinking", tool or name
    if name == "Notification":
        kind = event.get("notification_type", "")
        message = event.get("message", "")
        if kind in WAITING_NOTIFICATIONS or "permission" in message.lower():
            return "waiting", message[:80] or "aguardando você"
        if kind == "idle_prompt":
            return "idle", ""
        return "", ""  # outras notificações não mudam o estado
    return "", ""


def write_session(session_id, state, detail, event):
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")

    previous = {}
    try:
        with open(path, encoding="utf-8") as f:
            previous = json.load(f)
    except (OSError, ValueError):
        pass

    now = time.time()
    record = {
        "session_id": session_id,
        "state": state,
        "detail": detail,
        "cwd": event.get("cwd") or previous.get("cwd", ""),
        "transcript_path": event.get("transcript_path") or previous.get("transcript_path", ""),
        "event": event.get("hook_event_name", ""),
        # "since" só muda quando o estado muda: é o que alimenta o cronômetro do widget.
        "since": previous.get("since", now) if previous.get("state") == state else now,
        "updated": now,
    }

    # Escrita atômica: o widget nunca lê um arquivo pela metade.
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
    os.replace(tmp, path)


def remove_session(session_id):
    try:
        os.remove(os.path.join(SESSIONS_DIR, f"{session_id}.json"))
    except OSError:
        pass


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--test":
        state = sys.argv[2]
        if state == "clear":
            remove_session("teste-manual")
        else:
            write_session("teste-manual", state, "teste manual", {"cwd": os.getcwd()})
        return

    # Lê bytes e decodifica como UTF-8: no Windows o stdin padrão é cp1252
    # e quebraria caminhos com acento.
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")
    except ValueError:
        return
    session_id = event.get("session_id")
    if not session_id:
        return

    state, detail = state_for(event)
    if state is None:
        remove_session(session_id)
    elif state:
        write_session(session_id, state, detail, event)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # um widget de status jamais deve atrapalhar o Claude
    sys.exit(0)
