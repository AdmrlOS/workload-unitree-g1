#!/usr/bin/env python3
"""TEST ONLY: assemble Admiral's driver inventory for a disposable loader test.

Never COPY this output into a workload image. This exercises real NVIDIA ELF
loading and GStreamer registration, not GPU execution or hardware attestation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--cache', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[1]
packages = json.loads((repo / 'tests/nvidia-driver-packages.json').read_text())
names = set(json.loads((repo / 'config/admiral-driver-libraries.json').read_text()))
args.cache.mkdir(parents=True, exist_ok=True)
args.output.mkdir(parents=True, exist_ok=True)
for package in packages:
    deb = args.cache / (package['name'] + '.deb')
    if not deb.exists():
        with urllib.request.urlopen(package['url'], timeout=120) as src, deb.open('wb') as dest:
            shutil.copyfileobj(src, dest)
    if hashlib.sha256(deb.read_bytes()).hexdigest() != package['sha256']:
        raise ValueError(f'package checksum failed: {deb}')
    with tempfile.TemporaryDirectory() as temp:
        subprocess.run(['dpkg-deb', '-x', str(deb), temp], check=True)
        for path in Path(temp).rglob('*'):
            if path.name in names and path.is_file():
                shutil.copyfile(path.resolve(), args.output / path.name)
missing = names - {p.name for p in args.output.iterdir()}
if missing:
    raise ValueError(f'test driver assembly incomplete: {missing}')
print(f'prepared {len(names)} real R39.2.1 driver names for test-only mounting')
