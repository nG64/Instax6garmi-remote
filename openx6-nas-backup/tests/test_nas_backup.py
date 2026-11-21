"""Offline tests: a minimal WebDAV server in a thread plays the NAS.

Run from the component directory:  python3 -B -m unittest discover -s tests
"""
import importlib.util
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('nb', HERE.parent / 'src' / 'x6-nas-backup.py')
nb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nb)


class DAV(BaseHTTPRequestHandler):
    root: Path = None
    auth = None
    log = []

    def log_message(self, *a):
        pass

    def local(self, href=None):
        p = urllib.parse.unquote(urllib.parse.urlsplit(href or self.path).path)
        return self.root / p.lstrip('/')

    def reply(self, code, body=b''):
        self.send_response(code)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authed(self):
        if self.auth and self.headers.get('Authorization') != self.auth:
            self.reply(401)
            return False
        type(self).log.append((self.command, self.path))
        return True

    def do_PROPFIND(self):
        if not self.authed():
            return
        p = self.local()
        if not p.exists():
            return self.reply(404)
        size = '' if p.is_dir() else '<d:getcontentlength>%d</d:getcontentlength>' % p.stat().st_size
        self.reply(207, ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"><d:response>'
                         '<d:propstat><d:prop>%s</d:prop></d:propstat></d:response>'
                         '</d:multistatus>' % size).encode())

    def do_MKCOL(self):
        if not self.authed():
            return
        p = self.local()
        if p.exists():
            return self.reply(405)
        if not p.parent.exists():
            return self.reply(409)
        p.mkdir()
        self.reply(201)

    def do_PUT(self):
        if not self.authed():
            return
        p = self.local()
        if not p.parent.is_dir():
            return self.reply(409)
        n = int(self.headers['Content-Length'])
        with p.open('wb') as f:
            while n:
                b = self.rfile.read(min(n, 65536))
                if not b:
                    break
                f.write(b)
                n -= len(b)
        self.reply(201)

    def do_MOVE(self):
        if not self.authed():
            return
        os.replace(self.local(), self.local(self.headers['Destination']))
        self.reply(201)

    def do_DELETE(self):
        if not self.authed():
            return
        self.local().unlink(missing_ok=True)
        self.reply(204)


class Clock:
    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.nas = self.tmp / 'nas'
        (self.nas / 'x6').mkdir(parents=True)
        self.card = self.tmp / 'card'
        (self.card / 'DCIM' / 'Camera01').mkdir(parents=True)
        DAV.root, DAV.auth, DAV.log = self.nas, 'Basic dTpw', []   # u:p
        self.srv = ThreadingHTTPServer(('127.0.0.1', 0), DAV)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.clock = Clock()
        self.idle = True

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp)

    def make(self, **over):
        cfg = nb.validate(dict({'url': 'http://127.0.0.1:%d/x6' % self.srv.server_port,
                                'username': 'u', 'password': 'p', 'storages': ['sd'],
                                'settle_seconds': 60}, **over))
        return nb.Backup(cfg, data_dir=self.tmp / 'data', run_dir=self.tmp / 'run',
                         roots={'sd': str(self.card)}, idle=lambda: self.idle,
                         serial='CAM1', clock=self.clock)

    def media(self, name='VID_1.insv', size=3 * 1024 * 1024 + 7):
        p = self.card / 'DCIM' / 'Camera01' / name
        p.write_bytes(os.urandom(size))
        return p

    def settle(self, b):
        b.run_once()                 # first sighting
        self.clock.t += 120          # files now older than settle_seconds

    def remote(self, name='VID_1.insv'):
        return self.nas / 'x6' / 'CAM1' / 'sd' / 'DCIM' / 'Camera01' / name

    def test_uploads_settled_file_and_verifies(self):
        (self.tmp / 'data').mkdir()
        src = self.media()
        b = self.make()
        self.settle(b)
        self.assertEqual(b.run_once(), 1)
        self.assertEqual(self.remote().read_bytes(), src.read_bytes())
        self.assertFalse(self.remote('VID_1.insv.partial').exists())
        self.assertTrue(src.exists())     # never deleted by default
        st = json.loads((self.tmp / 'run' / 'status.json').read_text())
        self.assertEqual(st['state'], 'idle')

    def test_unsettled_file_waits(self):
        (self.tmp / 'data').mkdir()
        self.media()
        b = self.make()
        self.assertEqual(b.run_once(), 0)
        self.clock.t += 120
        self.media()                       # rewritten: still being recorded
        self.assertEqual(b.run_once(), 0)
        self.assertFalse(self.remote().exists())

    def test_second_pass_uploads_nothing_and_state_survives_restart(self):
        (self.tmp / 'data').mkdir()
        self.media()
        b = self.make()
        self.settle(b)
        b.run_once()
        DAV.log = []
        b2 = self.make()
        self.settle(b2)
        self.assertEqual(b2.run_once(), 0)
        self.assertNotIn('PUT', [m for m, _ in DAV.log])

    def test_busy_camera_aborts_upload_without_final_file(self):
        (self.tmp / 'data').mkdir()
        self.media(size=8 * 1024 * 1024)
        b = self.make()
        self.settle(b)
        calls = {'n': 0}

        def idle():
            calls['n'] += 1
            return calls['n'] == 1          # busy as soon as upload starts
        b.idle = idle
        b._last_idle_check = -1e9
        nb.IDLE_CHECK_SECONDS = 0
        try:
            self.assertEqual(b.run_once(), 0)
        finally:
            nb.IDLE_CHECK_SECONDS = 5
        self.assertFalse(self.remote().exists())
        self.assertEqual(b.done, {})

    def test_does_nothing_while_recording(self):
        (self.tmp / 'data').mkdir()
        self.media()
        b = self.make()
        self.settle(b)
        self.idle = False
        self.assertEqual(b.run_once(), 0)
        self.assertEqual(DAV.log, [])

    def test_wrong_password_is_reported(self):
        (self.tmp / 'data').mkdir()
        self.media()
        b = self.make(password='wrong')
        self.settle(b)
        with self.assertRaises(PermissionError):
            b.run_once()

    def test_delete_after_upload(self):
        (self.tmp / 'data').mkdir()
        src = self.media()
        b = self.make(delete_after_upload=True)
        self.settle(b)
        b.run_once()
        self.assertTrue(self.remote().exists())
        self.assertFalse(src.exists())

    def test_sd_import_moves_config_off_card(self):
        data = self.tmp / 'data'
        data.mkdir()
        sd = self.card / 'nas-backup.json'
        sd.write_text(json.dumps({'url': 'https://nas.local/x6', 'username': 'a',
                                  'password': 'secret'}))
        cfg = nb.load_config(data, sd)
        self.assertFalse(sd.exists())
        self.assertEqual(cfg['password'], 'secret')
        self.assertEqual((data / 'config.json').stat().st_mode & 0o777, 0o600)

    def test_invalid_config_is_rejected_and_left_on_card(self):
        data = self.tmp / 'data'
        data.mkdir()
        sd = self.card / 'nas-backup.json'
        sd.write_text(json.dumps({'url': 'ftp://nas'}))
        with self.assertRaises(ValueError):
            nb.load_config(data, sd)
        self.assertTrue(sd.exists())


if __name__ == '__main__':
    unittest.main()
