# Stage 1: Proof of technology

Purpose: prove input works reliably on the real iPhone and Mac before building any real interface. Throwaway UI is
fine: one screen, a few buttons, a log. Code from the spikes that survives goes into `packages/DeckCore`.

Record results in `docs/test-results/` using the template in [TESTING.md](TESTING.md).

## Spikes

| ID | Spike | What it proves |
|---|---|---|
| S0 | Confirm the platform limit: attempt to publish a HID service from an iPhone app and have the Mac discover it as a keyboard | Settles [ADR-0001](adr/0001-transport-and-input-injection.md) on the real devices. Expected result: fails. Takes under an hour. |
| S1 | Mac companion injects keys and mouse from a local test harness (no iPhone) | `CGEvent` injection works; Accessibility permission flow; correct Cmd/Opt/Ctrl/Shift behavior; confirms the open questions in PROTOCOL |
| S2 | LAN transport: iPhone discovers the companion via Bonjour, sends `tap`, `down`/`up`, `mouse_move`, `ping` | End-to-end path and latency over Wi-Fi |
| S3 | BLE transport: same messages over a custom GATT service | End-to-end path and latency over BLE, no Wi-Fi |
| S4 | Safety rules: implement I1–I9 in the receiver and run the failure tests | No stuck keys under disconnect, sleep, kill |
| S5 | Optional: USB transport via usbmuxd | A wired fallback and a latency floor |

S1 comes first and needs only the Mac. S2 and S3 are independent of each other.

## Pass criteria

All measured on the user's actual iPhone and Mac, on their usual network, with the Mac otherwise idle.

| Criterion | Target |
|---|---|
| Injection correctness | Every row of hardware checklist groups M (modifiers) and K (keys) passes |
| Latency, touch to injected event, p50 | ≤ 15 ms (LAN), ≤ 40 ms (BLE) |
| Latency, p95 | ≤ 30 ms (LAN), ≤ 80 ms (BLE) |
| Stuck keys in failure tests (checklist group F) | Zero, across 20 repetitions each |
| Reconnect after Mac sleep/wake | ≤ 5 s without user action |
| Reconnect after iPhone app background/foreground | ≤ 2 s without user action |
| Dropped events in a 10-minute soak at 20 events/s | 0 |

Latency is measured as round-trip `ping`/`pong` divided by two, plus the companion's own log of time from receipt
to post. These are initial targets; revise them in the decision record once real numbers exist.

## Decision gate

At the end of Stage 1 write ADR-0004 stating the primary transport, the fallback, the final CGEvent configuration,
and the measured numbers. Stage 2 does not start until it exists.

Selection rule: choose the transport that meets all pass criteria. If both do, prefer the one with fewer
reconnect failures in the soak test, then the lower p95 latency. If neither does, the first fix is the transport
configuration, and only then reconsider the design.
