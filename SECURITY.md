# Security

The widget runs inside your Claude Code (its hooks are called on every Claude action). That's why it was built to be small, easy to audit and unable to get in Claude's way.

## What it does

| | |
|---|---|
| **Writes** | `~/.claude/claude-status-widget/`: the copied files, one JSON per session and the widget settings. It also adds its own hooks to `~/.claude/settings.json`, with a backup first, and, only with `--startup`, creates `ClaudeStatusWidget.vbs` in the Windows Startup folder. |
| **Reads** | The JSON Claude Code hands to the hook and the end of the session transcript (only `.jsonl` files inside `~/.claude`): the widget reads the last ~6 KB to detect Esc, and the hook reads the last 256 KB on `Stop` to see whether the reply ended with a question. Nothing read from the transcript is stored. When you open the right-click menu, the widget also reads the Claude desktop app's conversation files to match sessions to conversations, using only their ids and archived flag. |
| **Opens** | A `claude://code/continue?session=local_...` link, only when you left-click a session in the menu. The id must match the app's exact format (`local_` plus letters, digits and `-`), so nothing else can get into the link. |
| **Stores per session** | State, tool name (e.g. `Bash`), project folder, transcript path, timestamps and the start of Claude Code notification text (e.g. "Claude needs your permission to use Bash"). |

## What it never does

- **Network:** it doesn't access the internet or any server. Its only socket is a lock on `127.0.0.1` that prevents opening two widgets; it never accepts connections.
- **Content:** it doesn't store prompts, responses, commands or file contents. The hooks' `tool_input` is ignored.
- **Dependencies:** it installs nothing. It's just the Python standard library, so there's no third-party package to be compromised.
- **Getting in Claude's way:** the hook never prints anything (for some events that would become model context), always exits with code 0 (never blocks an action), has a 5 s timeout and ignores any error.
- **Touching other hooks:** hooks already in `settings.json` are kept. Uninstalling removes only the entries containing `claude-status-widget`.

## Protections against forged data

- A `session_id` is only accepted if it has letters, digits, `-` and `_`. So an id like `../../x` can't write or delete files outside the widget folder.
- The widget checks the type of every field in the session JSONs and ignores malformed files instead of crashing.
- "Clear old sessions" and right-clicking a session only delete files listed inside the `sessions/` folder.
- `settings.json` is written to a temporary file and swapped in at once. An error midway doesn't corrupt Claude's settings. If it's invalid, the installer stops without changing anything.
- Uninstalling only removes the `~/.claude/claude-status-widget` folder.

## Before installing

There are three short Python files (`hook.py`, `install.py`, `widget.py`). Read them, or ask your Claude to read them, before running anything. The installer shows the commit being installed.

## Reporting a problem

Found a security issue? Use **Security → Report a vulnerability** on the repository's GitHub page, privately, instead of opening a public issue.
