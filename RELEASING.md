# Releasing RAG Preflight

Only `rag-preflight/` is published to PyPI. The Chroma, FAISS and shared reference
packages remain source examples in this repository.

## One-time repository setup

1. Make the GitHub repository publicly readable before publishing so the package
   metadata and documentation links do not return 404.
2. Revoke any OpenAI key that has been pasted into a chat, terminal transcript or
   other external system. Never store a replacement key in this repository.
3. In GitHub, create environments named `testpypi` and `pypi`. Configure a required
   reviewer on `pypi` so production publication needs explicit approval.
4. Register this repository and `.github/workflows/release.yml` as a Trusted
   Publisher on TestPyPI and PyPI. No long-lived repository token is required.

Repository visibility, provider-key revocation, PyPI account configuration and
GitHub environment reviewers are account-side actions and cannot be established
by a source commit.

## Release procedure

1. Confirm `main` is clean and current CI is green.
2. Replace the release-candidate wording and changelog heading with the actual
   publication date.
3. Run all library and reference-application tests and type checks.
4. Build into a temporary directory and run `twine check --strict` on the wheel
   and source distribution.
5. Create and push an annotated `v0.1.0` tag. The release workflow builds once,
   publishes that artifact to TestPyPI, installs and smoke-tests it, and then waits
   at the protected `pypi` environment before publishing the same artifact to PyPI.
6. Approve the `pypi` job only after checking the TestPyPI project page and smoke
   results. Cancel it if the metadata, README or installation is wrong.
7. Install `rag-preflight==0.1.0` from PyPI in a clean environment and run the CLI
   smoke test again.
8. Create the GitHub release from the signed tag and attach the checked wheel,
   source distribution and SHA-256 checksums.

PyPI versions are release artifacts. Fix a failed candidate before approving the
production environment; do not overwrite or silently replace a published file.
