# ADR-0001: Transport and input injection

Status: Accepted (transport choice pending Stage 1 measurements)

## Context

The goal is for an iPhone to behave as a keyboard, macro pad and mouse for a Mac. The original idea was the iPhone
acting as a Bluetooth HID device.

iOS does not allow this for third-party apps. CoreBluetooth's peripheral role cannot publish the HID service, and
the supported ways to get HID behavior require hardware or entitlements not available to an ordinary app. This is
the standing behavior of the platform; Stage 1 confirms it on the actual devices rather than assuming it (spike
S0 in [POC.md](../POC.md)).

## Decision

1. The Mac runs a **companion app** that receives input events from the iPhone and injects them using
   Quartz Event Services (`CGEvent`, posted to the HID event tap).
2. The iPhone app never touches input injection. It only produces events for the input engine to send.
3. The transport is **pluggable behind one protocol interface** so the choice can be changed after measurement
   without touching UI or companion logic. Candidates:

| Transport | Pros | Cons |
|---|---|---|
| LAN (Bonjour + TCP/WebSocket via Network.framework) | Lowest effort, good latency, debuggable | Needs shared Wi-Fi; reconnect depends on network |
| BLE custom GATT service | No Wi-Fi needed, low power | Higher/variable latency, throughput limits, more reconnect edge cases |
| USB (usbmuxd tunnel) | Lowest latency, most reliable | Wired; not the "wireless" goal, but a useful fallback |
| MultipeerConnectivity | Easy peer discovery, mixed radios | Less control, opaque behavior |

4. Start with the LAN transport as the primary candidate and BLE as the second spike. Pick by the measured criteria
   in [POC.md](../POC.md).

## Consequences

- The companion is a required component; installation involves granting Accessibility permission.
- CGEvent injection does not work at the login window or pre-boot prompts, and apps with Secure Keyboard Entry
  enabled may ignore it. Documented as known limitations, not bugs.
- A hardware HID dongle (e.g. a microcontroller acting as a USB/BLE keyboard) remains a possible future transport
  for the cases above. It would slot in behind the same transport interface. Tracked in the backlog.

## Alternatives rejected

- **iPhone as native Bluetooth HID peripheral:** not available to third-party iOS apps.
- **Cloud relay:** adds latency and a failure mode for no benefit.
