"""Host transport regressions; tiny process bytes, never a fake DB result."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
PREAMBLE = "import importlib.util,subprocess,sys; s=importlib.util.spec_from_file_location('transport', " + repr(str(ROOT/'scripts/preview_launcher.py')) + "); m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"


class PreviewTransportTests(unittest.TestCase):
    def test_complete_frames_are_forwarded_byte_for_byte(self):
        raw = b'{"jsonrpc":"2.0","id":1,"result":{}}\n{"jsonrpc":"2.0","id":2,"result":{}}\n'
        code = PREAMBLE + "c=subprocess.Popen([sys.executable,'-c'," + repr('import os;os.write(1,'+repr(raw)+')') + "],stdout=subprocess.PIPE);sys.exit(m.mcp_wait(c))"
        p = subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=4)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, raw)

    def test_full_host_pipe_obeys_five_second_frame_deadline(self):
        rd, wr = os.pipe()
        p = None
        try:
            os.set_blocking(wr, False)
            try:
                while True:
                    os.write(wr, b'x'*4096)
            except BlockingIOError:
                pass
            os.set_blocking(wr, True)
            code = PREAMBLE + "c=subprocess.Popen([sys.executable,'-c','print(\"{}\",flush=True)'],stdout=subprocess.PIPE)\ntry:\n m.mcp_wait(c)\nexcept TimeoutError:\n c.kill();c.wait();sys.exit(124)\n"
            p = subprocess.Popen([sys.executable, '-c', code], stdout=wr, stderr=subprocess.PIPE)
            os.close(wr)
            wr = None
            self.assertEqual(p.wait(timeout=7), 124)
        finally:
            if p is not None:
                if p.poll() is None:
                    p.kill()
                    p.wait(timeout=2)
                p.stderr.close()
            os.close(rd)
            if wr is not None:
                os.close(wr)


if __name__ == '__main__':
    unittest.main()
