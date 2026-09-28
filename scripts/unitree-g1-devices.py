#!/usr/bin/env python3
"""Apply the R39.2.1 NVENC userspace device rule after its driver has bound."""
import os
from pathlib import Path
import stat
import sys


NVENC_DRIVER = Path('/sys/bus/platform/drivers/tegra-nvenc/154c0000.nvenc')
NVENC_DEVICE = Path('/dev/v4l2-nvenc')


def prepare_encoder(driver=NVENC_DRIVER, device=NVENC_DEVICE):
    # This is NVIDIA's upstream-Tegra dispatch endpoint, not the hardware
    # encoder's major/minor. libv4l2_nvvideocodec.so handles its ioctls in
    # userspace and talks to the bound kernel driver. See the pinned
    # nvidia-l4t-init 99-tegra-devices.rules retained in /opt/unitree-g1.
    if not driver.is_symlink() or not driver.is_dir():
        raise RuntimeError(f'NVENC driver is not bound at {driver}; cannot initialize {device}')
    created = False
    try:
        os.mknod(device, stat.S_IFCHR | 0o660, os.makedev(1, 3))
        created = True
    except FileExistsError:
        pass
    info = device.lstat()
    if not stat.S_ISCHR(info.st_mode) or info.st_rdev != os.makedev(1, 3):
        raise RuntimeError(f'{device} exists but is not the NVIDIA R39 dispatch node; refusing to overwrite it')
    if created:
        os.chown(device, 0, 28)
        os.chmod(device, 0o660)
    print(f'NVENC: {device} ready; tegra-nvenc is bound', flush=True)


if __name__ == '__main__':
    try:
        prepare_encoder()
    except (OSError, RuntimeError) as error:
        print(f'WARNING: NVENC device initialization failed: {error}', file=sys.stderr, flush=True)
        sys.exit(1)
