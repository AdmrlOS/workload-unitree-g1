#!/usr/bin/env python3
"""Assemble pinned multimedia userspace; never install NVIDIA host packages.

Only library payloads, licenses and a device-rule reference are copied. No maintainer scripts, kernel,
firmware, systemd services, graphics driver or libcuda enters the image.
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import tempfile
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=pathlib.Path, required=True)
    parser.add_argument('--assets', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text())
    args.assets.mkdir(parents=True, exist_ok=True)
    for package in lock['packages']:
        name = package['name']
        if name not in {'nvidia-l4t-gstreamer', 'nvidia-l4t-multimedia',
                        'nvidia-l4t-multimedia-utils', 'nvidia-l4t-nvsci',
                        'nvidia-l4t-adaruntime', 'nvidia-l4t-core',
                        'nvidia-l4t-multimedia-nvgpu', 'nvidia-l4t-init',
                        'libnvjpeg-13-2', 'cuda-cudart-13-2'}:
            raise ValueError(f'not a permitted application package: {name}')
        deb = args.assets / f'{name}.deb'
        if not deb.exists():
            with urllib.request.urlopen(package['url'], timeout=120) as src, deb.open('wb') as dst:
                shutil.copyfileobj(src, dst)
        if hashlib.sha256(deb.read_bytes()).hexdigest() != package['sha256']:
            raise ValueError(f'SHA256 mismatch: {deb}')
        metadata = subprocess.check_output(
            ['dpkg-deb', '-f', str(deb), 'Package', 'Version', 'Architecture'], text=True)
        expected = f"Package: {name}\nVersion: {package['version']}\nArchitecture: arm64\n"
        if metadata != expected:
            raise ValueError(f'unexpected package metadata: {metadata}')
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            subprocess.run(['dpkg-deb', '-x', str(deb), temp], check=True)
            lib = pathlib.Path('usr/lib/aarch64-linux-gnu')
            if name in {'libnvjpeg-13-2', 'cuda-cudart-13-2'}:
                # R39 JPEG dlopens nvJPEG 13; copy only these runtime .so files
                # into the standard search path (no toolkit, dev libs or stubs).
                dest = args.output / lib
                dest.mkdir(parents=True, exist_ok=True)
                runtimes = list((root / 'usr/local/cuda-13.2/targets/sbsa-linux/lib').glob('*.so*'))
                if not runtimes:
                    raise ValueError(f'{name}: runtime libraries missing')
                for src in runtimes:
                    shutil.copy2(src, dest / src.name, follow_symlinks=False)
                paths = [pathlib.Path('usr/share/doc') / name]
            elif name == 'nvidia-l4t-gstreamer':
                # The G1 uses USB/UVC. Do not install unrelated SIPL/Argus plugins.
                paths = [lib / 'gstreamer-1.0' / f'libgst{p}.so'
                         for p in ('nvvidconv', 'nvvideo4linux2', 'nvjpeg')]
                paths += [lib / 'libgstnvexifmeta.so', lib / 'nvidia']
            elif name == 'nvidia-l4t-core':
                # Additional multimedia backends absent from Admiral's compute payload.
                paths = [lib / 'nvidia' / n for n in ('libnvrm_stream.so', 'libnvddk_vic.so', 'libnvvic.so', 'libnvddk_2d_v2.so', 'libnvcolorutil.so')]
            elif name == 'nvidia-l4t-init':
                # Audit only: do not install the host's services or run its
                # broad udev rules. Our device helper applies the NVENC rule.
                rule = args.output / 'opt/unitree-g1/vendor-tegra-devices.rules'
                rule.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / 'etc/udev/rules.d/99-tegra-devices.rules', rule)
                paths = []
            else:
                paths = [lib]
            if not name.startswith(('libnvjpeg-', 'cuda-cudart-')):
                paths += [pathlib.Path('usr/share/doc') / name]
            if name == 'nvidia-l4t-nvsci':
                paths += [pathlib.Path('etc/nvsciipc.cfg')]
            for relative in paths:
                src, dst = root / relative, args.output / relative
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst, follow_symlinks=False)
        print(f'verified and staged {name} {package["version"]}', flush=True)
    info = args.output / 'opt/unitree-g1'
    info.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.lock, info / 'nvidia-packages.json')
    conf = args.output / 'etc/ld.so.conf.d/000-unitree-multimedia.conf'
    conf.parent.mkdir(parents=True, exist_ok=True)
    # NVIDIA's V4L2 dispatch wrapper must win over generic libv4l2 for NVENC.
    conf.write_text('/usr/lib/aarch64-linux-gnu/nvidia\n')


if __name__ == '__main__':
    main()
