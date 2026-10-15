import datetime as dt
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('update', Path(__file__).resolve().parents[1] / 'scripts/update.py')
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


class ArchiveTests(unittest.TestCase):
    now = dt.datetime(2026, 10, 15, tzinfo=dt.timezone.utc)

    def release(self, date='Thu, 15 Oct 2026 00:00:00 +0000', extra=''):
        return f'Date: {date}\nCodename: sid\nArchitectures: amd64 arm64\n{extra}'

    def test_multiline_checksum_field(self):
        self.assertEqual(update.fields('SHA256:\n abc 42 main/Packages.xz\n')['SHA256'].strip(), 'abc 42 main/Packages.xz')

    def test_helper_update_bumps_arch_release(self):
        previous = 'pkgver=1.0\npkgrel=3\nsource=old\n'
        generated = 'pkgver=1.0\npkgrel=1\nsource=new\n'
        self.assertIn('pkgrel=4\n', update.preserve_release(generated, previous))

    def test_unchanged_recipe_keeps_release(self):
        previous = 'pkgver=1.0\npkgrel=3\nsource=old\n'
        self.assertEqual(update.preserve_release(previous.replace('pkgrel=3', 'pkgrel=1'), previous), previous)

    def test_new_upstream_resets_release(self):
        previous = 'pkgver=1.0\npkgrel=3\n'
        generated = 'pkgver=1.1\npkgrel=1\n'
        self.assertEqual(update.preserve_release(generated, previous), generated)

    def test_current_release(self):
        self.assertEqual(update.verify_release(self.release(), self.now)['Codename'], 'sid')

    def test_stale_release_rejected(self):
        with self.assertRaises(ValueError):
            update.verify_release(self.release('Thu, 01 Oct 2026 00:00:00 +0000'), self.now)

    def test_future_release_rejected(self):
        with self.assertRaises(ValueError):
            update.verify_release(self.release('Fri, 16 Oct 2026 00:00:00 +0000'), self.now)

    def test_expired_release_rejected(self):
        with self.assertRaises(ValueError):
            update.verify_release(self.release(extra='Valid-Until: Wed, 14 Oct 2026 00:00:00 +0000\n'), self.now)

    def test_wrong_suite_rejected(self):
        with self.assertRaises(ValueError):
            update.verify_release(self.release().replace('sid', 'trixie'), self.now)

    def test_path_traversal_rejected(self):
        for path in ['pool/../etc/passwd', '/tmp/a.deb', 'https://evil/a.deb', 'pool/$(id).deb']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                update.checked_path(path)

    def records(self):
        return {
            'linux-image-amd64': {'Depends': 'linux-image-7.2.10+deb14-amd64 (= 7.2.10-1)'},
            'linux-image-7.2.10+deb14-amd64': {'Version': '7.2.10-1', 'Source': 'linux-signed-amd64', 'Depends': 'linux-binary-7.2.10+deb14-amd64 (= 7.2.10-1), linux-modules-7.2.10+deb14-amd64 (= 7.2.10-1)'},
            'linux-binary-7.2.10+deb14-amd64': {'Version': '7.2.10-1'},
            'linux-modules-7.2.10+deb14-amd64': {'Version': '7.2.10-1'},
        }

    def test_resolves_exact_matching_binaries(self):
        version, abi, names = update.resolve_kernel(self.records())
        self.assertEqual(version, '7.2.10-1')
        self.assertEqual(abi, '7.2.10+deb14-amd64')
        self.assertIn('linux-modules-7.2.10+deb14-amd64', names)

    def test_mismatched_modules_rejected(self):
        records = self.records()
        records['linux-modules-7.2.10+deb14-amd64']['Version'] = '7.2.9-1'
        with self.assertRaises(ValueError):
            update.resolve_kernel(records)

    def test_unsigned_source_rejected(self):
        records = self.records()
        records['linux-image-7.2.10+deb14-amd64']['Source'] = 'linux'
        with self.assertRaises(ValueError):
            update.resolve_kernel(records)

    def test_shell_injection_version_rejected(self):
        with self.assertRaises(ValueError):
            update.pkgver('7.2.10;id')


if __name__ == '__main__':
    unittest.main()
