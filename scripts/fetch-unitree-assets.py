#!/usr/bin/env python3
"""Stage pinned PC4 artifacts without a robot (local UPKs or public mirror).

The base bootstrap is Unitree's official G1 FAQ download. Patch/video UPKs
are hosted by the community mirror linked from legion1581/unitree-jetpack.
All three downloads must match the hashes inspected for this image.
"""

import argparse
import hashlib
import json
import pathlib
import shutil
import urllib.parse
import urllib.request

MIRROR = 'https://disk.yandex.com/d/hDJ2DQMlDnoB2g'
API = 'https://cloud-api.yandex.net/v1/disk/public/resources/download'
ASSETS = (
    ('g1plus_pc4_unitree_install.zip', None,
     'https://oss-global-cdn.unitree.com/static/ad3297c5c9bb40368c3e0c9febefa375.zip',
     '9bb545ba6b90d4477843044c780d4646fb8a543467082ae910fc83d598962765'),
    ('unitree_patch_pc4.upk', '7.2-noble/unitree_patch_pc4_1.0.0.6-g1jp-noble.upk', None,
     '33c08e002fce0273b729bd24706614aa2221cef5481dc7d8a2ff6c0d344f605d'),
    ('video_hub_pc4.upk', 'common/video_hub_pc4_1.0.1.1-g1jp.upk', None,
     'de8b0815297bf5556b6fd7b2bed58d8a229f608b4227c1908bdebe48dbe23ea9'),
)


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest):
    request = urllib.request.Request(url, headers={'User-Agent': 'workload-unitree-g1/1.0'})
    with urllib.request.urlopen(request, timeout=120) as stream, dest.open('wb') as out:
        shutil.copyfileobj(stream, out)


def mirror_url(path):
    query = urllib.parse.urlencode({'public_key': MIRROR, 'path': '/' + path})
    request = urllib.request.Request(API + '?' + query, headers={'User-Agent': 'workload-unitree-g1/1.0'})
    with urllib.request.urlopen(request, timeout=30) as stream:
        return json.load(stream)['href']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=pathlib.Path,
                        help='use your local downloaded Yandex folder instead of the public mirror')
    parser.add_argument('--output', type=pathlib.Path, default=pathlib.Path('artifacts'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for filename, mirror_path, official_url, expected in ASSETS:
        dest = args.output / filename
        if dest.exists() and sha256(dest) == expected:
            print(f'verified existing {dest}')
            continue
        if args.source_dir and mirror_path:
            source = args.source_dir / mirror_path
            if not source.is_file():
                parser.error(f'missing {source}')
            shutil.copyfile(source, dest)
        else:
            url = official_url if official_url else mirror_url(mirror_path)
            print(f'downloading {filename}', flush=True)
            download(url, dest)
        digest = sha256(dest)
        if digest != expected:
            dest.unlink()
            parser.error(f'{filename}: SHA256 mismatch: {digest} != {expected}')
        print(f'verified {dest}: {digest}')


if __name__ == '__main__':
    main()
