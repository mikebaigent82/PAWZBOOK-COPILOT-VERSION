# Mac Command Deck

Turn an iPhone into a programmable keyboard, macro controller and mouse for a Mac.

This is a daily-use instrument, not a demo. Order of priorities: **reliable → customizable → beautiful**.

## Status

Stage 0 complete (project foundation). Stage 1 (proof of technology, on real hardware) is next.
See [docs/ROADMAP.md](docs/ROADMAP.md).

## Key technical finding

iOS does not let third-party apps act as a Bluetooth HID peripheral, so the iPhone cannot appear to the Mac as a
native keyboard or mouse. Command Deck therefore uses a **Mac companion app that receives input events from the
iPhone and injects them with CGEvent**. The companion is required, not optional. Details and the transports being
evaluated: [ADR-0001](docs/adr/0001-transport-and-input-injection.md).

Consequences to know up front: the Mac needs Accessibility permission granted to the companion, and injected input
does not work at the login screen or pre-boot (FileVault) prompts.

## Three separated systems

| System | Responsibility |
|---|---|
| **iPhone app** | Everything you touch: grids, editor, workspaces. Holds no transport or injection logic. |
| **Input engine** | Shared Swift package: wire protocol, transport, event model, stuck-key safety. Used by both ends. |
| **Mac companion** | Receives events, injects them, runs macros, later: app detection and automation. |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Documents

| Doc | Purpose |
|---|---|
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Components, data flow, planned repo layout |
| [PROTOCOL](docs/PROTOCOL.md) | Wire protocol and the invariants that prevent stuck keys |
| [POC](docs/POC.md) | Stage 1 spikes, pass/fail criteria, decision gate |
| [ROADMAP](docs/ROADMAP.md) | Five stages with exit criteria |
| [BACKLOG](docs/BACKLOG.md) | Prioritized work items |
| [TESTING](docs/TESTING.md) | Test layers and the hardware checklist |
| [adr/](docs/adr) | Architecture decision records |

## Configuration without code

Every button, macro and workspace is data, described by [spec/deck-config.schema.json](spec/deck-config.schema.json).
A working example is in [examples/default.deck.json](examples/default.deck.json).

Validate a config (schema plus cross-reference checks: unknown keys, bad macro/workspace references, macro cycles,
grid overlaps):

```sh
pip install -r requirements-dev.txt
python3 tools/validate_config.py examples/default.deck.json
python3 -m unittest discover -s tests -v
```

## Workflow

- Branch per change; `main` stays releasable.
- Decisions that are hard to reverse get an ADR in `docs/adr/`.
- A change that touches input handling must pass the relevant rows of the hardware checklist in
  [docs/TESTING.md](docs/TESTING.md) before merge, and the result is logged.
