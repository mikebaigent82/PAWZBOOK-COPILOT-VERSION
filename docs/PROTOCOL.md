# Wire protocol (draft v0)

Draft for Stage 1. JSON messages are used first because they are easy to debug. If measurement shows encoding
cost matters, a binary encoding replaces them without changing semantics. The framing is transport-specific
(WebSocket text frame, or length-prefixed for BLE/USB).

## Message envelope

```json
{ "v": 0, "t": "<type>", "seq": 123, "ts": 1731045123456 }
```

`seq` increases by one per message within a session. `ts` is the sender clock in milliseconds and is used only for
latency measurement, never for ordering.

## Messages

| Type | Direction | Fields | Meaning |
|---|---|---|---|
| `hello` | iPhone → Mac | `deviceName`, `appVersion` | Opens a session |
| `hello_ack` | Mac → iPhone | `companionVersion`, `accessibility: bool` | Session accepted; reports whether injection is permitted |
| `tap` | iPhone → Mac | `key`, `mods[]` | Atomic press and release |
| `down` / `up` | iPhone → Mac | `key` (or modifier name) | Explicit hold and release |
| `hb` | iPhone → Mac | none | Heartbeat while anything is held |
| `text` | iPhone → Mac | `text` | Type a string |
| `mouse_move` | iPhone → Mac | `dx`, `dy` | Relative move |
| `mouse_button` | iPhone → Mac | `button`, `state` | `left`/`right`/`middle`, `down`/`up` |
| `click` | iPhone → Mac | `button`, `count` | Atomic click |
| `scroll` | iPhone → Mac | `dx`, `dy` | Scroll wheel (pixels) |
| `macro` | iPhone → Mac | `steps[]` | Run a sequence on the Mac (see below) |
| `macro_cancel` | iPhone → Mac | none | Abort a running macro |
| `release_all` | either | none | Release every held key and button |
| `ping` / `pong` | either | `ts` echoed | Round-trip latency |
| `bye` | either | none | Orderly close |

Key names and their macOS virtual key codes are defined in [spec/keys.json](../spec/keys.json). Modifier names are
`cmd`, `opt`, `ctrl`, `shift`, `fn`.

## Invariants: no stuck keys

These are the rules the whole input engine exists to uphold. Each has a test in [TESTING.md](TESTING.md).

| # | Rule |
|---|---|
| I1 | The receiver keeps its own table of held keys, modifiers and mouse buttons. It is the single source of truth for what is down on the Mac. |
| I2 | Modifier flags on every injected event are derived from the receiver's held-modifier table, never copied from the sender. |
| I3 | Modifier press and release are posted as real modifier events (`flagsChanged`), in addition to flags on key events, so apps that watch modifier state behave correctly (e.g. Cmd-click, Cmd-Tab hold). |
| I4 | Release-all runs on: session open, session close, transport error, heartbeat timeout, Mac sleep, Mac wake, screen lock, companion quit. |
| I5 | Heartbeat: while anything is held the sender sends `hb` at least every 200 ms. The receiver releases all if nothing is received for 1000 ms. |
| I6 | The sender sends `release_all` when the app backgrounds, is interrupted, a touch is cancelled, orientation changes mid-hold, or the editor opens. |
| I7 | Short presses (`tap`, `click`) are single atomic messages so a drop cannot leave a half-pressed key. |
| I8 | Macros run on the Mac. A macro ends with release of everything it pressed, on completion, cancel, error or disconnect. |
| I9 | Duplicate or out-of-order `seq` values are ignored for transports that can reorder. |

## Macro step

```json
{ "action": { "type": "key", "key": "c", "modifiers": ["cmd"] }, "delayAfterMs": 50 }
```

Same action shape as in the config schema, flattened by the iPhone before sending (nested macros are expanded, so
the Mac never resolves references).

## macOS modifier mapping

| Name | CGEventFlags | Virtual key (left) |
|---|---|---|
| `cmd` | `maskCommand` | 55 |
| `shift` | `maskShift` | 56 |
| `opt` | `maskAlternate` | 58 |
| `ctrl` | `maskControl` | 59 |
| `fn` | `maskSecondaryFn` | 63 |

The exact `CGEventSource` state and tap location to use are confirmed in spike S1 ([POC.md](POC.md)).

## Open questions (to resolve in Stage 1)

- Whether to attach a source with `.hidSystemState` or `.combinedSessionState` so modifier state interacts
  correctly with the physical keyboard.
- Whether `tap` hold time needs to exceed a few milliseconds for all target apps.
- Whether media keys (volume, brightness) need `NSEvent` system-defined events rather than key codes. Backlog.
