#!/usr/bin/env python3
"""Validate a Command Deck config: JSON Schema plus cross-reference rules.

Usage: validate_config.py CONFIG.json [...]
Exit status: 0 if every file is valid (warnings allowed), 1 otherwise.
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "spec" / "deck-config.schema.json"
KEYS_PATH = ROOT / "spec" / "keys.json"

MAX_MACRO_DEPTH = 4
RISKY_COMMANDS = {"shell", "appleScript"}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _path(parts):
    return "/" + "/".join(str(p) for p in parts)


def _macro_refs(action):
    return [action["macroId"]] if action.get("type") == "macro" else []


def validate(config, schema=None, key_names=None):
    """Return (errors, warnings) as lists of strings."""
    schema = schema or _load(SCHEMA_PATH)
    key_names = key_names if key_names is not None else set(_load(KEYS_PATH)["keys"])

    errors = [
        f"{_path(e.absolute_path)}: {e.message}"
        for e in sorted(Draft202012Validator(schema).iter_errors(config), key=lambda e: list(map(str, e.absolute_path)))
    ]
    if errors:
        # Semantic checks assume the shape is right.
        return errors, []

    warnings = []
    workspaces = config["workspaces"]
    macros = config.get("macros", [])

    def check_unique(items, what):
        seen = set()
        for item in items:
            if item["id"] in seen:
                errors.append(f"duplicate {what} id '{item['id']}'")
            seen.add(item["id"])
        return seen

    workspace_ids = check_unique(workspaces, "workspace")
    macro_ids = check_unique(macros, "macro")
    button_list = [(w, b) for w in workspaces for b in w.get("buttons", [])]
    check_unique([b for _, b in button_list], "button")

    default = config.get("defaultWorkspace")
    if default is not None and default not in workspace_ids:
        errors.append(f"defaultWorkspace '{default}' does not exist")

    def check_action(action, where):
        kind = action["type"]
        if kind == "key":
            if action["key"] not in key_names:
                errors.append(f"{where}: unknown key '{action['key']}'")
        elif kind == "macro":
            if action["macroId"] not in macro_ids:
                errors.append(f"{where}: unknown macro '{action['macroId']}'")
        elif kind == "workspace":
            if action["workspaceId"] not in workspace_ids:
                errors.append(f"{where}: unknown workspace '{action['workspaceId']}'")
        elif kind == "mouse":
            op = action["op"]
            if op in ("move", "scroll") and "dx" not in action and "dy" not in action:
                errors.append(f"{where}: mouse {op} needs dx or dy")
        elif kind == "command":
            if action["kind"] in RISKY_COMMANDS:
                warnings.append(
                    f"{where}: '{action['kind']}' command stays disabled until enabled in the companion"
                )

    # Buttons: action references, grid bounds, overlaps.
    for ws in workspaces:
        grid = ws.get("grid")
        occupied = {}
        for b in ws.get("buttons", []):
            where = f"workspace '{ws['id']}' button '{b['id']}'"
            check_action(b["action"], where)
            if grid is None:
                errors.append(f"{where}: workspace has buttons but no grid")
                continue
            pos = b["position"]
            r0, c0 = pos["row"], pos["col"]
            r1, c1 = r0 + pos.get("rowSpan", 1), c0 + pos.get("colSpan", 1)
            if r1 > grid["rows"] or c1 > grid["cols"]:
                errors.append(f"{where}: outside {grid['rows']}x{grid['cols']} grid")
                continue
            for r in range(r0, r1):
                for c in range(c0, c1):
                    other = occupied.get((r, c))
                    if other is not None:
                        errors.append(f"{where}: overlaps button '{other}' at row {r}, col {c}")
                    else:
                        occupied[(r, c)] = b["id"]

    # Macros: step actions, cycles, depth.
    macro_by_id = {m["id"]: m for m in macros}
    for m in macros:
        for i, step in enumerate(m["steps"]):
            check_action(step["action"], f"macro '{m['id']}' step {i}")

    cycles = set()

    def depth_of(macro_id, stack):
        if macro_id in stack:
            loop = stack[stack.index(macro_id):]
            # Canonical rotation so one cycle is reported once, whatever the entry point.
            start = loop.index(min(loop))
            loop = loop[start:] + loop[:start]
            cycles.add(tuple(loop))
            return 0
        macro = macro_by_id.get(macro_id)
        if macro is None:
            return 0
        deepest = 0
        for step in macro["steps"]:
            for ref in _macro_refs(step["action"]):
                deepest = max(deepest, 1 + depth_of(ref, stack + [macro_id]))
        return deepest

    for m in macros:
        depth = depth_of(m["id"], [])
        if depth > MAX_MACRO_DEPTH:
            errors.append(f"macro '{m['id']}': nesting depth {depth} exceeds {MAX_MACRO_DEPTH}")
    for loop in sorted(cycles):
        errors.append("macro cycle: " + " -> ".join(loop + (loop[0],)))

    return errors, warnings


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    status = 0
    schema = _load(SCHEMA_PATH)
    keys = set(_load(KEYS_PATH)["keys"])
    for name in argv[1:]:
        try:
            config = _load(name)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"{name}: cannot read: {exc}")
            status = 1
            continue
        errors, warnings = validate(config, schema, keys)
        for w in warnings:
            print(f"{name}: warning: {w}")
        for e in errors:
            print(f"{name}: error: {e}")
        if errors:
            status = 1
        else:
            print(f"{name}: ok")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
