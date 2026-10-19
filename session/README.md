# Session manager (Milestone 1.3)

Standard-library Python module. Recording and processing states are independent.
Default storage: `~/.mcu-meeting/sessions/`; override with `--sessions-dir` **before** the subcommand.

```sh
python3 -m session --sessions-dir /tmp/mcu-meeting-demo create --bundle-id us.zoom.xos
python3 -m session --sessions-dir /tmp/mcu-meeting-demo inspect SESSION_UUID
python3 -m session --sessions-dir /tmp/mcu-meeting-demo transition SESSION_UUID recording
python3 -m session --sessions-dir /tmp/mcu-meeting-demo recover
.venv/bin/python -m session --sessions-dir /tmp/mcu-meeting-demo validate SESSION_UUID
```

Each session directory contains `manifest.json`, `audio/`, and `events/`. Manifests are written via a temporary file, fsync, and atomic replacement. `recover` is read-only and reports sessions still marked recording; it **does not** assume a session has crashed or alter its state. Human/operator intervention is required to mark interruption. The capture binary is not wired to session management yet. `validate` requires the development-only `jsonschema` dependency.

Allowed capture transitions: `created -> recording|failed`, `recording -> completed|interrupted|failed`, `interrupted -> failed`. Terminal states cannot transition further. Processing stage states are preserved unchanged. The schema and lifecycle remain provisional under ADR-0001.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests use isolated temporary directories; no default sessions are modified.
