import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, RUNNER_TEMP=str(self.root), RUNNER_OS='Linux',
                        RUNNER_ARCH='X64', BTT_VERSION='0.2.0', BTT_INSTALL_ONLY='false',
                        GITHUB_PATH=str(self.root / 'path'), GITHUB_OUTPUT=str(self.root / 'output'),
                        BTT_WORKING_DIRECTORY=str(self.root), BTT_PATHS='', BTT_TEST_COMMAND='',
                        PATH=f'{self.bin}{os.pathsep}{os.environ["PATH"]}')
        self.script('curl', '''#!/usr/bin/env python3
import os, pathlib, shutil, sys
args = sys.argv[1:]
url = args[args.index('-o') - 1]
assert url.startswith('https://github.com/Maddiaa0/btt/releases/download/v0.2.0/')
shutil.copyfile(pathlib.Path(os.environ['RUNNER_TEMP']) / url.rsplit('/', 1)[1], args[args.index('-o') + 1])
''')

    def script(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)
        return path

    def archive(self, target='x86_64-unknown-linux-musl', version='0.2.0'):
        body = f'#!/usr/bin/env bash\necho "btt {version}"\n'.encode()
        archive = self.root / f'btt-cli-{target}.tar.xz'
        with tarfile.open(archive, 'w:xz') as tar:
            entry = tarfile.TarInfo(f'btt-cli-{target}/btt')
            entry.size = len(body)
            entry.mode = 0o755
            tar.addfile(entry, io.BytesIO(body))
        checksum = archive.with_suffix('.xz.sha256')
        checksum.write_text(f'{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n')
        return archive, checksum

    def run_script(self, name):
        return subprocess.run(['bash', str(ROOT / 'scripts' / f'{name}.sh')],
                              env=self.env, text=True, capture_output=True)

    def test_install_verifies_all_platform_archives_and_exports_executable(self):
        for system, arch, target in [
            ('Linux', 'X64', 'x86_64-unknown-linux-musl'),
            ('Linux', 'ARM64', 'aarch64-unknown-linux-musl'),
            ('macOS', 'X64', 'x86_64-apple-darwin'),
            ('macOS', 'ARM64', 'aarch64-apple-darwin'),
        ]:
            with self.subTest(system=system, arch=arch):
                self.env.update(RUNNER_OS=system, RUNNER_ARCH=arch, BTT_VERSION='v0.2.0')
                self.archive(target)
                result = self.run_script('install')
                self.assertEqual(result.returncode, 0, result.stderr)
                binary = Path((self.root / 'path').read_text().splitlines()[-1]) / 'btt'
                self.assertEqual(subprocess.check_output([binary, '--version'], text=True), 'btt 0.2.0\n')
                self.assertIn(f'binary-path={binary}', (self.root / 'output').read_text())
                self.assertIn('version=0.2.0', (self.root / 'output').read_text())
                self.assertEqual(list(self.root.glob('btt-download.*')), [])

    def test_rejects_invalid_inputs_before_download(self):
        for key, value in [('BTT_VERSION', 'latest'), ('BTT_VERSION', '../../bad'),
                           ('BTT_INSTALL_ONLY', 'yes'), ('RUNNER_OS', 'Windows'),
                           ('RUNNER_ARCH', 'ARM')]:
            with self.subTest(key=key, value=value):
                original = self.env[key]
                self.env[key] = value
                result = self.run_script('install')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('::error::', result.stderr)
                self.assertFalse((self.root / 'path').exists())
                self.env[key] = original

    def test_rejects_download_failure(self):
        self.script('curl', '#!/usr/bin/env bash\nexit 22\n')
        result = self.run_script('install')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Could not download', result.stderr)

    def test_rejects_corrupt_archive_and_malformed_checksum(self):
        archive, checksum = self.archive()
        archive.write_bytes(b'corrupted')
        result = self.run_script('install')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        checksum.write_text('not a checksum\n')
        result = self.run_script('install')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('malformed', result.stderr)
        self.assertFalse((self.root / 'path').exists())

    def test_rejects_wrong_executable_version(self):
        self.archive(version='0.1.0')
        result = self.run_script('install')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('does not match', result.stderr)

    def test_paths_are_literal_arguments_and_tests_use_working_directory(self):
        self.script('btt', '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > args\n')
        self.env.update(BTT_PATHS='dir with spaces\r\n\n$(touch injected)\n--help',
                        BTT_TEST_COMMAND='pwd > ran-tests')
        result = self.run_script('check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'args').read_text().splitlines(),
                         ['check', '--', 'dir with spaces', '$(touch injected)', '--help'])
        self.assertFalse((self.root / 'injected').exists())
        self.assertEqual((self.root / 'ran-tests').read_text().strip(), str(self.root))

    def test_check_failure_skips_tests_and_preserves_exit_status(self):
        self.script('btt', '#!/usr/bin/env bash\nexit 7\n')
        self.env['BTT_TEST_COMMAND'] = 'touch ran-tests'
        self.assertEqual(self.run_script('check').returncode, 7)
        self.assertFalse((self.root / 'ran-tests').exists())

    def test_default_checks_project_and_test_pipeline_failure_is_preserved(self):
        self.script('btt', '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > args\n')
        self.assertEqual(self.run_script('check').returncode, 0)
        self.assertEqual((self.root / 'args').read_text(), 'check\n--\n')
        self.env['BTT_TEST_COMMAND'] = 'exit 9'
        self.assertEqual(self.run_script('check').returncode, 9)
        self.env['BTT_TEST_COMMAND'] = 'false | true'
        self.assertNotEqual(self.run_script('check').returncode, 0)


if __name__ == '__main__':
    unittest.main()
