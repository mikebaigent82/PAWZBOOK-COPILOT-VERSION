# Roadmap

Each stage has exit criteria. A stage is done when they are met, not when the code is written.

| Stage | Name | Status |
|---|---|---|
| 0 | Project foundation | Done |
| 1 | Proof of technology | Next |
| 2 | Core application | Not started |
| 3 | Macro engine | Not started |
| 4 | Advanced integration | Not started |
| 5 | Polish and reliability | Not started |

## Stage 0: Project foundation

Architecture, protocol draft, decisions, config schema with validator and tests, test procedures, backlog.

Exit: documents reviewed; example config validates; validator tests pass.

## Stage 1: Proof of technology

Reliable iPhone-to-Mac input on the real equipment. See [POC.md](POC.md).

Exit: all pass criteria in POC.md met on the user's devices; ADR-0004 written (transport choice and measured numbers).

## Stage 2: Core application

Button grid, editor, persistent configuration, workspaces, keyboard and mouse modes on the proven input path.

Exit: a complete workspace can be created, edited, saved, and used without touching source; config survives app
relaunch and export/import; hardware checklist groups M, K, F still pass.

## Stage 3: Macro engine

Sequences, per-step delays, modifier combinations, text steps, mouse steps, nested macros, cancel, repeat.

Exit: macros run on the companion with correct timing; cancel and disconnect always end with everything released
(invariant I8); macro editor works without touching source.

## Stage 4: Advanced integration

Companion menu-bar polish, active-application detection with automatic workspace switching, opt-in commands
(open app/URL; shell and AppleScript behind explicit allowlist), status and diagnostics.

Exit: workspace switches to the bound app within 500 ms; commands that run code are off by default and cannot be
enabled from a config file alone.

## Stage 5: Polish and reliability

Reconnection soak tests, battery consumption, orientation, responsiveness, edge cases, accessibility, visual design.

Exit: a week of daily use with no stuck keys and no manual reconnects; battery cost measured and documented.
