# Publishing

The package is published to PyPI with GitHub Actions Trusted Publishing. This
uses short-lived OpenID Connect credentials and does not require a PyPI API
token in repository secrets.

## One-time PyPI setup

Create a pending publisher for a new project in the PyPI account with these
exact values:

| Field | Value |
|---|---|
| PyPI project name | `ssml-h-tools` |
| GitHub owner | `hangry-labs` |
| GitHub repository | `ssml-h-tools` |
| Workflow file | `release.yml` |
| Environment name | `pypi` |

In GitHub, create the `pypi` environment and require manual approval for it.
The release workflow grants `id-token: write` only to the publish job.

Before the first release, enable two-factor authentication on the PyPI account
and store its recovery codes outside GitHub. Trusted Publishing does not need a
password or long-lived API token in repository settings.

## Release procedure

1. Replace `Unreleased` in `CHANGELOG.md` with the release date.
2. Set `[project].version` and `ssml_h.__version__` to the same final version.
3. Run the test and distribution checks locally.
4. Push the reviewed commit and create a GitHub Release tagged `v<version>`.
5. Approve the protected `pypi` environment deployment.
6. Confirm the package metadata and files on PyPI.

The workflow refuses to publish when the Git tag, package metadata, and
runtime `__version__` do not agree.
