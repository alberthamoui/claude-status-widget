import json
import ntpath
import os
import tempfile
import unittest
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
