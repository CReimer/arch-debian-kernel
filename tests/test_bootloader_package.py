import importlib.util
import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('update', Path(__file__).resolve().parents[1] / 'scripts/update.py')
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


class BootloaderPackageTests(unittest.TestCase):
    def test_signed_bootloader_is_outside_bootctl_source_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = b'Unmodified Debian-signed EFI payload fixture'
            original = 'usr/lib/systemd/boot/efi/systemd-bootx64.efi.signed'
            relocated = 'usr/lib/arch-debian-kernel/systemd-boot/systemd-bootx64.efi.signed'
            with tarfile.open(root / 'data.tar', 'w') as archive:
                info = tarfile.TarInfo(original)
                info.size = len(binary)
                archive.addfile(info, io.BytesIO(binary))
            (root / 'debian-binary').write_text('2.0\n')
            subprocess.run(['ar', 'rc', str(root / 'fixture.deb'), str(root / 'debian-binary'), str(root / 'data.tar')], check=True)
            recipe = update.recipe('systemd-boot-debian-bin', '262-1', [{'filename': 'pool/fixture.deb', 'sha256': '0' * 64}])
            (root / 'PKGBUILD').write_text(recipe)
            destination = root / 'package'
            destination.mkdir()
            env = dict(os.environ, srcdir=str(root), pkgdir=str(destination), startdir=str(root))
            subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', 'source "$1"; package', 'test', str(root / 'PKGBUILD')], env=env, check=True)
            self.assertFalse((destination / original).exists(), 'Debian binary must not override bootctl source selection')
            self.assertEqual((destination / relocated).read_bytes(), binary)
            self.assertFalse((destination / 'usr/lib/systemd/boot/efi').exists())


if __name__ == '__main__':
    unittest.main()
