#!/usr/bin/env python3
"""Inspect or extract Unitree UTPK/TEA module packages without a robot.

Format/key derivation: https://github.com/Bin4ry/UniTEABag (independently
verified against the UPKs used by legion1581/unitree-jetpack). MD5 in the
header is an integrity check, not a cryptographic signature.
"""

import argparse
import hashlib
import io
import json
import pathlib
import struct
import sys
import tarfile

MASK = 0xFFFFFFFF
DELTA = 0x9E3779B9


def keys(seed):
    def permute(value):
        return (0x7A + (value & 0x11) - (value & 0xEE)) & 0xFF

    state = permute(seed & 0xFF)
    current = [state]
    for i in range(1, 16):
        state = (permute(state) + i) & 0xFF
        current.append(state)
    first = (seed + 0x6E35BA0C) & MASK
    key1 = bytes(((first ^ ((i - 0x65748392) & MASK)) & 0xFF) for i in range(16))
    second = (seed ^ 0x9A8B7C6E) & MASK
    key2 = bytes(((i + second + 0x6E35BA0C) & 0xFF) for i in range(16))
    return bytes(current), key2, key1


def decrypt(data, key):
    k0, k1, k2, k3 = struct.unpack('<4I', key)
    output = bytearray(len(data))
    for offset in range(0, len(data), 8):
        v0, v1 = struct.unpack_from('<2I', data, offset)
        total = (DELTA * 16) & MASK
        for _ in range(16):
            v1 = (v1 - (((v0 << 4) + k2) ^ (v0 + total) ^ ((v0 >> 5) + k3))) & MASK
            v0 = (v0 - (((v1 << 4) + k0) ^ (v1 + total) ^ ((v1 >> 5) + k1))) & MASK
            total = (total - DELTA) & MASK
        struct.pack_into('<2I', output, offset, v0, v1)
    return output


def read_package(path, expected_sha256=None):
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise ValueError(f'{path}: SHA256 mismatch: {digest}')
    if len(data) < 116 or data[:4] != b'UTPK' or data[24] != 3 or data[112:116] != b'TEA\0':
        raise ValueError(f'{path}: not a UTPK/TEA package')
    (size,) = struct.unpack_from('<Q', data, 16)
    if size != len(data) - 112 or (size - 4) % 8:
        raise ValueError(f'{path}: invalid payload size')
    if hashlib.md5(data[112:]).digest() != data[32:48]:
        raise ValueError(f'{path}: invalid payload MD5')
    name = data[48:112].split(b'\0', 1)[0].decode('ascii')
    (seed,) = struct.unpack_from('<I', data, 28)
    for key in keys(seed):
        # Check the tar signature before decrypting the whole file.
        probe = decrypt(data[116:116 + 512], key)
        if probe[257:262] == b'ustar':
            return name, digest, decrypt(data[116:], key)
    raise ValueError(f'{path}: neither known TEA key produced a tar archive')


def members(archive):
    for member in archive.getmembers():
        parts = pathlib.PurePosixPath(member.name).parts
        if not parts or parts[0] == '/' or '..' in parts or not (member.isdir() or member.isfile()):
            raise ValueError(f'unsafe UPK member: {member.name!r}')
        yield member


def install(archive, files, name, root):
    by_name = {member.name: member for member in files if member.isfile()}
    metadata_path = f'{name}/module.json'
    if metadata_path not in by_name:
        raise ValueError(f'{name}: missing module.json')
    with archive.extractfile(by_name[metadata_path]) as stream:
        metadata = json.load(stream)
    module = metadata['Name']
    if name != f"{module}_{metadata['Version']}":
        raise ValueError(f'{name}: module.json name/version mismatch')
    prefix = f'{name}/module/{module}/file/'
    payload = {'/' + path[len(prefix):]: member for path, member in by_name.items()
               if path.startswith(prefix)}
    declared = metadata['FileList']
    if set(payload) != set(declared):
        raise ValueError(f'{name}: payload file paths disagree with module.json')
    for path, member in payload.items():
        if member.size == declared[path]:
            continue
        # The pinned community Noble 1.0.0.6 UPK modified chrony_setup.sh
        # after its module.json was generated (1998 vs 1629 bytes). This
        # exception is bound to the whole-archive SHA256 checked by the caller.
        if (name, path, declared[path], member.size) != (
            'unitree_patch_pc4_1.0.0.6',
            '/unitree/var/data/chrony/chrony_setup.sh', 1629, 1998
        ):
            raise ValueError(f'{name}: {path} size differs from module.json')
        print(f'{name}: known upstream FileList discrepancy: {path}', flush=True)

    # The OTA install commands in module.json invoke systemctl and udevadm.
    # In an Admiral image we only stage their declared file payload. Services
    # are started by our entrypoint and kernel/udev belong to Admiral OS.
    for path, member in payload.items():
        dest = root.joinpath(*pathlib.PurePosixPath(path).parts[1:])
        dest.parent.mkdir(parents=True, exist_ok=True)
        with archive.extractfile(member) as src, dest.open('wb') as out:
            while chunk := src.read(1024 * 1024):
                out.write(chunk)
        dest.chmod(member.mode & 0o777)
    module_json = root / 'unitree/robot/pkg/module' / module / 'module.json'
    module_json.parent.mkdir(parents=True, exist_ok=True)
    module_json.write_text(json.dumps(metadata, indent=2) + '\n')
    version_json = root / 'unitree/robot/pkg/version/version.json'
    versions = json.loads(version_json.read_text())
    versions['Module'][module] = metadata['Version']
    version_json.write_text(json.dumps(versions, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=pathlib.Path)
    parser.add_argument('--sha256', help='expected SHA256 of the entire .upk')
    parser.add_argument('--name', help='expected package name from the UTPK header')
    parser.add_argument('--output', type=pathlib.Path, help='extract into this directory (default: list only)')
    parser.add_argument('--install-root', type=pathlib.Path, help='apply module FileList to a staged rootfs')
    args = parser.parse_args()
    if args.output and args.install_root:
        parser.error('choose --output or --install-root')

    name, digest, payload = read_package(args.package, args.sha256)
    if args.name and name != args.name:
        raise ValueError(f'package name {name!r} != {args.name!r}')
    print(f'{args.package}: {name}, sha256={digest}', flush=True)
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:') as archive:
        files = list(members(archive))
        if not args.install_root:
            for member in files:
                print(f'{member.size:>10}  {member.name}')
        if args.install_root:
            install(archive, files, name, args.install_root)
        if args.output:
            # Validate the complete archive before writing anything to disk.
            args.output.mkdir(parents=True, exist_ok=True)
            for member in files:
                target = args.output.joinpath(*pathlib.PurePosixPath(member.name).parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as src, target.open('wb') as dest:
                        while chunk := src.read(1024 * 1024):
                            dest.write(chunk)
                    target.chmod(member.mode & 0o777)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, tarfile.TarError) as exc:
        sys.exit(str(exc))
