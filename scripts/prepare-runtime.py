#!/usr/bin/env python3
"""Remove the vendor runtime updater; Admiral deploys complete OCI images."""

import json
import pathlib
import shutil


def prepare(root):
    # Remove both live configuration and the vendor's recovery/default copy.
    # Leaving the pending-update script would still run code at manager startup.
    for base in ('unitree/etc', 'unitree/var/etc'):
        manager = root / base / 'master_service'
        for name in ('init', 'once'):
            path = manager / name
            data = json.loads(path.read_text())
            data = [item for item in data if item not in ('ota-pipe', 'ota-update')]
            path.write_text(json.dumps(data, indent=2) + '\n')
        for name in ('cmd/ota-pipe', 'cmd/ota-update', 'service/ota_pipe'):
            (manager / name).unlink(missing_ok=True)
        shutil.rmtree(root / base / 'ota_pipe', ignore_errors=True)
    for name in ('unitree/ota', 'unitree/var/data/ota_update'):
        shutil.rmtree(root / name)
    for name in ('etc/init.d/ota_pipe', 'unitree/sbin/ota_pipe_cli'):
        (root / name).unlink()


if __name__ == '__main__':
    prepare(pathlib.Path('/out'))
