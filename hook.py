"""
Claude Code hook that records the state of each session on disk.

Claude Code calls this script on every hook event, passing a JSON payload
on stdin. The script maps the event to one of these states and writes one
file per session to ~/.claude/claude-status-widget/sessions/<session_id>.json:

    thinking  -> processing / reasoning / running tools
    waiting   -> waiting for a permission, an answer (AskUserQuestion) or plan approval
    idle      -> finished and ready for a new prompt

Ground rules for a hook:
  * never print anything to stdout (for some events it becomes model context);
  * always exit with code 0 (code 2 would block Claude's action);
  * be fast.

Manual test without Claude:
    python hook.py --test thinking|waiting|idle|clear
"""
import json
import os
import re
import sys
import time

BASE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "claude-status-widget")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")

# The session_id becomes a file name: only safe characters are accepted, no "../".
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")

# Tools that, by nature, stop everything while waiting for the user.
INTERACTIVE_TOOLS = {"AskUserQuestion", "ExitPlanMode"}

# Notification types that mean "I need you".
WAITING_NOTIFICATIONS = {"permission_prompt", "elicitation_dialog"}


def state_for(event):
    """Maps a hook payload to (state, detail). None = remove the session."""
    name = event.get("hook_event_name", "")
    tool = event.get("tool_name", "")

    if name == "SessionEnd":
        return None, ""
    if name in ("SessionStart", "Stop", "StopFailure"):
        return "idle", ""
    if name == "UserPromptSubmit":
        return "thinking", "processing the prompt"
    if name == "PreToolUse":
        if tool in INTERACTIVE_TOOLS:
            return "waiting", "interactive question" if tool == "AskUserQuestion" else "approve the plan"
        return "thinking", tool
    if name == "PermissionRequest":
        return "waiting", f"permission: {tool}" if tool else "permission"
    if name in ("PostToolUse", "PostToolUseFailure", "SubagentStart", "SubagentStop", "PreCompact"):
        return "thinking", tool or name
    if name == "Notification":
        kind = event.get("notification_type", "")
        message = event.get("message", "")
        if kind in WAITING_NOTIFICATIONS or "permission" in message.lower():
            return "waiting", message[:80] or "waiting for you"
        if kind == "idle_prompt":
            return "idle", ""
        return "", ""  # other notifications don't change the state
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
        # "since" only changes when the state changes: it drives the widget's timer.
        "since": previous.get("since", now) if previous.get("state") == state else now,
        "updated": now,
    }

    # Atomic write: the widget never reads a half-written file.
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
            remove_session("manual-test")
        else:
            write_session("manual-test", state, "manual test", {"cwd": os.getcwd()})
        return

    # Read bytes and decode as UTF-8: on Windows the default stdin encoding is cp1252,
    # which would break paths with accented characters.
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")
    except ValueError:
        return
    session_id = event.get("session_id")
    if not isinstance(session_id, str) or not SAFE_ID.fullmatch(session_id):
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
        pass  # a status widget must never get in Claude's way
    sys.exit(0)
