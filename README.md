# Claude Status Widget

A dot on the Windows taskbar that shows what Claude Code is doing at a glance:

| Dot | Meaning |
|---|---|
| 🟠 **Orange, pulsing, with a spinning arc** | Thinking: reading, writing or running commands |
| 🟡 **Amber, blinking** | Waiting for you: a permission, a question or a plan to approve |
| 🟢 **Solid green** | Ready for the next request |
| ⚫ **Gray** | No Claude Code session open |

Requirements: Windows 10 or 11, Python 3.8+ and Claude Code.

## Install (the easy way)

Open Claude Code and send:

> Install the widget from this repository: https://github.com/alberthamoui/claude-widget

Claude will download the project, show you what will change on your PC and ask for your confirmation before installing.

## Instructions for Claude

> This section is for the assistant doing the install. Follow the steps in order and check with the user before the steps marked **(confirm)**.

1. **Check the system.** The widget only works on Windows. On another system, tell the user and stop.
2. **Check Python:** `python -c "import sys, tkinter; print(sys.version)"`. It must be 3.8+ and have Tkinter.
   - If Python is missing **(confirm)**: `winget install -e --id Python.Python.3.12`, then open a new terminal.
   - Use the same command that worked here (`python` or `py`) in the next steps.
3. **Download the repository** **(confirm the folder)**, for example into `%USERPROFILE%\claude-widget`:
   ```bash
   git clone https://github.com/alberthamoui/claude-widget.git "%USERPROFILE%\claude-widget"
   ```
   If it already exists, update it with `git -C "%USERPROFILE%\claude-widget" pull`.
4. **Read `install.py` before running it.** It's short and states at the top everything it changes.
5. **Install** **(confirm)**. Show the user what will change: `~/.claude/settings.json` gets hooks added, with a backup first. Also ask whether they want the widget to open when Windows starts.
   ```bash
   python "%USERPROFILE%\claude-widget\install.py" --startup
   ```
   Without opening on Windows startup: the same command without `--startup`.
6. **Check** that the installer ended with `Done.` and that the dot appeared on the taskbar, next to the weather or the Start button.
7. **Tell the user:**
   - Claude Code sessions that were already open may need a restart;
   - clicks work on the dot itself: right-click opens the menu and double-click shows the version with text.

If `install.py` prints `Error:`, it changed nothing. Show the message to the user.

## Install manually

```bash
git clone https://github.com/alberthamoui/claude-widget.git
cd claude-widget
python install.py --startup
```

The installer copies the files to `~/.claude/claude-status-widget/`. After that, the cloned folder can be deleted.

## Update

Download the new version and run the installer again. It closes the old widget, replaces the files and opens the new one, without duplicating the hooks:

```bash
git -C "%USERPROFILE%\claude-widget" pull
python "%USERPROFILE%\claude-widget\install.py" --startup
```

## Usage

Clicks only work on the dot itself.

- **Right-click:** opens the menu.
  - List of open sessions, with the state, project and what each one is doing.
  - **Pin to taskbar:** when unchecked, the widget becomes a free window you can put anywhere on the screen.
  - **Sound when waiting for you:** plays an alert when Claude starts waiting for you.
  - **Compact / normal mode:** switches between just the dot and the version with text.
  - **Clear old sessions:** removes finished sessions from the list.
  - **Quit:** closes the widget. To reopen it: `pythonw "%USERPROFILE%\.claude\claude-status-widget\widget.py"`.
- **Double-click:** same as "Compact / normal mode".
- **Drag:** moves the dot along the taskbar. The position is saved.

With several sessions open, the dot shows the most urgent one: waiting for you > thinking > ready. It also hides while a video or game is fullscreen.

## Uninstall

```bash
python "%USERPROFILE%\.claude\claude-status-widget\install.py" --uninstall
```

Removes the hooks (keeping yours), the startup entry and the widget folder.

## How it works

```
Claude Code ──(official hooks)──► hook.py ──► ~/.claude/claude-status-widget/sessions/<id>.json
                                                         ▲
                                         widget.py (Tkinter) reads every 400 ms
```

- **Capture:** through [Claude Code hooks](https://docs.claude.com/en/docs/claude-code/hooks), the official event system. It doesn't depend on reading the screen or network traffic.
- **Bridge:** one JSON file per session, written atomically.
- **Interface:** Python + Tkinter, both included with Python. No `pip install`.

| Hook event | State |
|---|---|
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStop`, `PreCompact` | thinking |
| `PermissionRequest`, `PreToolUse` for `AskUserQuestion`/`ExitPlanMode`, `Notification` of type `permission_prompt`/`elicitation_dialog` | waiting for you |
| `SessionStart`, `Stop`, `Notification` of type `idle_prompt` | ready |
| `SessionEnd` | removes the session |

Esc doesn't fire any hook. So the widget checks the last lines of the session transcript and, if it finds `[Request interrupted by user`, shows "Ready".

To test without Claude: `python widget.py --demo` cycles through the states, and `python hook.py --test thinking|waiting|idle|clear` creates a test session.

## Security

See [SECURITY.md](SECURITY.md): what the widget reads and writes, what it never does and how to report a problem.

## Limitations

- Windows only. Covers **Claude Code** (the Code tab of the desktop app, the terminal and VS Code). Doesn't cover claude.ai chat, the mobile app or cloud sessions.
- After you approve a permission, the dot only turns orange again once the approved command finishes.
- If Claude Code closes abruptly, the session stays listed. It disappears on its own after 8 h, or right away with "Clear old sessions".
- Doesn't work with `CLAUDE_CONFIG_DIR` pointing to a folder other than `~/.claude`.
