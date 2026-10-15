#!/usr/bin/env python3
"""Verify repackaged bytes, kernel capabilities and the Debian CA trust chain."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

ROOT = Path(__file__).resolve().parents[1]


def extract_ca(shim):
    data = shim.read_bytes()
    offset = 0
    while True:
        offset = data.find(b'\x30\x82', offset)
        if offset < 0:
            raise ValueError('Debian CA not found in Shim')
        length = int.from_bytes(data[offset + 2:offset + 4], 'big') + 4
        try:
            cert = x509.load_der_x509_certificate(data[offset:offset + length])
            if cert.subject.rfc4514_string() == 'CN=Debian Secure Boot CA':
                return cert.public_bytes(Encoding.PEM)
        except ValueError:
            pass
        offset += 1


def check(directory):
    lock = json.loads((ROOT / 'sources.lock.json').read_text())
    abi = lock['kernel_abi']
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        expected = root / 'debian'
        actual = root / 'arch'
        expected.mkdir()
        actual.mkdir()
        for name, info in lock['packages'].items():
            archives = list(directory.glob(f'{name}-{info["pkgver"]}-*.pkg.tar.zst'))
            if len(archives) != 1:
                raise ValueError(f'Expected one built archive for {name}, found {len(archives)}')
            subprocess.run(['bsdtar', '-xf', str(archives[0].resolve()), '-C', str(actual)], check=True)
            for source in info['sources']:
                deb = ROOT / 'packages' / name / source['filename'].split('/')[-1]
                if hashlib.sha256(deb.read_bytes()).hexdigest() != source['sha256']:
                    raise ValueError('Debian archive changed after resolution')
                member = next(x for x in subprocess.check_output(['bsdtar', '-tf', str(deb)], text=True).splitlines() if x.startswith('data.tar'))
                with subprocess.Popen(['bsdtar', '-xOf', str(deb), member], stdout=subprocess.PIPE) as process:
                    subprocess.run(['bsdtar', '-xf', '-', '-C', str(expected)], stdin=process.stdout, check=True)
                    if process.wait():
                        raise ValueError('Debian extraction failed')
        compared = 0
        for source in expected.rglob('*'):
            if not source.is_file() or not ('.ko' in source.name or '.efi' in source.name or source.name.startswith('vmlinuz')):
                continue
            relative = source.relative_to(expected)
            target = actual / relative
            if str(relative) == 'usr/lib/systemd/boot/efi/systemd-bootx64.efi.signed':
                target = actual / 'usr/lib/arch-debian-kernel/systemd-boot/systemd-bootx64.efi.signed'
            if relative.parts[0] == 'lib':
                target = actual / 'usr' / relative
            if relative.parts[0] == 'boot' and source.name.startswith('vmlinuz-'):
                target = actual / 'usr/lib/modules' / abi / 'vmlinuz'
            if not target.is_file() or source.read_bytes() != target.read_bytes():
                raise ValueError(f'Signed payload modified or missing: {relative}')
            compared += 1
        if compared < 100:
            raise ValueError('Unexpectedly few signed kernel payloads')
        kernel = actual / 'usr/lib/modules' / abi / 'vmlinuz'
        boot = actual / 'usr/lib/arch-debian-kernel/systemd-boot/systemd-bootx64.efi.signed'
        if (actual / 'usr/lib/systemd/boot/efi').exists():
            raise ValueError('Debian bootloader must not populate the standard bootctl source directory')
        shim = actual / 'usr/lib/shim/shimx64.efi.signed'
        cert = root / 'debian-ca.pem'
        cert.write_bytes(extract_ca(shim))
        for binary in [kernel, boot]:
            subprocess.run(['sbverify', '--cert', str(cert), str(binary)], check=True)
        result = subprocess.check_output(['sbverify', '--list', str(shim)], text=True)
        if 'Microsoft' not in result:
            raise ValueError('Missing Microsoft signature on Shim')
        configs = list(actual.glob(f'usr/lib/modules/{abi}/config'))
        if not configs:
            raise ValueError('Missing packaged kernel config')
        config = configs[0].read_text()
        for option in ['BPF_LSM', 'BPF_SYSCALL', 'BPF_JIT', 'DEBUG_INFO_BTF', 'SECURITY_LOCKDOWN_LSM', 'TCG_TPM', 'INTEL_IOMMU', 'AMD_IOMMU', 'EFI_STUB', 'MODULE_SIG']:
            if f'CONFIG_{option}=y\n' not in config:
                raise ValueError(f'Missing required kernel support: {option}')
        lsm = next(line for line in config.splitlines() if line.startswith('CONFIG_LSM='))
        if 'bpf' not in lsm.split('"')[1].split(','):
            raise ValueError('BPF LSM absent from default LSM list')
        print(f'PASS: {compared} EFI/kernel/module payloads byte-identical; Debian CA verifies kernel and systemd-boot; required kernel options present')


if __name__ == '__main__':
    check(Path(sys.argv[1]).resolve())
