"""CLI: python3 -m session ..."""
import argparse
import json
import sys
from pathlib import Path
from . import manager


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="MCU Meeting session management")
    parser.add_argument("--sessions-dir", type=Path, default=manager.default_root())
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Create a durable session")
    create.add_argument("--bundle-id", required=True)
    for name in ("inspect", "validate"):
        commands.add_parser(name).add_argument("session_id")
    move = commands.add_parser("transition", help="Explicit capture-state transition")
    move.add_argument("session_id")
    move.add_argument("state", choices=sorted(set().union(*manager.TRANSITIONS.values())))
    commands.add_parser("recover", help="Read-only scan for unfinished recordings")
    rec = commands.add_parser("record", help="Create session and run ten-second macOS capture")
    rec.add_argument("--bundle-id", required=True)
    rec.add_argument("--capture-bin", type=Path, default=Path("capture/macos/.build/release/mcu-capture"))
    rec.add_argument("--duration", type=float, help="Maximum recording duration in seconds; otherwise Ctrl+C to stop")
    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            from .recording import record
            data = record(args.sessions_dir, args.bundle_id, args.capture_bin, duration=args.duration)
        elif args.command == "create":
            data = manager.create(args.sessions_dir, args.bundle_id)
        elif args.command == "inspect":
            data = manager.load(args.sessions_dir, args.session_id)
        elif args.command == "transition":
            data = manager.transition(args.sessions_dir, args.session_id, args.state)
        elif args.command == "recover":
            data = manager.recovery_candidates(args.sessions_dir)
        else:
            data = manager.load(args.sessions_dir, args.session_id)
            # Schema validation is a development dependency, not a runtime dependency.
            from jsonschema import Draft202012Validator, FormatChecker
            schema = json.loads((Path(__file__).resolve().parent.parent / "contracts" / "session.schema.json").read_text())
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)
            data = {"valid": True, "session_id": args.session_id}
        print(json.dumps(data, indent=2))
        return 0
    except (OSError, ValueError, KeyError, ImportError) as exc:
        print(f"session error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"session error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
