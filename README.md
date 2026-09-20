# btt-action

Install [btt](https://github.com/Maddiaa0/btt) and check that your tests match their `.tree` specifications.
Downloads a prebuilt binary and verifies its SHA-256 checksum. No Rust toolchain or package manager is required.

> This action is awaiting its first release. The examples below describe the planned `v1` tag.
> btt must publish `v0.2.0` before the default installation can run.

## Check your project

Add these steps after your job's setup:

```yaml
steps:
  - uses: actions/checkout@v4.2.2
  - uses: Maddiaa0/btt-action@v1
```

The action runs `btt check` in the workspace and fails if the check fails.
It respects `btt.toml`, including per-directory configuration, and checked-in `.btt/packs/`.
Release binaries include WASM grammar support.

`btt check` checks test structure. To execute the tests too, provide your project's Bash command:

```yaml
- uses: Maddiaa0/btt-action@v1
  with:
    working-directory: crates/core
    test-command: cargo test --locked
```

Install any toolchain and project dependencies before this step. The test command runs only after
the tree check succeeds, in the same working directory. A failing command or pipeline fails the step.
Keep the command in trusted workflow code; do not interpolate pull request titles or other untrusted text into it.

## Inputs

| Input | Default | Behavior |
| --- | --- | --- |
| `version` | `0.2.0` | Exact stable btt release, with or without `v`. No `latest`, ranges, or prereleases. |
| `working-directory` | `.` | Directory for the check and test command, relative to the workspace. |
| `paths` | Empty | Tree files or directories, one per line, relative to `working-directory`. Empty checks the project. Paths are literal, not shell globs. |
| `install-only` | `false` | Set to `'true'` to install without running checks or the test command. |
| `test-command` | Empty | Bash command to execute after a successful check. |

Choose specific directories with multiline paths:

```yaml
- uses: Maddiaa0/btt-action@v1
  with:
    paths: |
      crates/core
      packages/web
```

For separate check and test steps:

```yaml
- uses: Maddiaa0/btt-action@v1
  with:
    install-only: 'true'
- run: btt check
- run: cargo test --locked
```

## Outputs

| Output | Value |
| --- | --- |
| `version` | Installed version without the `v` prefix. |
| `binary-path` | Absolute path to the installed executable. |

The executable is also added to `PATH` for later steps in the same job.

## Runners and permissions

Supports Linux and macOS on x64 and ARM64, matching btt's release targets.
Linux uses the musl build. Windows binaries are not published.
Self-hosted runners need Bash, curl, tar with xz support, shasum, and Python 3, plus HTTPS access to GitHub release assets.

The action needs no token or write permissions. Checkout normally needs `contents: read`.
Once this repository is public, the action can run on fork pull requests without custom secrets.

Each invocation downloads its own binary into the runner's temporary directory. There is no shared cache,
source-build fallback, or automatic pack installation. Checksums detect mismatched downloads; they do not
independently authenticate a compromised release. Pin the action to a full commit SHA and pin `version`
for reproducible workflows. Update the default btt version only after that release is at least 14 days old.

Check errors and warnings appear as GitHub Actions annotations on the breached `.tree` file,
with the specification line when BTT reports one. Each annotation includes the test URL; the job
summary also provides clickable specification and test links at the checked commit. Extra tests
link to their source line. Grammar errors link to a matching sibling test when one exists.
Uncovered tests are annotated on the test file itself. GitHub shows annotations inline in a pull
request's Files changed view when their location belongs to its diff; the Checks view and job
summary retain findings outside that diff. No review token or write permission is required.

Reporting runs even when BTT fails and preserves its failure status. btt's configured severities
determine whether the check fails. `continue-on-error: true` in the calling workflow makes that
failure advisory. Use the action's default check mode to get annotations; `install-only: 'true'`
followed by a separate `btt check` only prints the CLI output.
If btt finds no specs, it prints `no .tree files found` and succeeds, matching the CLI's current behavior.

## Verify changes

Run the dependency-free fixture tests:

```bash
bash -n scripts/install.sh scripts/check.sh
python3 -m unittest discover -s tests -v
```

Tests exercise download selection, checksum verification, executable version validation, literal paths,
working directories, and failure propagation. They use generated archives and do not download btt.
CI runs them on Linux and macOS.

Once a btt release is available and at least 14 days old, manually run the CI workflow with its exact
version to exercise real downloads, installation, scaffolding, passing checks, and drift detection
on all four runner targets.

Before publishing `v1`, make this repository public, run that smoke test successfully, and remove
the prerelease notice above. The default `0.2.0` is reserved for btt's current package version and
has not yet been validated against a published archive.
