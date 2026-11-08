import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import validate_config  # noqa: E402

EXAMPLE = json.loads((ROOT / "examples" / "default.deck.json").read_text())


def cfg():
    return copy.deepcopy(EXAMPLE)


def key_button(bid, row, col, key="a", **extra):
    return {
        "id": bid,
        "label": bid,
        "action": {"type": "key", "key": key},
        "position": {"row": row, "col": col, **extra},
    }


def macro(mid, *refs):
    return {
        "id": mid,
        "label": mid,
        "steps": [{"action": {"type": "macro", "macroId": r}} for r in refs]
        or [{"action": {"type": "key", "key": "a"}}],
    }


class ValidateConfigTests(unittest.TestCase):
    def errors(self, config):
        errs, _ = validate_config.validate(config)
        return errs

    def assertHasError(self, config, fragment):
        errs = self.errors(config)
        self.assertTrue(any(fragment in e for e in errs), f"expected '{fragment}' in {errs}")

    def test_example_is_valid(self):
        errs, warns = validate_config.validate(cfg())
        self.assertEqual(errs, [])
        self.assertEqual(warns, [])

    def test_key_table_has_all_modifiers_separate(self):
        table = json.loads((ROOT / "spec" / "keys.json").read_text())
        self.assertEqual(set(table["modifiers"]), {"cmd", "shift", "opt", "ctrl", "fn"})
        self.assertFalse(set(table["modifiers"]) & set(table["keys"]))
        codes = list(table["keys"].values())
        self.assertEqual(len(codes), len(set(codes)))

    def test_schema_rejects_bad_color(self):
        c = cfg()
        c["workspaces"][0]["buttons"][0]["color"] = "blue"
        self.assertHasError(c, "color")

    def test_schema_rejects_unknown_property(self):
        c = cfg()
        c["workspaces"][0]["buttons"][0]["colour"] = "#000000"
        self.assertTrue(self.errors(c))

    def test_schema_rejects_bad_modifier(self):
        c = cfg()
        c["workspaces"][0]["buttons"][0]["action"]["modifiers"] = ["super"]
        self.assertTrue(self.errors(c))

    def test_schema_rejects_negative_delay(self):
        c = cfg()
        c["macros"][0]["steps"][0]["delayAfterMs"] = -1
        self.assertTrue(self.errors(c))

    def test_schema_requires_grid_for_deck(self):
        c = cfg()
        del c["workspaces"][0]["grid"]
        self.assertTrue(self.errors(c))

    def test_unknown_key(self):
        c = cfg()
        c["workspaces"][0]["buttons"][0]["action"]["key"] = "banana"
        self.assertHasError(c, "unknown key 'banana'")

    def test_modifier_name_is_not_a_key(self):
        c = cfg()
        c["workspaces"][0]["buttons"][0]["action"]["key"] = "cmd"
        self.assertHasError(c, "unknown key 'cmd'")

    def test_duplicate_workspace_id(self):
        c = cfg()
        c["workspaces"][1]["id"] = "editing"
        self.assertHasError(c, "duplicate workspace id 'editing'")

    def test_duplicate_button_id_across_workspaces(self):
        c = cfg()
        c["workspaces"][2] = {
            "id": "second",
            "name": "Second",
            "kind": "deck",
            "grid": {"rows": 1, "cols": 1},
            "buttons": [key_button("copy", 0, 0)],
        }
        self.assertHasError(c, "duplicate button id 'copy'")

    def test_missing_default_workspace(self):
        c = cfg()
        c["defaultWorkspace"] = "nope"
        self.assertHasError(c, "defaultWorkspace 'nope'")

    def test_missing_macro_reference(self):
        c = cfg()
        c["workspaces"][0]["buttons"][6]["action"]["macroId"] = "ghost"
        self.assertHasError(c, "unknown macro 'ghost'")

    def test_missing_workspace_reference(self):
        c = cfg()
        c["workspaces"][0]["buttons"][7]["action"]["workspaceId"] = "ghost"
        self.assertHasError(c, "unknown workspace 'ghost'")

    def test_button_outside_grid(self):
        c = cfg()
        c["workspaces"][0]["buttons"][0]["position"] = {"row": 3, "col": 0}
        self.assertHasError(c, "outside 3x3 grid")

    def test_span_outside_grid(self):
        c = cfg()
        c["workspaces"][0]["buttons"][7]["position"] = {"row": 2, "col": 2, "colSpan": 2}
        self.assertHasError(c, "outside 3x3 grid")

    def test_button_overlap(self):
        c = cfg()
        c["workspaces"][0]["buttons"][1]["position"] = {"row": 0, "col": 0}
        self.assertHasError(c, "overlaps button 'copy'")

    def test_span_overlap(self):
        c = cfg()
        # 'copy-paste' spans (2,0)-(2,1); put 'to-mouse' on top of col 1
        c["workspaces"][0]["buttons"][7]["position"] = {"row": 2, "col": 1}
        self.assertHasError(c, "overlaps button 'copy-paste'")

    def test_buttons_without_grid(self):
        c = cfg()
        c["workspaces"][1]["buttons"] = [key_button("stray", 0, 0)]
        self.assertHasError(c, "no grid")

    def test_macro_self_cycle(self):
        c = cfg()
        c["macros"].append(macro("loop", "loop"))
        self.assertHasError(c, "macro cycle: loop -> loop")

    def test_macro_two_step_cycle_reported_once(self):
        c = cfg()
        c["macros"] += [macro("a-m", "b-m"), macro("b-m", "a-m")]
        cycles = [e for e in self.errors(c) if e.startswith("macro cycle")]
        self.assertEqual(len(cycles), 1, cycles)

    def test_macro_depth_limit(self):
        c = cfg()
        chain = [macro(f"m{i}", f"m{i + 1}") for i in range(5)] + [macro("m5")]
        c["macros"] += chain
        self.assertHasError(c, "nesting depth")

    def test_macro_depth_at_limit_is_allowed(self):
        c = cfg()
        chain = [macro(f"m{i}", f"m{i + 1}") for i in range(4)] + [macro("m4")]
        c["macros"] += chain
        self.assertEqual(self.errors(c), [])

    def test_mouse_move_needs_delta(self):
        c = cfg()
        c["workspaces"][0]["buttons"][0]["action"] = {"type": "mouse", "op": "move"}
        self.assertHasError(c, "needs dx or dy")

    def test_risky_command_warns(self):
        c = cfg()
        c["workspaces"][0]["buttons"][0]["action"] = {"type": "command", "kind": "shell", "value": "ls"}
        errs, warns = validate_config.validate(c)
        self.assertEqual(errs, [])
        self.assertEqual(len(warns), 1)
        self.assertIn("disabled", warns[0])

    def test_safe_command_does_not_warn(self):
        c = cfg()
        c["workspaces"][0]["buttons"][0]["action"] = {"type": "command", "kind": "openApp", "value": "Safari"}
        errs, warns = validate_config.validate(c)
        self.assertEqual((errs, warns), ([], []))


class CliTests(unittest.TestCase):
    def run_cli(self, *paths):
        return subprocess.run(
            [sys.executable, str(ROOT / "tools" / "validate_config.py"), *map(str, paths)],
            capture_output=True,
            text=True,
        )

    def test_valid_file_exits_zero(self):
        r = self.run_cli(ROOT / "examples" / "default.deck.json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ok", r.stdout)

    def test_invalid_file_exits_one(self):
        c = cfg()
        c["defaultWorkspace"] = "nope"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text(json.dumps(c))
            r = self.run_cli(p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("error", r.stdout)

    def test_unreadable_file_exits_one(self):
        r = self.run_cli("/nonexistent/file.json")
        self.assertEqual(r.returncode, 1)

    def test_no_arguments_exits_two(self):
        self.assertEqual(self.run_cli().returncode, 2)


if __name__ == "__main__":
    unittest.main()
