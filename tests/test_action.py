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

    def diagnostic(self, output, status=1):
        (self.root / 'btt.toml').write_text('[project]\npacks = ["typescript"]\n')
        self.env.update(GITHUB_WORKSPACE=str(self.root), GITHUB_REPOSITORY='owner/repo',
                        GITHUB_SHA='merge-sha', GITHUB_STEP_SUMMARY=str(self.root / 'summary'))
        self.script('btt', '#!/usr/bin/env python3\nimport sys\nprint(' + repr(output) + ')\nsys.exit(' + str(status) + ')\n')
        return self.run_script('check')

    def test_annotations_link_missing_and_extra_tests_at_pr_head(self):
        event = self.root / 'event.json'
        event.write_text('{"pull_request":{"head":{"sha":"head-sha"}}}')
        self.env['GITHUB_EVENT_PATH'] = str(event)
        target = self.root / 'example.test.ts'
        result = self.diagnostic(f'✗ example.tree → {target}\n'
                                 '    error missing test `works` (example.tree:3)\n'
                                 f'    warn  extra   test `other` ({target}:9)\n'
                                 '1 tree file(s), 1 error(s), 1 warning(s)')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('::error title=BTT,file=example.tree,line=3::', result.stdout)
        self.assertIn('::warning title=BTT,file=example.tree,line=1::', result.stdout)
        summary = (self.root / 'summary').read_text()
        self.assertIn('/blob/head-sha/example.test.ts#L9', summary)
        self.assertIn('/blob/head-sha/example.tree#L3', summary)
        self.assertNotIn('merge-sha', summary)

    def test_grammar_annotations_resolve_working_directory_and_escape_paths(self):
        project = self.root / 'nested'
        project.mkdir()
        (project / 'btt.toml').write_text('[project]\npacks = ["typescript"]\n')
        (project / 'a,b%.test.ts').write_text('')
        self.env['BTT_WORKING_DIRECTORY'] = str(project)
        result = self.diagnostic('✗ a,b%.tree\n'
                                 '    error a,b%.tree: line 2: bad node <script>', 2)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('file=nested/a%2Cb%25.tree,line=2::', result.stdout)
        self.assertIn('nested/a%252Cb%2525.test.ts#L1', result.stdout)
        summary = (self.root / 'summary').read_text()
        self.assertIn('&lt;script&gt;', summary)
        self.assertNotIn('<script>', summary)

    def test_report_handles_missing_target_uncovered_and_order_warnings(self):
        result = self.diagnostic('✗ absent.tree — no matching test file\n'
                                 '    tried absent.rs\n'
                                 '✗ order.tree → order.rs\n'
                                 '    warn  order differs under `example`\n'
                                 '! orphan.rs — 1 test(s), not covered by any .tree')
        self.assertEqual(result.returncode, 1)
        self.assertIn('::error title=BTT,file=absent.tree,line=1::', result.stdout)
        self.assertIn('::warning title=BTT,file=order.tree,line=1::', result.stdout)
        self.assertIn('::warning title=BTT,file=orphan.rs,line=1::', result.stdout)
        self.assertIn('No test target reported', (self.root / 'summary').read_text())

    def test_warning_only_checks_still_run_tests(self):
        self.env['BTT_TEST_COMMAND'] = 'touch ran-tests'
        result = self.diagnostic('✗ example.tree → example.rs\n'
                                 '    warn  order differs under `example`', 0)
        self.assertEqual(result.returncode, 0)
        self.assertTrue((self.root / 'ran-tests').exists())
        self.assertIn('::warning ', result.stdout)

    def test_raw_output_cannot_inject_workflow_commands(self):
        result = self.diagnostic('::error file=forged.tree,line=1::forged', 0)
        lines = result.stdout.splitlines()
        token = lines[0].removeprefix('::stop-commands::')
        self.assertEqual(lines[1], '::error file=forged.tree,line=1::forged')
        self.assertEqual(lines[2], f'::{token}::')
        self.assertEqual(result.returncode, 0)

    def test_reporting_failure_does_not_replace_btt_failure(self):
        self.env['GITHUB_EVENT_PATH'] = str(self.root / 'missing-event')
        self.assertEqual(self.diagnostic('', 7).returncode, 7)


if __name__ == '__main__':
    unittest.main()
