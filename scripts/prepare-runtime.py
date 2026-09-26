#!/usr/bin/env python3
"""Replace master_service's systemd-only ota_pipe control with SysV control.

The vendor bootstrap assumes systemd, whereas Admiral runs the image as one
supervised OCI workload. Its init.d script works standalone on Ubuntu 24.04.
"""

import json
import pathlib


def main():
    config = pathlib.Path('/out/unitree/etc/master_service/service/ota_pipe')
    data = json.loads(config.read_text())
    for action in ('start', 'stop', 'status'):
        data[action.capitalize()]['Cmd'] = f'/etc/init.d/ota_pipe {action}'
    config.write_text(json.dumps(data, indent=2) + '\n')


if __name__ == '__main__':
    main()
