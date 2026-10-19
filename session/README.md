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

Each session directory contains `manifest.json`, `audio/`, and `events/`. Manifests are written via a temporary file, fsync, and atomic replacement. `recover` is read-only and reports sessions still marked recording; it **does not** assume a session has crashed or alter its state. Human/operator intervention is required to mark interruption. The experimental `record` command integrates the Swift capture binary with durable session management. `validate` requires the development-only `jsonschema` dependency.

Allowed capture transitions: `created -> recording|failed`, `recording -> completed|interrupted|failed`, `interrupted -> failed`. Terminal states cannot transition further. Processing stage states are preserved unchanged. The schema and lifecycle remain provisional under ADR-0001.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests use isolated temporary directories; no default sessions are modified.

## Integrated capture (Milestone 1.4)

Build Swift capture first with `swift build -c release --package-path capture/macos`.
Then run from repository root:

```sh
python3 -m session --sessions-dir /tmp/mcu-meeting-demo record --bundle-id com.google.Chrome
```

`record` creates a session before launching the managed macOS capture process
binary. It writes `audio/application.wav`, validates PCM WAV frames, computes
SHA-256, and atomically registers the artifact before marking capture completed.
A nonzero exit or invalid audio marks capture failed; interruption marks it
interrupted. A crash before finalization may leave `recording`, which the
read-only `recover` command can discover. Processing stages are not changed.
Use `--capture-bin PATH` after `record` to select another executable. This is
not yet a full-meeting recorder or a microphone recorder.

## Long-running capture orchestration (Milestone 1.5C)

Run `python3 -m session record --bundle-id com.google.Chrome --duration 30`
for a bounded recording, or omit `--duration` and press Ctrl+C once to request
a graceful stop. Python launches Swift in a separate process session, forwards
SIGINT, waits up to 15 seconds for WAV finalization, and validates the artifact
before marking the session completed. A forced kill is never successful.

Python still has no automatic crash recovery or persistent capture PID registry.
A Python crash may leave a running Swift child; inspect processes and the
`recover` report before taking action. Do not run unattended recordings yet.
