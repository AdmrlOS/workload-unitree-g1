#!/usr/bin/env python3
"""Explicit image, video, platform and readiness diagnostics (no motion commands)."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys

LIB = Path('/usr/lib/aarch64-linux-gnu')
CONFIG = Path('/opt/unitree-g1/config')
PLUGINS = ('nvvidconv', 'nvv4l2h264enc', 'nvjpegenc')
DEVICE_TREE = Path('/sys/firmware/devicetree/base')


def board_info():
    values = {}
    for name in ('model', 'chosen/ids'):
        try:
            values[name] = (DEVICE_TREE / name).read_bytes().replace(b'\x00', b' ').decode(errors='replace').strip()
        except OSError:
            values[name] = 'unavailable'
    return values


def is_orin_nano(ids):
    # Same module IDs excluded by NVIDIA's R39.2.1 gst-nvvideo4linux2.
    # Do not infer the module from a shared Nano/NX carrier-board model name.
    return bool(re.search(r'3767[-:]000[345]', ids))


def video():
    board = board_info()
    print(f'Board: {board["model"]}; module IDs: {board["chosen/ids"]}', flush=True)
    if is_orin_nano(board['chosen/ids']):
        raise RuntimeError('Orin Nano has no NVENC hardware encoder. NVIDIA intentionally omits '
                           'nvv4l2h264enc on this module. Stock Unitree video requires Orin NX; '
                           'SSH/CUDA/application development can continue, but G1 video readiness cannot pass.')
    # A private cache avoids retaining a blacklist generated before injection.
    os.environ['GST_REGISTRY'] = '/run/unitree-g1/gstreamer-registry.bin'
    Path('/run/unitree-g1').mkdir(parents=True, exist_ok=True)
    for plugin in PLUGINS:
        try:
            execute(['gst-inspect-1.0', plugin])
        except RuntimeError as exc:
            raise RuntimeError(f'{exc}\nOn Orin Nano, nvv4l2h264enc is unavailable because it has '
                               'no NVENC engine. On Orin NX, inspect the NVIDIA plugin, driver '
                               'and BSP device access with unitree-g1-status inspect.') from exc
    if not Path('/dev/v4l2-nvenc').is_char_device():
        raise RuntimeError('/dev/v4l2-nvenc is missing; workload startup must initialize the '
                           'NVIDIA dispatch node after tegra-nvenc binds. Inspect the startup log.')
    codec = LIB / 'libv4l/plugins/nv/libv4l2_nvvideocodec.so'
    if not codec.is_file():
        raise RuntimeError(f'NVGPU codec dispatch plugin missing: {codec}')
    print('PASS: NVIDIA video elements, codec dispatch plugin and encoder node present (not an encode test)', flush=True)


def lan():
    addresses = json.loads(execute(['ip', '-j', '-4', 'addr', 'show']))
    robot = [iface['ifname'] for iface in addresses
             for address in iface.get('addr_info', [])
             if address.get('local') == '192.168.123.164' and address.get('prefixlen') == 24]
    if robot != ['eth0']:
        actual = ', '.join(robot) if robot else 'no interface'
        raise RuntimeError(f'robot LAN 192.168.123.164/24 is on {actual}; Unitree video hub '
                           'hardcodes eth0 for DDS and multicast. Workload startup should '
                           'rename the physical PC1 NIC; inspect the startup log for why it did not.')
    route = json.loads(execute(['ip', '-j', 'route', 'get', '192.168.123.161']))
    if not route or route[0].get('dev') != 'eth0' or route[0].get('prefsrc') != '192.168.123.164':
        raise RuntimeError('PC1 192.168.123.161 must route over eth0 from 192.168.123.164')
    print('PASS: robot LAN eth0 / 192.168.123.164 has the PC1 route (not a peer response test)', flush=True)


def execute(command):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, timeout=20)
    if result.returncode:
        raise RuntimeError(f'{command}: {result.stdout.strip()}')
    return result.stdout


def check_libraries(build=False):
    allowed = set(json.loads((CONFIG / 'admiral-driver-libraries.json').read_text())) if build else set()
    paths = [Path('/unitree/module/master_service/master_service'),
             Path('/unitree/module/video_hub_pc4/videohub_pc4')]
    paths += [LIB / 'gstreamer-1.0' / f'libgst{name}.so'
              for name in ('nvvidconv', 'nvvideo4linux2', 'nvjpeg')]
    paths += [LIB / 'libnvjpeg.so.13', LIB / 'libcudart.so.13']
    paths += [LIB / 'libv4l/plugins/nv/libv4l2_nvvideocodec.so',
              LIB / 'nvidia/libtegrav4l2.so']
    # NVIDIA opens several encoder/VIC/NvSci backends with dlopen. Checking
    # just the application's ldd output does not cover those dependencies.
    paths += [LIB / 'nvidia' / name for name in (
        'libnvv4l2.so', 'libnvvideo.so', 'libnvmmlite.so', 'libnvmmlite_video.so',
        'libnvmm.so', 'libnvmm_utils.so', 'libnvmm_jpeg.so',
        'libnvbufsurface.so', 'libnvbufsurface_nvsci.so', 'libnvbufsurftransform.so',
        'libnvmedia2d.so', 'libnvmedia_iep_sci.so', 'libnvmedia_ijpe_sci.so',
        'libnvscibuf.so', 'libnvscisync.so', 'libnvvic.so',
        'libnvddk_vic.so', 'libnvddk_2d_v2.so', 'libnvcolorutil.so')]
    for path in paths:
        if not path.is_file():
            raise RuntimeError(f'missing runtime file {path}')
        result = execute(['ldd', str(path)])
        missing = set(re.findall(r'^\s*(\S+) => not found$', result, re.MULTILINE)) - allowed
        if missing:
            raise RuntimeError(f'{path.name}: missing {sorted(missing)}')
    print('PASS: application, plugins and encoder backend ELF dependencies')


def image():
    if 'VERSION_ID="26.04"' not in Path('/etc/os-release').read_text():
        raise RuntimeError('expected Ubuntu 26.04')
    for name in ('/unitree/ota', '/unitree/var/data/ota_update',
                 '/unitree/sbin/ota_pipe_cli', '/etc/init.d/ota_pipe'):
        if Path(name).exists():
            raise RuntimeError(f'runtime updater must not ship: {name}')
    for base in ('/unitree/etc', '/unitree/var/etc'):
        if (Path(base) / 'ota_pipe').exists():
            raise RuntimeError(f'updater configuration remains in {base}')
        manager = Path(base) / 'master_service'
        for name in ('init', 'once'):
            hooks = json.loads((manager / name).read_text())
            if any(hook in hooks for hook in ('ota-pipe', 'ota-update')):
                raise RuntimeError(f'updater startup hook remains in {manager / name}')
        for name in ('cmd/ota-pipe', 'cmd/ota-update', 'service/ota_pipe'):
            if (manager / name).exists():
                raise RuntimeError(f'updater command remains in {manager / name}')
    print('PASS: runtime updater, pending updates and recovery hooks removed')
    drivers = set(json.loads((CONFIG / 'admiral-driver-libraries.json').read_text()))
    for root in (Path('/usr'), Path('/opt')):
        for path in root.rglob('*'):
            if path.name in drivers or path.name.startswith('libcuda.so') or path.name == 'stubs':
                raise RuntimeError(f'competing Admiral driver/stub in image: {path}')
    check_libraries(build=True)
    print('PASS: Ubuntu 26.04 image has no bundled Admiral driver libraries')


def platform():
    # Published docs use /run/admrl; the inspected init implementation uses
    # /run/admiral. Accept either manifest location, never infer from uname.
    manifests = [Path(f'/run/{name}/nvidia/manifest.json') for name in ('admrl', 'admiral')]
    manifest = next((p for p in manifests if p.is_file()), None)
    if manifest is None:
        raise RuntimeError('Admiral NVIDIA manifest missing (device isolation must be disabled)')
    data = json.loads(manifest.read_text())
    if data.get('l4t_version') != '39.2.1' or data.get('variant') != 'nvgpu':
        raise RuntimeError(f'expected L4T 39.2.1 NVGPU, got {data.get("l4t_version")} / {data.get("variant")}')
    lan()
    check_libraries()
    ctypes.CDLL('libcuda.so.1', mode=os.RTLD_NOW | os.RTLD_LOCAL)
    video()
    print('PASS: R39.2.1 driver loads, video plugins register, robot network configured')


def ready():
    platform()
    execute(['/etc/init.d/master_service', 'status'])
    camera = json.loads(Path('/run/unitree-g1/camera.json').read_text())
    os.kill(camera['pid'], 0)
    if camera['state'] != 'running':
        raise RuntimeError(f'camera {camera["state"]}: {camera["detail"]}')
    print('PASS: Unitree services and camera supervisor running after frame warmup')
    print('Still verify received JPEG/H.264 frames on the robot; process liveness is not stream health.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['image', 'video', 'lan', 'platform', 'ready'])
    args = parser.parse_args()
    try:
        {'image': image, 'video': video, 'lan': lan, 'platform': platform, 'ready': ready}[args.mode]()
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
