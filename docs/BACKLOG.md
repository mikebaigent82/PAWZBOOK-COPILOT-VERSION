# Backlog

Priority: P0 blocks the stage, P1 should ship in the stage, P2 nice to have.

## Stage 1: Proof of technology

| ID | P | Item |
|---|---|---|
| B-001 | P0 | S0: confirm HID peripheral is unavailable on the real iPhone |
| B-002 | P0 | S1: companion injection harness (keys, modifiers, mouse) |
| B-003 | P0 | S2: LAN transport spike with Bonjour discovery |
| B-004 | P0 | S3: BLE transport spike |
| B-005 | P0 | S4: implement invariants I1–I9 and run checklist group F |
| B-006 | P0 | Latency measurement tooling (ping/pong plus companion-side log) |
| B-007 | P0 | ADR-0004: transport decision with measured numbers |
| B-008 | P2 | S5: USB transport spike |

## Stage 2: Core application

| ID | P | Item |
|---|---|---|
| B-010 | P0 | `DeckCore` Swift package: config models, key table, protocol codec |
| B-011 | P0 | Swift validator matching `tools/validate_config.py` on shared fixtures |
| B-012 | P0 | Button grid renderer for `deck` workspaces |
| B-013 | P0 | Button editor: label, icon, color, action, position |
| B-014 | P0 | Config persistence, export, import, migration scaffolding |
| B-015 | P0 | Workspace switcher and workspace editor |
| B-023 | P0 | Pairing and authentication between iPhone and companion (see Q-001); the companion injects keystrokes, so an unauthenticated listener is a security hole |
| B-016 | P1 | Keyboard mode with sticky and hold modifiers |
| B-017 | P1 | Mouse mode: trackpad surface, buttons, scroll |
| B-018 | P1 | Haptic feedback per button, configurable |
| B-019 | P1 | Connection status UI and manual reconnect |
| B-020 | P1 | Companion menu-bar app: status, permission check, launch at login |
| B-021 | P2 | Button duplication and drag to reorder |
| B-022 | P2 | Icon picker for SF Symbols |

## Stage 3: Macro engine

| ID | P | Item |
|---|---|---|
| B-030 | P0 | Macro model, flattening of nested macros on the iPhone |
| B-031 | P0 | Companion macro runner with release-on-end (I8) |
| B-032 | P0 | Macro editor: steps, delays, reorder |
| B-033 | P1 | Cancel and repeat (N times, while held) |
| B-034 | P1 | Text step with typing-speed control |
| B-035 | P2 | Record-a-macro from live key presses |
| B-036 | P2 | Media keys via system-defined events |

## Stage 4: Advanced integration

| ID | P | Item |
|---|---|---|
| B-040 | P0 | Active-app detection and workspace auto-switch |
| B-041 | P1 | Commands: open app, open URL |
| B-042 | P1 | Opt-in shell and AppleScript commands with companion-side allowlist |
| B-043 | P1 | Companion diagnostics view and log export |
| B-044 | P2 | Hardware HID dongle transport for login-window and pre-boot use |

## Stage 5: Polish and reliability

| ID | P | Item |
|---|---|---|
| B-050 | P0 | Reconnection soak test automation |
| B-051 | P0 | Battery consumption measurement |
| B-052 | P1 | Orientation and safe-area handling for all grids |
| B-053 | P1 | iPad layout |
| B-054 | P2 | Themes and visual design pass |
| B-055 | P2 | Widgets and Lock Screen shortcuts |

## Open items needing a decision

| ID | Question |
|---|---|
| Q-001 | Pairing and security model: who may connect to the companion on the LAN? Needed before Stage 2 ships beyond the author's own use. Candidate: pairing code, then a stored shared secret. |
