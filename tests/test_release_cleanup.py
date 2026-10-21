import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from unittest.mock import patch, Mock
from pathlib import Path

spec = importlib.util.spec_from_file_location('cleanup_release', Path(__file__).resolve().parents[1] / 'scripts/cleanup_release.py')
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


class ReleaseCleanupTests(unittest.TestCase):
    current = {'linux-debian-bin': 'linux-debian-bin-7.2.11.deb1-1-x86_64.pkg.tar.zst',
               'systemd-boot-debian-bin': 'systemd-boot-debian-bin-262.1.deb1-1-x86_64.pkg.tar.zst'}

    def assets(self, *extra):
        names = [item for filename in self.current.values() for item in [filename, filename + '.sig']]
        return names + list(extra)

    def test_removes_old_packages_and_matching_signatures(self):
        old = 'linux-debian-bin-7.2.10.deb1-1-x86_64.pkg.tar.zst'
        self.assertEqual(cleanup.obsolete_assets(self.current, self.assets(old, old + '.sig')), [old, old + '.sig'])

    def test_current_package_and_signature_are_never_deleted(self):
        self.assertEqual(cleanup.obsolete_assets(self.current, self.assets()), [])

    def test_repository_metadata_and_unrelated_files_are_preserved(self):
        unrelated = ['arch-debian-kernel.db', 'arch-debian-kernel.db.sig', 'repository.asc',
                     'other-package-1.0-1-x86_64.pkg.tar.zst',
                     'linux-debian-bin-headers-7.2.10.deb1-1-x86_64.pkg.tar.zst']
        self.assertEqual(cleanup.obsolete_assets(self.current, self.assets(*unrelated)), [])

    def test_missing_current_payload_aborts_cleanup(self):
        with self.assertRaises(ValueError):
            cleanup.obsolete_assets(self.current, [])

    def test_missing_current_signature_aborts_cleanup(self):
        names = self.assets()
        names.remove(self.current['linux-debian-bin'] + '.sig')
        with self.assertRaises(ValueError):
            cleanup.obsolete_assets(self.current, names)

    def test_empty_database_aborts_cleanup(self):
        with self.assertRaises(ValueError):
            cleanup.obsolete_assets({}, self.assets())

    def test_orphaned_old_signature_is_removed(self):
        old = 'linux-debian-bin-7.2.10.deb1-1-x86_64.pkg.tar.zst.sig'
        self.assertEqual(cleanup.obsolete_assets(self.current, self.assets(old)), [old])

    def test_all_noncurrent_versions_are_removed_without_version_sorting(self):
        old = ['linux-debian-bin-7.2.9.deb1-1-x86_64.pkg.tar.zst',
               'linux-debian-bin-7.2.10.deb1-1-x86_64.pkg.tar.zst']
        self.assertEqual(cleanup.obsolete_assets(self.current, self.assets(*old)), sorted(old))

    def test_database_filenames_are_read_without_extracting_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'repository.db'
            text = '%NAME%\nlinux-debian-bin\n\n%FILENAME%\n' + self.current['linux-debian-bin'] + '\n\n'
            with tarfile.open(database, 'w:gz') as archive:
                member = tarfile.TarInfo('linux-debian-bin-7.2.11.deb1-1/desc')
                member.size = len(text.encode())
                archive.addfile(member, io.BytesIO(text.encode()))
            self.assertEqual(cleanup.database_packages(database), {'linux-debian-bin': self.current['linux-debian-bin']})

    def test_unsafe_database_filename_aborts_cleanup(self):
        with self.assertRaises(ValueError):
            cleanup.obsolete_assets({'linux-debian-bin': '../unsafe.pkg.tar.zst'}, [])

    def test_failed_publication_verification_prevents_all_release_operations(self):
        with patch.object(cleanup, 'database_packages', return_value=self.current), \
                patch.object(cleanup, 'verify_published_database', side_effect=ValueError('Mismatch')), \
                patch.object(cleanup.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                cleanup.cleanup_release(Path('repository.db'), 'owner/repo', 'repository', apply=True)
            run.assert_not_called()

    def test_missing_current_asset_prevents_all_deletions(self):
        with patch.object(cleanup, 'database_packages', return_value=self.current), \
                patch.object(cleanup, 'verify_published_database'), \
                patch.object(cleanup.subprocess, 'run', return_value=Mock(stdout='{"assets": []}')) as run:
            with self.assertRaises(ValueError):
                cleanup.cleanup_release(Path('repository.db'), 'owner/repo', 'repository', apply=True)
            self.assertEqual(run.call_count, 1)

    def test_dry_run_does_not_delete_assets(self):
        assets = self.assets('linux-debian-bin-7.2.10.deb1-1-x86_64.pkg.tar.zst')
        result = Mock(stdout=json.dumps({'assets': [{'name': name} for name in assets]}))
        with patch.object(cleanup, 'database_packages', return_value=self.current), \
                patch.object(cleanup, 'verify_published_database'), \
                patch.object(cleanup.subprocess, 'run', return_value=result) as run:
            cleanup.cleanup_release(Path('repository.db'), 'owner/repo', 'repository')
            self.assertEqual(run.call_count, 1)

    def test_apply_deletes_only_obsolete_assets(self):
        old = 'linux-debian-bin-7.2.10.deb1-1-x86_64.pkg.tar.zst'
        assets = self.assets(old, old + '.sig', 'arch-debian-kernel.db', 'repository.asc')
        result = Mock(stdout=json.dumps({'assets': [{'name': name} for name in assets]}))
        with patch.object(cleanup, 'database_packages', return_value=self.current), \
                patch.object(cleanup, 'verify_published_database'), \
                patch.object(cleanup.subprocess, 'run', return_value=result) as run:
            cleanup.cleanup_release(Path('repository.db'), 'owner/repo', 'repository', apply=True)
            self.assertEqual(run.call_count, 3)
            self.assertEqual([call.args[0] for call in run.call_args_list[1:]], [
                ['gh', 'release', 'delete-asset', 'repository', asset, '--yes', '--repo', 'owner/repo']
                for asset in (old, old + '.sig')])

    def test_public_database_mismatch_aborts_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'repository.db'
            database.write_bytes(b'local database')
            with patch.object(cleanup.urllib.request, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(b'remote')), \
                    patch.object(cleanup.subprocess, 'run'):
                with self.assertRaisesRegex(ValueError, 'differs'):
                    cleanup.verify_published_database(database, 'owner/repo', 'repository')

    def test_invalid_public_signature_aborts_cleanup(self):
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'repository.db'
            database.write_bytes(b'database')
            with patch.object(cleanup.urllib.request, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(b'database')), \
                    patch.object(cleanup.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'gpg')):
                with self.assertRaises(subprocess.CalledProcessError):
                    cleanup.verify_published_database(database, 'owner/repo', 'repository')


if __name__ == '__main__':
    unittest.main()
