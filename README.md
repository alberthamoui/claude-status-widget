# Claude Status Widget

> [!IMPORTANT]
> **Windows only, for now.** It works on Windows 10 and 11. macOS and Linux are not supported yet: the installer stops with a message and changes nothing.

A dot on the Windows taskbar that shows what Claude Code is doing at a glance:

| Dot | Meaning |
|---|---|
| 🟠 **Orange, pulsing, with a spinning arc** | Thinking: reading, writing or running commands |
| 🟡 **Amber, blinking** | Waiting for you: a permission, a plan to approve, or Claude finished its reply with a question |
| 🟢 **Solid green** | Ready for the next request |
| ⚫ **Gray** | No Claude Code session open |

Requirements: **Windows 10 or 11**, Python 3.8+ and Claude Code.

## Install (the easy way)

Open Claude Code and send:

> Install the widget from this repository: https://github.com/alberthamoui/claude-widget

Claude will download the project, show you what will change on your PC and ask for your confirmation before installing.

## Instructions for Claude

> This section is for the assistant doing the install. Follow the steps in order and check with the user before the steps marked **(confirm)**.

1. **Check the system.** The widget currently only works on Windows 10 and 11. On macOS, Linux or anything else, tell the user it isn't supported yet and stop: don't clone, install Python or change any settings.
All commands below work as written in both Git Bash (the shell Claude Code uses on Windows) and PowerShell. Don't use `%USERPROFILE%`: it only works in the old Command Prompt.

2. **Check Python:** `python -c "import sys, tkinter; print(sys.version)"`. It must be 3.8+ and have Tkinter.
   - If `python` isn't found, prints nothing, or opens the Microsoft Store (Windows' placeholder), try `py -3 -c "import sys, tkinter; print(sys.version)"`.
   - If neither works, install Python **(confirm)**:
     ```bash
     winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
     ```
     The current shell won't see it on the PATH yet, so in the next steps call it by its full path: `"$LOCALAPPDATA/Programs/Python/Python312/python.exe"`.
   - Use the command that worked (`python`, `py -3` or the full path) wherever the steps below say `python`.
3. **Download the repository** **(confirm the folder)**, for example into `$HOME/claude-widget`:
   ```bash
   git clone https://github.com/alberthamoui/claude-widget.git "$HOME/claude-widget"
   ```
   If it already exists, update it instead: `git -C "$HOME/claude-widget" pull`.
4. **Read `install.py` before running it.** It's short and states at the top everything it changes.
5. **Install** **(confirm)**. Show the user what will change: `~/.claude/settings.json` gets hooks added, with a backup first. Also ask whether they want the widget to open when Windows starts.
   ```bash
   python "$HOME/claude-widget/install.py" --startup
   ```
   Without opening on Windows startup: the same command without `--startup`.
6. **Check** that the installer ended with `Done.` and that the dot appeared on the taskbar, just left of the Start button.
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

Download the new version and run the installer again (in PowerShell or Git Bash). It closes the old widget, replaces the files and opens the new one, without duplicating the hooks:

```bash
git -C "$HOME/claude-widget" pull
python "$HOME/claude-widget/install.py" --startup
```

## Usage

Clicks only work on the dot itself.

- **Right-click:** opens the menu.
  - List of open sessions, with the state, project and what each one is doing.
    - **Left-click a session** to open it in the Claude desktop app. Sessions it can't open (terminal, VS Code) are grayed out.
    - **Right-click a session** to remove it from the list. It doesn't close it in Claude, and it comes back if that session does something again.
  - **Pin to taskbar:** one dot on every taskbar (every monitor), just left of the Start button, so it stays clear of the weather widget however wide it gets. When unchecked, the widget becomes a single free window you can put anywhere on the screen.
  - **Sound when waiting for you:** plays an alert when Claude starts waiting for you.
  - **Compact / normal mode:** switches between just the dot and the version with text.
  - **Clear old sessions:** removes finished sessions from the list.
  - **Quit:** asks for confirmation, then closes the widget. To reopen it: `pythonw "$HOME/.claude/claude-status-widget/widget.py"`.
- **Double-click:** same as "Compact / normal mode".
- **Drag:** moves the dot along the taskbar. The distance from the Start button is saved and used on every monitor.

With several sessions open, the dot shows the most urgent one: waiting for you > thinking > ready. Like the rest of the taskbar, the dot on a monitor hides while a video or game is fullscreen there, even when another window has focus.

## Uninstall

In PowerShell or Git Bash:

```bash
python "$HOME/.claude/claude-status-widget/install.py" --uninstall
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
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PreCompact` | thinking |
| `PermissionRequest`, `PreToolUse` for `AskUserQuestion`/`ExitPlanMode`, `Notification` of type `permission_prompt`/`elicitation_dialog`, `Stop` after a reply that ends with a question | waiting for you |
| `SessionStart`, `Stop`, `Notification` of type `idle_prompt` (unless a question is pending) | ready |

On `Stop`, the hook reads the end of the transcript to tell "done" from "done, and asking you something": a question in the Claude desktop app's next-step box, or a final message ending with `?`.
| `SessionEnd` | removes the session |

Esc doesn't fire any hook. So the widget checks the last lines of the session transcript and, if it finds `[Request interrupted by user`, shows "Ready".

As a safety net, a session that stays "thinking" for 30 minutes with no hook event and no transcript write is shown as "Ready". That covers a missed `Stop`, such as Claude Code closing abruptly.

To test without Claude: `python widget.py --demo` cycles through the states, and `python hook.py --test thinking|waiting|idle|clear` creates a test session.

## Security

See [SECURITY.md](SECURITY.md): what the widget reads and writes, what it never does and how to report a problem.

## Limitations

- Windows only, for now (no macOS or Linux support yet). Covers **Claude Code** (the Code tab of the desktop app, the terminal and VS Code). Doesn't cover claude.ai chat, the mobile app or cloud sessions.
- Opening a session from the menu only works for conversations in the Claude desktop app, not for the terminal or VS Code. It uses the app's `claude://code/continue` link, which isn't a documented API and could change in an app update; if that happens, the click just stops switching conversations.
- After you approve a permission, the dot only turns orange again once the approved command finishes.
- If Claude Code closes abruptly, the session stays listed (as "Ready" after 30 minutes). It disappears on its own after 8 h, or right away with "Clear old sessions".
- A single command that runs for more than 30 minutes without Claude writing anything shows as "Ready" until it finishes.
- Doesn't work with `CLAUDE_CONFIG_DIR` pointing to a folder other than `~/.claude`.

## Not tested yet

The install was tested from a fresh clone, following the steps above in Git Bash, with a user name that has an accent and a space. These cases haven't been tested yet. If you run into one, please open an issue.

- **PC without Python:** installing Python with `winget` (step 2 of the instructions) was never run for real.
- **Python 3.8:** only the syntax was checked; the code has only run on Python 3.11.
- **Windows 10:** only tested on Windows 11. The Windows 10 taskbar is different, so the dot may sit in a slightly different place.
- **Opening conversations from the menu:** may not work if the Claude desktop app was installed differently, because its data can live in another folder. In that case conversations just show grayed out.
- **Another person's Claude reading this README:** never tested end to end. It will ask for confirmation before changing `settings.json`, which is expected.
