# Release checklist

The workflow to cut a tagged release of TheWeave that the installer can fetch.

## Pre-release

- [ ] All intended changes committed on `main`
- [ ] [`CHANGELOG.md`](../CHANGELOG.md) `[Unreleased]` section moved to the new version's heading
- [ ] [`pyproject.toml`](../pyproject.toml) `version = "X.Y.Z"` bumped
- [ ] `README.md` version badge bumped (line with `version-X.Y.Z-orange`)
- [ ] `install-weave.sh` default `WEAVE_VERSION="X.Y.Z"` bumped
- [ ] `weave-cli doctor` green on `seed-vault/` and `personas/sonnet/`
- [ ] `pytest` passes

## Tag + push

```bash
git add -p   # review hunks
git commit -m "Release vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z — <one-line summary>"
git push origin main vX.Y.Z
```

## GitHub release

The auto-generated source tarball at `/archive/refs/tags/vX.Y.Z.tar.gz` is what `install-weave.sh` downloads — it's created automatically when the tag is pushed and requires no manual upload. **But** the installer itself needs to be uploaded as a release asset so users can fetch it from `/releases/latest/download/install-weave.sh`.

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --notes-file <(awk '/^## \['"X.Y.Z"'\]/,/^## \[/' CHANGELOG.md | head -n -1) \
  install-weave.sh
```

Or via the GitHub UI: Releases → Draft new release → choose tag → upload `install-weave.sh` as asset.

## Smoke-test the public install

From a clean machine (or VM), with no clone of the repo:

```bash
curl -sSL https://github.com/TheWeaveSC/theweave/releases/latest/download/install-weave.sh | bash
```

Should:
1. Pass preflight (Python ≥3.11, curl, tar)
2. Download tarball from `/archive/refs/tags/vX.Y.Z.tar.gz`
3. Create venv, install package
4. Symlink `weave-cli` into `~/.local/bin/` if on PATH
5. Run `weave-cli doctor` — all green

If any step fails, the user sees the failure point and the script exits non-zero.

## Visibility note

The auto-generated `/archive/refs/tags/` tarball is **public-readable only if the repo is public**. While the repo is private, the install path will not work for outside testers — even with the install script in hand. The public flip and the install path are coupled.
