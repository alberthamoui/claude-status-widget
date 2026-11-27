import io
import json
import ntpath
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import hook
import install


class StopTests(unittest.TestCase):
    def test_stop_prefers_payload_and_keeps_transcript_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "session.jsonl"
            event = {"hook_event_name": "Stop", "transcript_path": str(transcript)}
            with patch.object(hook, "CLAUDE_DIR", os.path.realpath(directory)):
                self.assertEqual(hook.state_for(dict(event, last_assistant_message="Continue?"))[0], "waiting")

                prompt = {"type": "user", "message": {"content": "Hello"}}
                reply = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Continue?"}]}}
                transcript.write_text(f"{json.dumps(prompt)}\n{json.dumps(reply)}\n", encoding="utf-8")
                self.assertEqual(hook.state_for(dict(event, last_assistant_message="Done."))[0], "idle")
                self.assertEqual(hook.state_for(event)[0], "waiting")

                reply["message"]["content"].append(
                    {"type": "tool_use", "name": "mcp__desktop__wrap_up", "input": {"ask": "Next step?"}}
                )
                transcript.write_text(f"{json.dumps(prompt)}\n{json.dumps(reply)}\n", encoding="utf-8")
                self.assertEqual(hook.state_for(dict(event, last_assistant_message="Done."))[0], "waiting")


class InstallerTests(unittest.TestCase):
    def test_parse_claude_version(self):
        self.assertEqual(install.parse_claude_version("2.1.100 (Claude Code)\n"), (2, 1, 100))
        self.assertIsNone(install.parse_claude_version("unknown"))

    def test_supported_version_accepts_windows_cmd(self):
        claude = r"C:\Program Files\nodejs\claude.cmd"
        for version in ("2.1.78", "2.1.100"):
            with self.subTest(version=version), patch.object(install, "find_claude_cli", return_value=claude), \
                    patch.object(install.subprocess, "run") as run, redirect_stderr(io.StringIO()) as stderr:
                run.return_value.stdout = f"{version} (Claude Code)\n"
                install.check_claude_version()
                self.assertEqual(run.call_args.args[0], [claude, "--version"])
                self.assertEqual(stderr.getvalue(), "")

    def test_old_version_exits_before_touching_settings(self):
        with patch.object(install, "check_requirements"), patch.object(install.sys, "argv", ["install.py"]), \
                patch.object(install, "find_claude_cli", return_value="claude"), \
                patch.object(install.subprocess, "run") as run, \
                patch.object(install, "load_settings") as load_settings, redirect_stderr(io.StringIO()) as stderr:
            run.return_value.stdout = "2.1.77 (Claude Code)\n"
            with self.assertRaises(SystemExit) as error:
                install.main()
            self.assertEqual(error.exception.code, 1)
            self.assertIn("Claude Code 2.1.78 or newer is required (found 2.1.77)", stderr.getvalue())
            load_settings.assert_not_called()

    def test_missing_claude_warns_and_continues(self):
        with patch.object(install, "find_claude_cli", return_value=None), \
                patch.object(install.subprocess, "run") as run, redirect_stderr(io.StringIO()) as stderr:
            install.check_claude_version()
            self.assertIn("not found on PATH", stderr.getvalue())
            run.assert_not_called()

    def test_unknown_version_warns_and_continues(self):
        with patch.object(install, "find_claude_cli", return_value="claude"), \
                patch.object(install.subprocess, "run") as run, redirect_stderr(io.StringIO()) as stderr:
            run.return_value.stdout = "unknown version"
            install.check_claude_version()
            self.assertIn("could not identify the Claude Code version", stderr.getvalue())

    def test_version_command_timeout_warns_and_continues(self):
        with patch.object(install, "find_claude_cli", return_value="claude"), \
                patch.object(install.subprocess, "run", side_effect=subprocess.TimeoutExpired("claude", 5)), \
                redirect_stderr(io.StringIO()) as stderr:
            install.check_claude_version()
            self.assertIn("could not run 'claude --version'", stderr.getvalue())

    def test_version_lookup_skips_current_directory(self):
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory) / "project"
            bin_dir = Path(directory) / "bin"
            cwd.mkdir()
            bin_dir.mkdir()
            claude = bin_dir / "claude.cmd"
            for file in (cwd / "claude.cmd", claude):
                file.touch()
                file.chmod(0o755)
            os.chdir(cwd)
            try:
                path = os.pathsep.join(("", ".", str(cwd), str(bin_dir)))
                with patch.dict(os.environ, {"PATH": path}), patch.object(install.subprocess, "run") as run:
                    run.return_value.stdout = "2.1.78 (Claude Code)"
                    install.check_claude_version()
                    self.assertEqual(run.call_args.args[0], [str(claude), "--version"])
            finally:
                os.chdir(original_cwd)

    def test_registers_failure_handlers(self):
        settings = {}
        install.add_our_hooks(settings, "python.exe")
        for name, expected in (("StopFailure", "idle"), ("PostToolUseFailure", "thinking")):
            with self.subTest(event=name):
                self.assertEqual(settings["hooks"][name][0]["hooks"][0]["type"], "command")
                self.assertEqual(hook.state_for({"hook_event_name": name})[0], expected)

    def test_removes_current_and_legacy_commands_for_installed_script_only(self):
        install_dir = r"C:\Users\João Silva\.claude\claude-status-widget"
        script = ntpath.join(install_dir, "hook.py")

        def entry(command):
            return {"type": "command", "command": command}

        with patch.object(install, "INSTALL_DIR", install_dir):
            current = entry(install.hook_command(r"C:\Program Files\Python312\python.exe"))
            legacy = entry(f'python "{script.lower()}"')
            unrelated = [
                entry('echo "claude-status-widget"'),
                entry(f'python "{script}.backup"'),
                entry('python "C:/other/claude-status-widget/hook.py"'),
            ]
            settings = {"hooks": {"Stop": [{"hooks": [current, legacy, *unrelated]}]}}
            install.strip_our_hooks(settings)
            self.assertEqual(settings, {"hooks": {"Stop": [{"hooks": unrelated}]}})


if __name__ == "__main__":
    unittest.main()
