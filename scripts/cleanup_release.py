#!/usr/bin/env python3
"""Keep only packages referenced by the verified, published Pacman database."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import urllib.request


def package_pattern(name):
    if not re.fullmatch(r'[a-z0-9][a-z0-9+_.-]*', name):
        raise ValueError(f'Invalid package name: {name!r}')
    return re.compile(re.escape(name) + r'-[0-9][A-Za-z0-9+.~_]*-[0-9]+-x86_64\.pkg\.tar\.zst')


def validate_packages(packages):
    if not packages:
        raise ValueError('Refusing cleanup with an empty package database')
    for name, filename in packages.items():
        if not package_pattern(name).fullmatch(filename):
            raise ValueError(f'Unexpected package filename: {filename!r}')


def database_packages(database):
    packages = {}
    with tarfile.open(database, 'r:*') as archive:
        for member in archive:
            if not member.isfile() or not member.name.endswith('/desc'):
                continue
            with archive.extractfile(member) as description:
                sections = description.read().decode().strip().split('\n\n')
            fields = {lines[0]: lines[1:] for section in sections if (lines := section.splitlines())}
            name, = fields['%NAME%']
            filename, = fields['%FILENAME%']
            if name in packages:
                raise ValueError(f'Duplicate package: {name}')
            packages[name] = filename
    validate_packages(packages)
    return packages


def obsolete_assets(packages, assets):
    validate_packages(packages)
    current = {asset for filename in packages.values() for asset in (filename, filename + '.sig')}
    missing = current - set(assets)
    if missing:
        raise ValueError(f'Current release assets are missing: {sorted(missing)}')
    patterns = [package_pattern(name) for name in packages]
    return sorted(asset for asset in set(assets) - current
                  if any(pattern.fullmatch(asset.removesuffix('.sig')) for pattern in patterns))


def verify_published_database(database, repository, release):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid GitHub repository')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', release):
        raise ValueError('Invalid release tag')
    url = f'https://github.com/{repository}/releases/download/{release}/{database.name}'
    with tempfile.TemporaryDirectory(prefix='release-cleanup-') as temporary:
        remote = Path(temporary) / database.name
        for suffix in ('', '.sig'):
            with urllib.request.urlopen(url + suffix, timeout=60) as response:
                Path(str(remote) + suffix).write_bytes(response.read())
        subprocess.run(['gpg', '--batch', '--verify', str(remote) + '.sig', str(remote)], check=True)
        if remote.read_bytes() != database.read_bytes():
            raise ValueError('Published database differs from the new local database; refusing cleanup')


def cleanup_release(database, repository, release, apply=False):
    packages = database_packages(database)
    verify_published_database(database, repository, release)
    result = subprocess.run(['gh', 'release', 'view', release, '--repo', repository, '--json', 'assets'],
                            check=True, capture_output=True, text=True)
    assets = [asset['name'] for asset in json.loads(result.stdout)['assets']]
    obsolete = obsolete_assets(packages, assets)
    for asset in obsolete:
        if apply:
            subprocess.run(['gh', 'release', 'delete-asset', release, asset, '--yes', '--repo', repository], check=True)
        print(f'{"Deleted" if apply else "Would delete"}: {asset}')
    print(f'Retained {len(packages)} current packages and their signatures; '
          f'{len(obsolete)} obsolete assets {"deleted" if apply else "selected (dry run)"}.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--release', default='repository')
    parser.add_argument('--apply', action='store_true', help='Delete obsolete assets (default: dry run)')
    args = parser.parse_args()
    cleanup_release(args.database, args.repo, args.release, args.apply)
