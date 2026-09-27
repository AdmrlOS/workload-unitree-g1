#!/usr/bin/env python3
"""Workload-owned D435i discovery, /dev/rlsen0 alias, warmup and hotplug.

Implements the vendor udev rule without a udev database/daemon. The BSP
supplies USB/UVC and real device nodes; this helper never creates device nodes,
changes host permissions, resets USB, or writes the immutable host rootfs.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import threading
import time

SYS = Path('/sys/class/video4linux')
DEV = Path('/dev')
STATE = Path('/run/unitree-g1/camera.json')
STOP = threading.Event()


def read(path):
    try:
        return path.read_text().strip()
    except (OSError, UnicodeError):
        return ''


def capture_device(path):
    """Use device_caps, not aggregate capabilities (which include metadata)."""
    data = bytearray(104)  # struct v4l2_capability, Linux UAPI
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, 0x80685600, data, True)  # VIDIOC_QUERYCAP, arm64
    finally:
        os.close(fd)
    capabilities, device_caps = struct.unpack_from('=II', data, 84)
    caps = device_caps if capabilities & 0x80000000 else capabilities
    return bool(caps & 0x1) and bool(caps & 0x04000000)  # capture + streaming


def discover(sys_root=SYS, dev_root=DEV, serial='', probe=capture_device):
    matches = []
    for node in sorted(sys_root.glob('video*')):
        try:
            interface = next((p for p in node.resolve().parents
                              if (p / 'bInterfaceNumber').exists()), None)
            if interface is None or read(interface / 'bInterfaceNumber') != '03':
                continue
            usb = next((p for p in interface.parents if (p / 'idVendor').exists()), None)
            if usb is None or (read(usb / 'idVendor'), read(usb / 'idProduct')) != ('8086', '0b3a'):
                continue
            if serial and read(usb / 'serial') != serial:
                continue
            device = dev_root / node.name
            if not probe(device):
                continue
            info = device.stat()
            # devnum catches re-enumeration even when videoN is reused quickly.
            identity = (str(node.resolve()), read(usb / 'devnum'), info.st_ino, info.st_rdev)
            matches.append((device, identity))
        except (OSError, StopIteration):
            continue  # sysfs and /dev can disappear during enumeration
    if len(matches) > 1:
        raise RuntimeError('multiple D435i RGB cameras; set UNITREE_CAMERA_SERIAL')
    return matches[0] if matches else None


def reconcile_alias(candidate, alias=DEV / 'rlsen0'):
    if alias.exists() and not alias.is_symlink():
        raise RuntimeError(f'refusing to overwrite non-symlink {alias}')
    if candidate is None:
        # Only remove the video alias we manage, never an unrelated path.
        if alias.is_symlink() and Path(os.readlink(alias)).name.startswith('video'):
            alias.unlink(missing_ok=True)
        return
    target = candidate[0].name  # relative to /dev so it works in both namespaces
    if alias.is_symlink() and os.readlink(alias) == target:
        return
    temporary = alias.with_name(f'.rlsen0-{os.getpid()}')
    try:
        temporary.symlink_to(target)
        temporary.replace(alias)
    finally:
        temporary.unlink(missing_ok=True)


def status(state, detail):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    data = {'state': state, 'detail': detail, 'updated': time.time(), 'pid': os.getpid()}
    temp = STATE.with_suffix('.tmp')
    temp.write_text(json.dumps(data) + '\n')
    temp.replace(STATE)
    print(f'camera: {state}: {detail}', flush=True)


def terminate(child):
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        except ProcessLookupError:
            child.wait()


def run_child(command, candidate, serial, timeout=None):
    child = subprocess.Popen(command, start_new_session=True)
    deadline = time.monotonic() + timeout if timeout else None
    try:
        while not STOP.wait(0.5):
            if child.poll() is not None:
                return child.returncode == 0
            if deadline and time.monotonic() >= deadline:
                return False
            if discover(serial=serial) != candidate:
                return False
        return False
    finally:
        terminate(child)


def run(serial):
    previous = None
    try:
        while not STOP.is_set():
            try:
                camera = discover(serial=serial)
                reconcile_alias(camera)
                if camera is None:
                    message = 'waiting for USB 8086:0b3a interface 03 RGB capture'
                    if previous != message:
                        status('waiting', message)
                        previous = message
                    STOP.wait(2)
                    continue
                status('warming', str(camera[0]))
                previous = None
                # Match the actual vendor format rather than warming an arbitrary
                # negotiated mode. A failed warmup never launches a stuck pipeline.
                command = ['gst-launch-1.0', '-q', 'v4l2src', 'device=/dev/rlsen0',
                           'num-buffers=45', '!',
                           'video/x-raw,format=YUY2,width=1920,height=1080,framerate=15/1',
                           '!', 'fakesink', 'sync=false']
                if not run_child(command, camera, serial, timeout=12):
                    status('retrying', 'warmup did not deliver 45 frames; retry in 3s')
                    STOP.wait(3)
                    continue
                status('running', f'vendor video hub on {camera[0]}; warmup passed')
                run_child(['stdbuf', '-oL', '/unitree/module/video_hub_pc4/videohub_pc4'],
                          camera, serial)
                status('retrying', 'video hub exited or USB identity changed')
            except (OSError, RuntimeError) as exc:
                if previous != str(exc):
                    status('error', str(exc))
                    previous = str(exc)
            STOP.wait(3)
    finally:
        status('stopped', 'camera supervisor stopped')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['discover', 'init', 'run'])
    args = parser.parse_args()
    serial = os.environ.get('UNITREE_CAMERA_SERIAL', '')
    if args.command == 'run':
        signal.signal(signal.SIGTERM, lambda *_: STOP.set())
        signal.signal(signal.SIGINT, lambda *_: STOP.set())
        run(serial)
    else:
        camera = discover(serial=serial)
        if args.command == 'init':
            reconcile_alias(camera)
        if camera is None:
            raise SystemExit('no matching D435i RGB capture device')
        print(camera[0])


if __name__ == '__main__':
    main()
