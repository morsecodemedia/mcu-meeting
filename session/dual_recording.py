"""Dual-track recording with bounded coordinated shutdown and durable artifacts."""
from __future__ import annotations
import json
import math
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from . import manager
from .recording import CaptureFailed, verify_wav


def _binary(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f"capture executable missing or not executable: {path}")
    return str(path)


def record_dual(root, bundle_id, application_bin, microphone_bin, *, duration=None, stop_timeout=15.0):
    app = _binary(application_bin)
    mic = _binary(microphone_bin)
    if not bundle_id.strip():
        raise ValueError("bundle ID cannot be empty")
    if duration is not None and (not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration) or not 0 < duration <= 86400):
        raise ValueError("duration must be finite and > 0 and <= 86400")
    root = Path(root).expanduser()
    data = manager.create(root, bundle_id)
    sid = data['session_id']
    folder = root / sid
    commands = {
        'application': [app, '--bundle-id', bundle_id, '--output', str(folder/'audio/application.wav')],
        'microphone': [mic, 'record', '--output', str(folder/'audio/microphone.wav')],
    }
    if duration is not None:
        for command in commands.values():
            command.extend(['--duration', str(duration)])
    children = {}
    logs = {}
    timing = {'schema_version': 1, 'clock': 'monotonic', 'precision': 'process-launch-only', 'sources': {}}
    stopping = False
    stop_reason = None
    deadline = None
    failure = None
    interrupted = False

    def request_stop(reason):
        nonlocal stopping, stop_reason, deadline
        if stopping:
            return
        stopping, stop_reason = True, reason
        deadline = time.monotonic() + stop_timeout
        for child in children.values():
            if child.poll() is None:
                child.send_signal(signal.SIGINT)

    manager.transition(root, sid, 'recording')
    try:
        for name, argv in commands.items():
            log = tempfile.TemporaryFile(mode='w+t')
            logs[name] = log
            launched = time.monotonic()
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=log, text=True, start_new_session=True)
            children[name] = child
            timing['sources'][name] = {'launched_monotonic': launched, 'exited_monotonic': None, 'exit_code': None}
        while True:
            try:
                now = time.monotonic()
                for name, child in children.items():
                    rc = child.poll()
                    info = timing['sources'][name]
                    if rc is not None and info['exited_monotonic'] is None:
                        info['exited_monotonic'] = now
                        info['exit_code'] = rc
                        if rc != 0 and failure is None:
                            failure = f'{name} capture exited {rc}'
                if failure and not stopping:
                    request_stop('failure')
                if all(c.poll() is not None for c in children.values()):
                    break
                if not stopping and any(c.poll() is not None for c in children.values()):
                    if duration is None:
                        failure = failure or 'one capture exited before its sibling'
                        request_stop('early-exit')
                    elif deadline is None:
                        # Independent recorders may finalize at slightly
                        # different times after the same duration.
                        deadline = now + stop_timeout

                if not stopping and deadline is not None and now >= deadline:
                    failure = failure or 'duration-limited sibling did not finish'
                    request_stop('duration-timeout')
                if stopping and now >= deadline:
                    failure = failure or 'capture shutdown timed out'
                    break
                time.sleep(0.1)
            except KeyboardInterrupt:
                if stopping:
                    failure = 'second interrupt during shutdown'
                    break
                interrupted = True
                request_stop('user')
        if failure:
            raise RuntimeError(failure)
        for name, child in children.items():
            if child.returncode != 0:
                raise RuntimeError(f'{name} capture exited {child.returncode}')
        artifacts = []
        for name, filename, kind in (('application','application.wav','application_audio'),('microphone','microphone.wav','microphone_audio')):
            path = folder/'audio'/filename
            artifacts.append({'kind':kind,'path':f'audio/{filename}','sha256':verify_wav(path)})
        timing['stop_reason'] = stop_reason or ('duration' if duration is not None else 'natural')
        timing['launch_offset_seconds'] = timing['sources']['microphone']['launched_monotonic'] - timing['sources']['application']['launched_monotonic']
        # Timing file is diagnostic only, not an audio synchronization contract.
        timing_path = folder/'events/capture-timing.json'
        with timing_path.open('w') as stream:
            json.dump(timing, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        current = manager.load(root, sid)
        current['artifacts'].extend(artifacts)
        manager._write_atomic(folder/'manifest.json', current)
        manager.transition(root, sid, 'completed')
        return manager.load(root, sid)
    except BaseException as exc:
        state = 'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed'
        try:
            manager.transition(root, sid, state)
        except Exception:
            pass
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise CaptureFailed(sid, str(exc)) from exc
    finally:
        for child in children.values():
            if child.poll() is None:
                child.kill()
        for child in children.values():
            child.wait()
        for log in logs.values():
            log.close()
