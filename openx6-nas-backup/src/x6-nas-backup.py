#!/usr/bin/python3
"""OpenX6 NAS backup: mirror the camera's recordings to a WebDAV share on the
owner's own network instead of the Insta360 cloud.

Runs as a systemd service on the X6 (Python 3.10 standard library only).

* Configuration lives in /data/x6-nas-backup/config.json (mode 0600).
  For first setup, place `nas-backup.json` in the SD card root: it is imported
  into /data and then removed from the card because it contains a password.
* Only files that have stopped changing are uploaded, and only while the camera
  is neither recording nor capturing. A recording start aborts the upload.
* Each file is uploaded as `<name>.partial`, its size is verified on the NAS and
  it is then renamed (WebDAV MOVE). A half-written file never appears under its
  final name.
* Uploaded files are remembered by (size, mtime) in state.json; nothing is ever
  deleted on the camera unless `delete_after_upload` is explicitly enabled.
"""
import argparse
import base64
import hashlib
import http.client
import json
import os
import signal
import ssl
import subprocess
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

VERSION = '0.1.0'
DATA = Path('/data/x6-nas-backup')
RUN = Path('/run/x6-nas-backup')
SD_IMPORT = Path('/mnt/sdcard/nas-backup.json')
STORAGES = {
    'internal': '/ins/media_rw/emulated',
    'sd': '/mnt/sdcard',
    'ssd': '/mnt/quickreader',
}
DEFAULTS = {
    'enabled': True,
    'url': None,                 # e.g. https://nas.local:5006/x6-backup
    'username': '',
    'password': '',
    'verify_tls': True,
    'ca_file': None,             # PEM of a self-signed NAS certificate
    'storages': ['sd', 'internal', 'ssd'],
    'folders': ['DCIM'],         # top-level folders mirrored on each storage
    'interval_seconds': 120,
    'settle_seconds': 60,        # file must be untouched this long
    'timeout_seconds': 30,
    'delete_after_upload': False,
    'device_name': None,         # NAS subfolder; default: camera serial
}
CHUNK = 1 << 20
IDLE_CHECK_SECONDS = 5


class Busy(Exception):
    """The camera started recording/capturing; stop uploading for now."""


class Stop(Exception):
    pass


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def write_private(path: Path, data: bytes, mode=0o600):
    tmp = path.with_name('.' + path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


# ---------------------------------------------------------------- config ---

def validate(cfg: dict) -> dict:
    out = dict(DEFAULTS)
    unknown = set(cfg) - set(DEFAULTS)
    if unknown:
        raise ValueError('unknown config keys: ' + ', '.join(sorted(unknown)))
    out.update(cfg)
    u = urllib.parse.urlsplit(out['url'] or '')
    if u.scheme not in ('http', 'https') or not u.hostname:
        raise ValueError('url must be http(s)://host[:port]/path')
    if u.scheme == 'http' and out['password']:
        log('warning: password is sent unencrypted over http')
    bad = set(out['storages']) - set(STORAGES)
    if bad:
        raise ValueError('unknown storages: ' + ', '.join(sorted(bad)))
    if out['device_name'] is not None and (not out['device_name'].isalnum()):
        raise ValueError('device_name must be letters/digits only')
    for f in out['folders']:
        if not f or '/' in f or f.startswith('.'):
            raise ValueError('folders must be plain top-level names')
    for k in ('interval_seconds', 'settle_seconds', 'timeout_seconds'):
        if not isinstance(out[k], int) or out[k] < 1:
            raise ValueError(k + ' must be a positive integer')
    return out


def load_config(data_dir: Path, sd_import: Path) -> dict:
    cfg_path = data_dir / 'config.json'
    if sd_import.is_file() and not sd_import.is_symlink():
        raw = sd_import.read_bytes()
        validate(json.loads(raw))          # refuse to import a broken file
        write_private(cfg_path, raw)
        sd_import.unlink()
        log('imported configuration from', sd_import)
    return validate(json.loads(cfg_path.read_bytes()))


# ---------------------------------------------------------- camera state ---

def camera_idle() -> bool:
    """True only when the stock media service reports Record/Capture idle."""
    try:
        p = subprocess.run(
            ['/usr/bin/ins_bll_cli', '{"cmd":"share_state","action":"get","type":"media"}'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=8, check=True)
        v = json.loads(p.stdout)
    except Exception:
        return False                       # unknown state: stay out of the way
    d = v.get('data', {})
    return (v.get('ret') == 'ok'
            and d.get('record', {}).get('record_status') == 'RecordIdle'
            and d.get('capture', {}).get('capture_status') == 'CaptureIdle')


def camera_serial() -> str:
    for p in ('/ins/etc/serial', '/proc/device-tree/serial-number'):
        try:
            s = Path(p).read_text().strip('\x00\n ')
            if s:
                return ''.join(c for c in s if c.isalnum())
        except OSError:
            pass
    return 'X6'


# ---------------------------------------------------------------- webdav ---

class WebDAV:
    def __init__(self, url, username='', password='', verify_tls=True,
                 ca_file=None, timeout=30):
        u = urllib.parse.urlsplit(url)
        self.https = u.scheme == 'https'
        self.host, self.port = u.hostname, u.port
        self.base = u.path.rstrip('/')
        self.timeout = timeout
        self.auth = None
        if username:
            tok = base64.b64encode(f'{username}:{password}'.encode()).decode()
            self.auth = 'Basic ' + tok
        self.ctx = None
        if self.https:
            self.ctx = ssl.create_default_context(cafile=ca_file)
            if not verify_tls:
                self.ctx.check_hostname = False
                self.ctx.verify_mode = ssl.CERT_NONE

    def _conn(self):
        if self.https:
            return http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout,
                                               context=self.ctx)
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def href(self, rel):
        return self.base + '/' + urllib.parse.quote(rel.strip('/'))

    def _headers(self, extra=None):
        h = {'User-Agent': 'x6-nas-backup/' + VERSION}
        if self.auth:
            h['Authorization'] = self.auth
        h.update(extra or {})
        return h

    def request(self, method, rel, body=None, headers=None):
        c = self._conn()
        try:
            c.request(method, self.href(rel), body=body, headers=self._headers(headers))
            r = c.getresponse()
            return r.status, r.read()
        finally:
            c.close()

    def reachable(self) -> bool:
        try:
            st, _ = self.request('PROPFIND', '', headers={'Depth': '0'})
        except OSError:
            return False
        if st in (401, 403):
            raise PermissionError('NAS rejected the credentials (HTTP %d)' % st)
        return st in (207, 200)

    def mkdirs(self, rel_dir, known: set):
        parts = [p for p in rel_dir.split('/') if p]
        for i in range(1, len(parts) + 1):
            d = '/'.join(parts[:i])
            if d in known:
                continue
            st, _ = self.request('MKCOL', d + '/')
            if st not in (201, 405, 301):    # 405: already exists
                raise OSError('MKCOL %s failed: HTTP %d' % (d, st))
            known.add(d)

    def size(self, rel):
        st, body = self.request('PROPFIND', rel, headers={'Depth': '0'})
        if st == 404:
            return None
        if st != 207:
            raise OSError('PROPFIND %s failed: HTTP %d' % (rel, st))
        for el in ET.fromstring(body).iter('{DAV:}getcontentlength'):
            return int(el.text)
        return None

    def put_file(self, rel, path: Path, size, check_abort):
        c = self._conn()
        try:
            c.putrequest('PUT', self.href(rel), skip_accept_encoding=True)
            for k, v in self._headers({'Content-Length': str(size),
                                       'Content-Type': 'application/octet-stream'}).items():
                c.putheader(k, v)
            c.endheaders()
            sent = 0
            with path.open('rb') as f:
                while sent < size:
                    buf = f.read(min(CHUNK, size - sent))
                    if not buf:
                        raise OSError('file shrank during upload')
                    c.send(buf)
                    sent += len(buf)
                    check_abort()
            r = c.getresponse()
            r.read()
            if r.status not in (200, 201, 204):
                raise OSError('PUT %s failed: HTTP %d' % (rel, r.status))
        finally:
            c.close()

    def move(self, src, dst):
        dest = ('https' if self.https else 'http') + '://' + self.host
        if self.port:
            dest += ':%d' % self.port
        dest += self.href(dst)
        st, _ = self.request('MOVE', src, headers={'Destination': dest, 'Overwrite': 'T'})
        if st not in (201, 204):
            raise OSError('MOVE %s failed: HTTP %d' % (src, st))

    def delete(self, rel):
        self.request('DELETE', rel)


# ---------------------------------------------------------------- backup ---

class Backup:
    def __init__(self, cfg, data_dir=DATA, run_dir=RUN, roots=None,
                 idle=camera_idle, serial=None, clock=time.time):
        self.cfg = cfg
        self.data_dir, self.run_dir = Path(data_dir), Path(run_dir)
        self.roots = roots or STORAGES
        self.idle = idle
        self.clock = clock
        self.serial = serial or cfg['device_name'] or camera_serial()
        self.dav = WebDAV(cfg['url'], cfg['username'], cfg['password'], cfg['verify_tls'],
                          cfg['ca_file'], cfg['timeout_seconds'])
        self.state_path = self.data_dir / 'state.json'
        try:
            self.done = json.loads(self.state_path.read_bytes())
        except (OSError, ValueError):
            self.done = {}
        self.seen = {}            # key -> (size, mtime_ns) from the previous scan
        self.dirs = set()
        self.stopping = False
        self._last_idle_check = 0.0
        self.status = {'version': VERSION, 'state': 'starting'}

    # --- bookkeeping
    def save_state(self):
        write_private(self.state_path, json.dumps(self.done, sort_keys=True).encode())

    def publish(self, **kw):
        self.status.update(kw, updated=int(self.clock()))
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            write_private(self.run_dir / 'status.json',
                          json.dumps(self.status).encode(), 0o644)
        except OSError:
            pass

    # --- discovery
    def scan(self):
        """Yield (key, path, size, mtime_ns) for regular files below the folders."""
        for storage in self.cfg['storages']:
            root = Path(self.roots[storage])
            for folder in self.cfg['folders']:
                top = root / folder
                if not top.is_dir() or top.is_symlink():
                    continue
                for dirpath, dirnames, files in os.walk(top, followlinks=False):
                    dirnames[:] = sorted(d for d in dirnames if not d.startswith('.'))
                    for name in sorted(files):
                        if name.startswith('.'):
                            continue
                        p = Path(dirpath, name)
                        try:
                            st = p.lstat()
                        except OSError:
                            continue
                        if not (st.st_mode & 0o170000 == 0o100000):
                            continue
                        key = storage + '/' + p.relative_to(root).as_posix()
                        yield key, p, st.st_size, st.st_mtime_ns

    def candidates(self):
        now_ns = int(self.clock() * 1e9)
        settle_ns = self.cfg['settle_seconds'] * 1_000_000_000
        current, ready = {}, []
        for key, p, size, mtime in self.scan():
            sig = [size, mtime]
            current[key] = sig
            if self.done.get(key) == sig:
                continue
            if self.seen.get(key) == sig and now_ns - mtime >= settle_ns and size > 0:
                ready.append((key, p, size, mtime))
        self.seen = current
        return ready

    # --- upload
    def check_abort(self):
        if self.stopping:
            raise Stop()
        now = time.monotonic()
        if now - self._last_idle_check >= IDLE_CHECK_SECONDS:
            self._last_idle_check = now
            if not self.idle():
                raise Busy()

    def upload(self, key, path, size, mtime):
        remote = self.serial + '/' + key
        parent = remote.rsplit('/', 1)[0]
        self.dav.mkdirs(parent, self.dirs)
        if self.dav.size(remote) == size:          # already there (e.g. lost state)
            log('already on NAS:', key)
        else:
            tmp = remote + '.partial'
            self.dav.put_file(tmp, path, size, self.check_abort)
            got = self.dav.size(tmp)
            if got != size:
                self.dav.delete(tmp)
                raise OSError('size mismatch for %s: %s != %d' % (key, got, size))
            st = path.stat()
            if [st.st_size, st.st_mtime_ns] != [size, mtime]:
                self.dav.delete(tmp)
                raise OSError('file changed during upload: ' + key)
            self.dav.move(tmp, remote)
        self.done[key] = [size, mtime]
        self.save_state()
        if self.cfg['delete_after_upload']:
            path.unlink()

    def run_once(self):
        """One sync pass. Returns number of uploaded files."""
        if not self.cfg['enabled']:
            self.publish(state='disabled')
            return 0
        if not self.idle():
            self.publish(state='camera_busy')
            return 0
        ready = self.candidates()
        if not ready:
            self.publish(state='idle', pending=0)
            return 0
        if not self.dav.reachable():
            self.publish(state='nas_unreachable', pending=len(ready))
            return 0
        n = 0
        total = len(ready)
        for key, path, size, mtime in ready:
            self.publish(state='uploading', file=key, index=n + 1, pending=total - n)
            try:
                self.upload(key, path, size, mtime)
                n += 1
                log('uploaded', key, size)
            except Busy:
                self.publish(state='camera_busy')
                break
            except (OSError, ssl.SSLError, http.client.HTTPException) as e:
                log('upload failed:', key, e)
                self.publish(state='error', error=str(e)[:200])
                break
        else:
            self.publish(state='idle', pending=0, last_success=int(self.clock()))
        return n

    def forever(self):
        while not self.stopping:
            try:
                self.run_once()
            except Stop:
                break
            except PermissionError as e:
                log(e)
                self.publish(state='auth_failed', error=str(e))
            except Exception as e:                 # never crash-loop the camera
                log('pass failed:', repr(e))
                self.publish(state='error', error=repr(e)[:200])
            deadline = time.monotonic() + self.cfg['interval_seconds']
            while not self.stopping and time.monotonic() < deadline:
                time.sleep(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--once', action='store_true', help='run a single pass and exit')
    ap.add_argument('--check', action='store_true', help='validate config and test the NAS')
    args = ap.parse_args(argv)

    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        cfg = load_config(DATA, SD_IMPORT)
    except FileNotFoundError:
        log('no configuration yet; put nas-backup.json in the SD card root')
        while not SD_IMPORT.exists():
            time.sleep(30)
        cfg = load_config(DATA, SD_IMPORT)
    b = Backup(cfg)
    if args.check:
        ok = b.dav.reachable()
        print(json.dumps({'nas_reachable': ok, 'camera_idle': camera_idle(),
                          'serial': b.serial}))
        return 0 if ok else 1

    def stop(*_):
        b.stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if args.once:
        b.run_once()     # first pass only records sizes; settling needs a second
        time.sleep(1)
        b.run_once()
        return 0
    b.forever()
    return 0


if __name__ == '__main__':
    sys.exit(main())
