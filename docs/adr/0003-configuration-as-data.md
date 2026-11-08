# ADR-0003: Configuration as versioned, schema-validated data

Status: Accepted

## Context

A core requirement is that an entire workspace can be built without touching source code.

## Decision

- All workspaces, buttons and macros are stored as JSON described by
  [spec/deck-config.schema.json](../../spec/deck-config.schema.json), with an integer `schemaVersion`.
- Validation has two layers: JSON Schema (shape) and semantic checks (references, key names, cycles, grid layout),
  implemented in [tools/validate_config.py](../../tools/validate_config.py). The in-app editor must enforce the same
  rules; the Swift implementation is tested against the same example and failure fixtures.
- Key names come from one table, [spec/keys.json](../../spec/keys.json), shared by the validator, editor and companion.
- Config is exportable and importable as a single file, and edited configs are validated before being saved.
- Schema changes bump `schemaVersion` and ship with a migration.

## Consequences

- Backup, sharing and version-controlling a layout are trivial.
- Commands that run code on the Mac (`shell`, `appleScript`) are expressible in config, so the companion treats
  them as disabled until the user explicitly enables them there. A config file alone must never be able to run code.
