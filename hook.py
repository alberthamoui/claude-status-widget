"""
Claude Code hook that records the state of each session on disk.

Claude Code calls this script on every hook event, passing a JSON payload
on stdin. The script maps the event to one of these states and writes one
file per session to ~/.claude/claude-status-widget/sessions/<session_id>.json:

    thinking  -> processing / reasoning / running tools
    waiting   -> waiting for a permission, an answer (AskUserQuestion, or a turn that
                 ended with a question) or plan approval
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

CLAUDE_DIR = os.path.realpath(os.path.join(os.path.expanduser("~"), ".claude"))
BASE_DIR = os.path.join(CLAUDE_DIR, "claude-status-widget")
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
TRANSCRIPT_TAIL_BYTES = 256 * 1024  # enough to hold the last turn, without reading huge transcripts

# The session_id becomes a file name: only safe characters are accepted, no "../".
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")

# Tools that, by nature, stop everything while waiting for the user.
INTERACTIVE_TOOLS = {"AskUserQuestion", "ExitPlanMode"}

# Notification types that mean "I need you".
WAITING_NOTIFICATIONS = {"permission_prompt", "elicitation_dialog"}


def inside_claude_dir(path):
    """Only Claude Code's own transcripts are read, never an arbitrary path."""
    try:
        real = os.path.realpath(path)
        return real.endswith(".jsonl") and os.path.commonpath([real, CLAUDE_DIR]) == CLAUDE_DIR
    except (TypeError, ValueError):
        return False


def ended_with_question(transcript_path):
    """True if Claude's last turn ended by asking the user something.

    Walks the transcript back to the user's prompt that started the turn, looking for
    the Claude desktop app's next-step question (a wrap_up tool call with "ask") or,
    elsewhere, a final message that ends with a question mark.
    """
    if not isinstance(transcript_path, str) or not inside_claude_dir(transcript_path):
        return False
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - TRANSCRIPT_TAIL_BYTES))
            lines = f.read().decode("utf-8", "ignore").splitlines()[1:]  # first line may be cut
    except OSError:
        return False

    final_text = None
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        content = (entry.get("message") or {}).get("content")
        blocks = content if isinstance(content, list) else []
        if entry.get("type") == "user":
            if isinstance(content, str) or any(isinstance(b, dict) and b.get("type") == "text" for b in blocks):
                break  # the user's own message: start of the turn
            continue
        if entry.get("type") != "assistant":
            continue
        for block in reversed(blocks):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and str(block.get("name", "")).endswith("__wrap_up"):
                tool_input = block.get("input")
                if isinstance(tool_input, dict) and tool_input.get("ask"):
                    return True
            if block.get("type") == "text" and final_text is None and isinstance(block.get("text"), str):
                final_text = block["text"]
    return bool(final_text) and final_text.rstrip().rstrip("*_`\"')»”").endswith("?")


def state_for(event):
    """Maps a hook payload to (state, detail). None = remove the session."""
    name = event.get("hook_event_name", "")
    tool = event.get("tool_name", "")

    if name == "SessionEnd":
        return None, ""
    if name == "Stop" and ended_with_question(event.get("transcript_path")):
        return "waiting", "question for you"
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
    if name in ("PostToolUse", "PostToolUseFailure", "PreCompact"):
        return "thinking", tool or name
    # SubagentStart/SubagentStop leave the state alone: a background subagent can finish
    # after the main turn has already stopped, and must not flip the session back to "thinking".
    if name == "Notification":
        kind = event.get("notification_type", "")
        message = event.get("message", "")
        if kind in WAITING_NOTIFICATIONS or "permission" in message.lower():
            return "waiting", message[:80] or "waiting for you"
        if kind == "idle_prompt":
            return "idle_unless_waiting", ""
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


def current_state(session_id):
    try:
        with open(os.path.join(SESSIONS_DIR, f"{session_id}.json"), encoding="utf-8") as f:
            return json.load(f).get("state")
    except (OSError, ValueError, AttributeError):
        return None


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
    if state == "idle_unless_waiting":
        # Claude Code's "waiting for your input" reminder (after ~60 s idle) must not
        # turn a pending question back into "ready".
        if current_state(session_id) == "waiting":
            return
        state = "idle"
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
