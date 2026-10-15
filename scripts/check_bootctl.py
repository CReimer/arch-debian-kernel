#!/usr/bin/env python3
"""Container-only installation test: Debian packages must not change bootctl's source."""
import argparse
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(package, previous=None):
    if not (Path('/.dockerenv').exists() or Path('/run/.containerenv').exists()):
        raise RuntimeError('Run this installation test only in a disposable container')
    official = Path('/usr/lib/systemd/boot/efi/systemd-bootx64.efi')
    legacy = official.with_suffix('.efi.signed')
    relocated = Path('/usr/lib/arch-debian-kernel/systemd-boot/systemd-bootx64.efi.signed')
    before = digest(official)
    if legacy.exists():
        raise RuntimeError('Test container already contains a signed bootctl override')
    if previous:
        subprocess.run(['pacman', '-U', '--noconfirm', str(previous)], check=True)
        if not legacy.is_file():
            raise RuntimeError('Previous package did not reproduce the legacy layout')
    subprocess.run(['pacman', '-U', '--noconfirm', str(package)], check=True)
    if legacy.exists() or not relocated.is_file() or digest(official) != before:
        raise RuntimeError('Package installation interfered with official bootloader files')
    with tempfile.TemporaryDirectory() as temporary:
        esp = Path(temporary) / 'esp'
        esp.mkdir(mode=0o700)
        env = dict(os.environ, SYSTEMD_RELAX_ESP_CHECKS='1')
        command = ['bootctl', f'--esp-path={esp}', '--no-variables']
        subprocess.run([*command, 'install'], env=env, check=True)
        targets = [esp / 'EFI/systemd/systemd-bootx64.efi', esp / 'EFI/BOOT/BOOTX64.EFI']
        if any(digest(target) != before for target in targets):
            raise RuntimeError('bootctl install selected a foreign bootloader')
        result = subprocess.run([*command, 'update'], env=env, capture_output=True, text=True)
        if result.returncode not in (0, 1) or (result.returncode == 1 and 'Skipping' not in result.stdout + result.stderr):
            raise RuntimeError(f'bootctl update failed: {result.stdout}{result.stderr}')
        if any(digest(target) != before for target in targets):
            raise RuntimeError('bootctl update selected a foreign bootloader')
    print('PASS: Debian package leaves official bootctl install/update sources unchanged')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--previous-package', type=Path)
    args = parser.parse_args()
    check(args.package.resolve(), args.previous_package.resolve() if args.previous_package else None)
