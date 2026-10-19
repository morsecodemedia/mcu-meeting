import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from session import manager
from session.recording import CaptureFailed, record

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'sessions'
        self.bin = Path(self.tmp.name) / 'capture'
        self.bin.write_text('#!/bin/sh\nexit 0\n')
        self.bin.chmod(0o700)

    def tearDown(self):
        self.tmp.cleanup()

    def test_duration_forwarded_and_failed_capture(self):
        seen = []
        def runner(argv, **kwargs):
            seen.extend(argv)
            return SimpleNamespace(returncode=9, stderr='simulated failure')
        with self.assertRaises(CaptureFailed):
            record(self.root, 'us.zoom.xos', self.bin, runner=runner, duration=60)
        self.assertEqual(seen[-2:], ['--duration', '60'])
        sid = next(self.root.iterdir()).name
        self.assertEqual(manager.load(self.root, sid)['capture']['state'], 'failed')

    def test_invalid_duration_does_not_create_session(self):
        for value in (0, -1, 86401):
            with self.assertRaises(ValueError):
                record(self.root, 'us.zoom.xos', self.bin, duration=value)
        self.assertFalse(self.root.exists())

    def test_keyboard_interrupt_remains_interrupted(self):
        def runner(argv, **kwargs):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            record(self.root, 'us.zoom.xos', self.bin, runner=runner)
        sid = next(self.root.iterdir()).name
        self.assertEqual(manager.load(self.root, sid)['capture']['state'], 'interrupted')
