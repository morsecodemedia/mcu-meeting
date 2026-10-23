import tempfile
import unittest
import wave
from pathlib import Path
from session import manager
from session.dual_recording import record_dual
from session.recording import CaptureFailed

FAKE = '''#!/usr/bin/env python3
import argparse, signal, time, wave, sys
p=argparse.ArgumentParser()
p.add_argument('record',nargs='?') if '--bundle-id' not in sys.argv else None
p.add_argument('--bundle-id'); p.add_argument('--output',required=True); p.add_argument('--duration',type=float)
a=p.parse_args()
if 'fail' in sys.argv[0]: sys.exit(7)
stop=False
def handler(*args):
 global stop
 stop=True
signal.signal(signal.SIGINT,handler)
start=time.monotonic()
while not stop and time.monotonic()-start < (a.duration or 30): time.sleep(.03)
with wave.open(a.output,'wb') as w:
 w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(b'\\x01\\x00'*4800)
'''

class DualTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name);self.sessions=self.root/'sessions'
  for name in ('app','mic','fail'):
   p=self.root/name;p.write_text(FAKE);p.chmod(0o700)
 def tearDown(self): self.tmp.cleanup()
 def test_success(self):
  result=record_dual(self.sessions,'com.google.Chrome',self.root/'app',self.root/'mic',duration=.5)
  self.assertEqual(result['capture']['state'],'completed')
  self.assertEqual({x['kind'] for x in result['artifacts']},{'application_audio','microphone_audio'})
  self.assertTrue((self.sessions/result['session_id']/'events/capture-timing.json').exists())
 def test_failure(self):
  with self.assertRaises(CaptureFailed) as err:
   record_dual(self.sessions,'com.google.Chrome',self.root/'fail',self.root/'mic',duration=.5)
  self.assertEqual(manager.load(self.sessions,err.exception.session_id)['capture']['state'],'failed')
 def test_missing_binary(self):
  with self.assertRaises(ValueError):record_dual(self.sessions,'com.google.Chrome',self.root/'app',self.root/'missing')
  self.assertFalse(self.sessions.exists())

if __name__=='__main__': unittest.main()
