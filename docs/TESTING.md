# Testing

## Layers

| Layer | What | Where it runs | Status |
|---|---|---|---|
| Config tests | Schema and semantic validation of configs | Any machine: `python3 -m unittest discover -s tests -v` | Exists |
| Protocol and invariant tests | Simulated sender plus fake injector; fuzzed disconnects, drops, reordering; asserts nothing is left held | Mac, no devices | Stage 1 (B-005) |
| Hardware checklist | The tables below, on the real iPhone and Mac | Manual | Stage 1 onward |
| Soak | Long runs at a steady event rate with periodic faults | Real devices, scripted | Stage 5 (B-050) |

## Rules

- Any change to input handling re-runs the affected checklist groups before merge.
- A failure of a group F (failure) row blocks release. Stuck keys are never "known issues".
- Log each run in `docs/test-results/YYYY-MM-DD-<topic>.md` with the build, devices, OS versions, transport and the
  result of every row run.

## Result log template

```
# <date> <topic>
Build: <commit>      Transport: <LAN|BLE|USB>
iPhone: <model, iOS>  Mac: <model, macOS>   Network: <description>

| ID | Result (pass/fail/skip) | Notes |
```

## Hardware checklist

Use a plain text editor (TextEdit in plain-text mode) unless the row says otherwise.

### M: Modifiers

| ID | Procedure | Pass criteria |
|---|---|---|
| M-01 | Tap Cmd+C then Cmd+V on selected text | Text copied and pasted |
| M-02 | Tap Cmd+Z, then Cmd+Shift+Z | Undo, then redo |
| M-03 | Tap Shift+a | Capital `A` |
| M-04 | Tap Opt+e, then e | Accent composes as on a physical keyboard |
| M-05 | Tap Ctrl+arrowLeft / arrowRight | Switches Spaces |
| M-06 | Hold Cmd, tap Tab several times, release Cmd | App switcher stays open while Cmd held, selects on release |
| M-07 | Hold Cmd, click a link in Safari | Opens in a new tab |
| M-08 | Hold Opt, click and drag in Finder | Item is copied, not moved |
| M-09 | Hold Shift, then tap a letter, then release | Capital letter; the next plain letter is lowercase |
| M-10 | Cmd+Opt+Esc | Force Quit window opens |
| M-11 | Cmd+Space | Spotlight opens |
| M-12 | Press and release each of Cmd, Opt, Ctrl, Shift alone | No stuck state: Mac keyboard viewer shows all four released |

### K: Keys

| ID | Procedure | Pass criteria |
|---|---|---|
| K-01 | Tap every letter and digit | Each appears once |
| K-02 | Tap return, tab, space, delete, forwardDelete, escape | Each behaves correctly |
| K-03 | Tap arrows, home, end, pageUp, pageDown | Each behaves correctly |
| K-04 | Tap F1–F12 | Mapped function or app behavior occurs |
| K-05 | Tap a key 200 times rapidly | Exactly 200 characters, none dropped or doubled |
| K-06 | Send `text` of 500 characters including punctuation | Typed exactly |
| K-07 | Hold a key for 3 s | Key repeats as with a physical keyboard, then stops on release |

### P: Pointer

| ID | Procedure | Pass criteria |
|---|---|---|
| P-01 | Drag a finger across the trackpad surface | Cursor follows without lag or jumps |
| P-02 | Left, right, middle click; double and triple click | Correct behavior in Finder and a text editor |
| P-03 | Scroll up and down in a long page | Smooth and in the expected direction |
| P-04 | Press-hold and drag to move a window | Window moves; releases cleanly |

### F: Failure and safety (blocking)

Repeat each row 20 times. After each, open the keyboard viewer and type normally to confirm nothing is stuck.

| ID | Procedure | Pass criteria |
|---|---|---|
| F-01 | Hold Cmd on the iPhone, then force-quit the iPhone app | Cmd released within 1 s |
| F-02 | Hold Cmd, then turn iPhone Wi-Fi/Bluetooth off | Cmd released within 1 s |
| F-03 | Hold Cmd, then lock the iPhone | Cmd released immediately |
| F-04 | Hold Cmd, then switch to another iPhone app | Cmd released immediately |
| F-05 | Hold Cmd, then rotate the iPhone | Cmd released, no stuck state |
| F-06 | Hold Cmd, then put the Mac to sleep from the menu | Nothing held on wake |
| F-07 | Hold Cmd, then quit the companion | Cmd released |
| F-08 | Hold Cmd, then kill -9 the companion process | Cmd not stuck, verified by typing. If it is stuck, a watchdog helper is needed (open question, record the finding) |
| F-09 | Run a macro that presses Cmd+Shift, disconnect mid-macro | Everything released |
| F-10 | Hold a mouse button, disconnect | Button released |
| F-11 | Hold Cmd+Opt+Ctrl+Shift simultaneously, then trigger each fault above in turn | All four released every time |
| F-12 | Tap rapidly while toggling Wi-Fi on the iPhone | No stuck keys; events either arrive or are dropped whole |

### R: Reconnection

| ID | Procedure | Pass criteria |
|---|---|---|
| R-01 | Mac sleeps 1 min, then wakes | iPhone reconnects without user action within 5 s |
| R-02 | iPhone app backgrounded for 1 min, then foregrounded | Reconnects within 2 s |
| R-03 | Companion quit and relaunched | iPhone reconnects within 5 s |
| R-04 | Router restarted (LAN transport) | Reconnects when network returns, within 10 s of it being back |
| R-05 | iPhone and Mac idle connected for 1 hour | Still connected; first press works with no delay |
| R-06 | Move out of range, then return (BLE) | Reconnects without user action |

### L: Latency

| ID | Procedure | Pass criteria |
|---|---|---|
| L-01 | 1000 `ping`/`pong` at 20/s | p50 and p95 within the POC.md targets |
| L-02 | Same while Mac is under load (video playing, build running) | p95 within 2x the idle target |
| L-03 | Same with iPhone on low-power mode | Reported; no pass threshold, informs Stage 5 |

### X: Known limitations (verify and document, not pass/fail)

| ID | Procedure | Expected |
|---|---|---|
| X-01 | Type at the macOS login window | Injection ignored |
| X-02 | Type in a Terminal with Secure Keyboard Entry on | May be ignored |
| X-03 | Type into a password field | Observe and document |

## Config tests

`tests/test_validate_config.py` covers: the shipped example validates; every semantic rule has a failing case
(unknown key, duplicate ids, missing macro or workspace, macro cycle, grid overlap, button outside grid). A new
rule needs a new failing test first.
