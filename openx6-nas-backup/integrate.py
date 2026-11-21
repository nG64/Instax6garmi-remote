#!/usr/bin/env python3
"""Add the x6-nas-backup component to an OpenX6 checkout (fork).

    python3 -B integrate.py /path/to/OpenX6

Copies the daemon and its systemd unit into components/assets/ and merges
profile-fragment.json into components/profile.json. Idempotent.

OpenX6 signs components/profile.json (release/profile.sig + preview.json pins),
so after running this the fork must be re-signed with your own key, see README.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = {
    HERE / 'src' / 'x6-nas-backup.py': 'x6-nas-backup.py',
    HERE / 'assets' / 'x6-nas-backup.service': 'x6-nas-backup.service',
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(target):
    comp = Path(target) / 'components'
    profile_path = comp / 'profile.json'
    profile = json.loads(profile_path.read_text())
    frag = json.loads((HERE / 'profile-fragment.json').read_text())

    for src, name in FILES.items():
        shutil.copyfile(src, comp / 'assets' / name)
    for dest, action in frag['actions'].items():
        got = sha(comp / action['asset'])
        if got != action['asset_sha256']:
            sys.exit('digest mismatch for %s: regenerate profile-fragment.json' % action['asset'])
        profile['actions'][dest] = action
    profile['links'].update(frag['links'])

    profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + '\n')
    print('merged into', profile_path)
    print('new profile sha256:', sha(profile_path))
    print('next: re-sign the profile with your own key (see README)')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
