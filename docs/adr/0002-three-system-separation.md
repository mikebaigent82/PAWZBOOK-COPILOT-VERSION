# ADR-0002: Three separated systems

Status: Accepted

## Context

The product has an interface layer, an input layer and a computer-integration layer. Mixing them makes the stuck-key
and reconnect logic untestable and makes the UI hard to change.

## Decision

Three components with one-way dependencies:

- **iPhone app (UI)** depends on the input engine's public API only.
- **Input engine** (shared Swift package, no UI, no platform-specific injection) owns the protocol, transport
  abstraction, session state and the held-key safety rules. It compiles for iOS and macOS.
- **Mac companion** depends on the input engine, owns injection (`CGEvent`), macro execution, and later
  application detection and automation.

The input engine must be testable on a Mac without any device by pairing a simulated sender with a fake injector.

## Consequences

- The "stuck modifier" invariants live in one place and are covered by loopback tests.
- Macros execute on the companion (see [PROTOCOL.md](../PROTOCOL.md)), so timing is not at the mercy of the link.
- Slightly more up-front structure than a single app target. Accepted.
